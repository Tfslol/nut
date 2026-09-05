"""Static portfolio-interest alignment and conflict review for the RM workbench.

The fact packet in this module is deliberately deterministic.  It is the only
source of figures supplied to the optional language-model analysis; the model
can describe and prioritise the supplied facts, but it cannot calculate or
approve an action.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Literal

import pandas as pd
from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

from singhacks26.ai_brief import (
    DEFAULT_MODEL,
    DEFAULT_REASONING_EFFORT,
    NUMBER_PATTERN,
    PROHIBITED_PATTERNS,
    SUPPORTED_REASONING_EFFORTS,
)
from singhacks26.intelligence import AS_OF, portfolio_mandate_review, usd_per_unit
from singhacks26.workbench import CURATED_THEMES

CALCULATION_VERSION = "alignment/1.4"
DIMENSION_STATUSES = Literal["aligned", "partially_aligned", "review", "misaligned", "conflict"]
OVERALL_BANDS = Literal["aligned", "partially_aligned", "review", "misaligned", "conflict"]
CONFLICT_CATEGORIES = Literal["risk_profile", "mandate", "objectives", "event"]
CONFLICT_SEVERITIES = Literal["Urgent", "High", "Medium", "Low"]

# Keep this taxonomy in sync with the controlled event-to-client mapping in
# app.py.  It is intentionally a small, approved lexicon rather than fuzzy
# matching over client text.
THEME_LEXICON = {
    "gold": ["gold", "precious metals", "inflation hedge"],
    "energy": ["energy", "oil", "lng", "shipping", "transport", "gulf"],
    "technology": ["technology", "information technology", "growth equity"],
    "rates": ["duration", "fixed income", "bond", "credit", "yield", "rate"],
    "private credit": ["private credit", "semi-liquid", "redemption", "gate"],
    "real estate": ["real estate", "property"],
}
SEVERITY_RANK = {"Urgent": 4, "High": 3, "Medium": 2, "Low": 1}

# Presentation preload set: deliberately spans a severe suitability mismatch,
# a clean alignment case, a concentrated technology/collateral case, and a
# diversified family-office/liquidity case.
PRESENTATION_CLIENTS = ("CL-0003", "CL-0010", "CL-0013", "CL-0017")


class AlignmentDimensions(BaseModel):
    """Status for the four alignment dimensions in the PRD contract."""

    risk_profile_alignment: DIMENSION_STATUSES
    mandate_alignment: DIMENSION_STATUSES
    objectives_life_event_alignment: DIMENSION_STATUSES
    event_consistency: DIMENSION_STATUSES


class Conflict(BaseModel):
    """A review lead that an RM can inspect and discuss."""

    conflict_id: str
    category: CONFLICT_CATEGORIES
    severity: CONFLICT_SEVERITIES
    headline: str
    detail: str
    evidence_ids: list[str] = Field(min_length=1)
    discussion_topic: str


class AlignmentReport(BaseModel):
    """Structured, guardrailed alignment output returned by the LLM."""

    client_id: str
    as_of: str
    overall_band: OVERALL_BANDS
    dimensions: AlignmentDimensions
    strengths: list[str] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


def _empty_store() -> dict[str, Any]:
    return {"schema_version": "alignment/1.0", "reports": {}}


def _records(frame: pd.DataFrame, columns: list[str] | None = None) -> list[dict[str, Any]]:
    if columns is not None:
        available = [column for column in columns if column in frame.columns]
        frame = frame[available]
    if frame.empty:
        return []
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def _clean_note(vault_text: str | None) -> str:
    """Keep the supplied note censored, including its age-range frontmatter."""
    text = vault_text or ""
    return re.sub(r"^age_range:.*$", "age_range: redacted", text, flags=re.MULTILINE)


def _client_row(data: dict[str, Any], client_id: str) -> pd.Series:
    clients = data.get("clients")
    if clients is None or "client_id" not in clients:
        raise ValueError("Alignment data must include clients with client_id.")
    rows = clients.loc[clients.client_id == client_id]
    if rows.empty:
        raise ValueError(f"Unknown client_id: {client_id}")
    return rows.iloc[0]


def _themes(text: str) -> list[str]:
    clean = str(text).lower()
    return [theme for theme, words in THEME_LEXICON.items() if any(word in clean for word in words)]


def _event_rows(data: dict[str, Any], client: pd.Series, positions: pd.DataFrame) -> list[dict[str, Any]]:
    event_log = data.get("event_log", pd.DataFrame())
    if event_log.empty:
        return []
    position_text = " ".join(
        positions[[column for column in ["asset_class", "sub_asset_class", "sector", "region"] if column in positions]]
        .fillna("")
        .astype(str)
        .agg(" ".join, axis=1)
    )
    notes = data.get("rm_notes", [])
    client_notes = [note for note in notes if note.get("client_id") == client.client_id]
    note_text = " ".join(str(note.get("note", "")) for note in client_notes)
    client_themes = set(
        _themes(
            " ".join(
                [
                    position_text,
                    str(client.get("objectives", "")),
                    str(client.get("source_of_wealth", "")),
                    note_text,
                ]
            )
        )
    )
    matched: list[dict[str, Any]] = []
    for _, event in event_log.iterrows():
        event_themes = set(_themes(f"{event.get('primary_transmission', '')} {event.get('description', '')}"))
        overlap = sorted(client_themes & event_themes)
        if not overlap:
            continue
        event_date = str(event.event_date)
        matched.append(
            {
                "event_id": f"event_log.csv:{event_date}",
                "event_date": event_date,
                "event_type": str(event.event_type),
                "region": str(event.region),
                "severity": str(event.severity),
                "description": str(event.description),
                "primary_transmission": str(event.primary_transmission),
                "matched_themes": overlap,
                "evidence_id": f"event_log.csv:{event_date}",
            }
        )
    return matched


def _evidence_ids(
    client_id: str,
    portfolios: pd.DataFrame,
    needs: pd.DataFrame,
    facilities: pd.DataFrame,
    commitments: pd.DataFrame,
    events: list[dict[str, Any]],
    vault_text: str | None = None,
) -> list[str]:
    ids = {
        f"clients.csv:{client_id}",
        "holdings.csv:2026-08-26",
        "instruments.csv",
        "mandates.csv",
        "planned_cash_needs.csv",
        "credit_facilities.csv",
        "commitments.csv",
        "event_log.csv",
        "note:Profile",
        "note:Portfolios and AUM by snapshot",
        "note:Mandates in scope",
        "note:Latest holdings (by portfolio, weighted)",
        "note:Allocation by asset class (latest, USD)",
        "note:Look-through: structured-product underlyings",
        "note:Exposure by sector (top 5, latest)",
        "note:Exposure by region (top 5, latest)",
        "note:Planned cash needs",
        "note:Credit facilities",
        "note:RM notes",
        "note:Relevant controlled events (theme match)",
    }
    note_headings = re.findall(r"^#{2,3}\s+(.+?)\s*$", vault_text or "", flags=re.MULTILINE)
    ids.update(f"note:{heading.strip()}" for heading in note_headings)
    ids.update(f"portfolios.csv:{value}" for value in portfolios.portfolio_id)
    ids.update(f"planned_cash_needs.csv:{value}" for value in needs.need_id)
    ids.update(f"credit_facilities.csv:{value}" for value in facilities.facility_id)
    ids.update(f"commitments.csv:{value}" for value in commitments.commitment_id)
    ids.update(event["evidence_id"] for event in events)
    return sorted(ids)


def _theme_exposure(positions: pd.DataFrame, total: float) -> list[dict[str, Any]]:
    results = []
    for theme, instrument_ids in CURATED_THEMES.items():
        members = positions.loc[positions.instrument_id.isin(instrument_ids)]
        value = float(members.market_value_usd.sum())
        if value:
            results.append(
                {
                    "theme": theme,
                    "market_value_usd": value,
                    "household_weight_pct": round(value / total * 100, 2) if total else 0.0,
                    "instrument_ids": sorted(members.instrument_id.unique().tolist()),
                    "evidence_id": "holdings.csv:2026-08-26",
                }
            )
    return sorted(results, key=lambda row: row["market_value_usd"], reverse=True)


def build_alignment_fact_packet(data: dict[str, Any], client_id: str, vault_text: str | None = None) -> dict[str, Any]:
    """Build the local, synthetic fact packet used by alignment analysis.

    No client name, actual age, raw RM note collection, or other identity field
    is copied into this packet.  The optional note is expected to be the
    censored Obsidian page; its age-range frontmatter is redacted defensively.
    """
    client = _client_row(data, client_id)
    holdings = data["holdings"]
    latest = AS_OF if AS_OF in set(holdings.snapshot_date.astype(str)) else str(holdings.snapshot_date.max())
    positions = holdings.loc[(holdings.client_id == client_id) & (holdings.snapshot_date.astype(str) == latest)].copy()
    if positions.empty:
        raise ValueError(f"No holdings found for {client_id} at {latest}.")
    portfolios = data["portfolios"].loc[data["portfolios"].client_id == client_id].copy()
    governed = portfolios.loc[portfolios.service_model != "Custody"]
    total = float(positions.market_value_usd.sum())

    mandate_review = portfolio_mandate_review(data, client_id)
    mandate_rows = _records(mandate_review)
    mandate_rules = data["mandates"].loc[data["mandates"].mandate_code.isin(governed.mandate_code)]
    rules = _records(
        mandate_rules,
        [
            "mandate_code",
            "mandate_name",
            "asset_class",
            "min_pct",
            "target_pct",
            "max_pct",
            "max_single_position_pct",
            "mandate_notes",
        ],
    )

    instruments = data["instruments"]
    position_details = positions.merge(
        instruments[
            [
                "instrument_id",
                "concentration_limit_applies",
                "sustainability_excluded",
                "underlying_reference",
            ]
        ],
        on="instrument_id",
        how="left",
        suffixes=("", "_instrument"),
    )
    max_single_by_mandate = mandate_rules.groupby("mandate_code").max_single_position_pct.max().to_dict()
    concentration_rows = []
    exclusions = []
    for _, row in position_details.iterrows():
        portfolio = portfolios.loc[portfolios.portfolio_id == row.portfolio_id]
        mandate_code = str(portfolio.mandate_code.iloc[0]) if not portfolio.empty else ""
        limit = float(max_single_by_mandate.get(mandate_code, 0))
        if (
            str(row.get("concentration_limit_applies", "")) == "Y"
            and str(portfolio.service_model.iloc[0]) != "Custody"
            and float(row.weight_pct) > limit
        ):
            concentration_rows.append(
                {
                    "portfolio_id": row.portfolio_id,
                    "instrument_id": row.instrument_id,
                    "weight_pct": float(row.weight_pct),
                    "max_single_position_pct": limit,
                    "evidence_ids": ["holdings.csv:2026-08-26", "mandates.csv"],
                }
            )
        if str(row.get("sustainability_excluded", "")) == "Y" and str(portfolio.service_model.iloc[0]) != "Custody":
            exclusions.append(
                {
                    "portfolio_id": row.portfolio_id,
                    "instrument_id": row.instrument_id,
                    "market_value_usd": float(row.market_value_usd),
                    "weight_pct": float(row.weight_pct),
                    "evidence_ids": ["instruments.csv", "mandates.csv", "holdings.csv:2026-08-26"],
                }
            )

    lookthrough = []
    for _, row in position_details.iterrows():
        reference = str(row.get("underlying_reference", "") or "").strip()
        lookthrough.append(
            {
                "portfolio_id": row.portfolio_id,
                "instrument_id": row.instrument_id,
                "economic_reference": reference or str(row.instrument_id),
                "market_value_usd": float(row.market_value_usd),
                "household_weight_pct": round(float(row.market_value_usd) / total * 100, 2),
                "liquidity_tier": str(row.liquidity_tier),
                "evidence_id": "holdings.csv:2026-08-26",
            }
        )

    def grouped_exposure(column: str) -> list[dict[str, Any]]:
        grouped = positions.groupby(column, dropna=False).market_value_usd.sum().sort_values(ascending=False)
        return [
            {
                column: str(key) if pd.notna(key) else "Unknown",
                "market_value_usd": float(value),
                "household_weight_pct": round(float(value) / total * 100, 2) if total else 0.0,
                "evidence_id": "holdings.csv:2026-08-26",
            }
            for key, value in grouped.items()
        ]

    liquidity = []
    liquidity_values = positions.groupby("liquidity_tier").market_value_usd.sum().sort_values(ascending=False)
    for tier, value in liquidity_values.items():
        liquidity.append(
            {
                "liquidity_tier": str(tier),
                "market_value_usd": float(value),
                "household_weight_pct": round(float(value) / total * 100, 2) if total else 0.0,
                "evidence_id": "holdings.csv:2026-08-26",
            }
        )
    daily_liquid_usd = float(positions.loc[positions.liquidity_tier == "Daily", "market_value_usd"].sum())

    needs = data.get("planned_cash_needs", pd.DataFrame()).loc[
        data.get("planned_cash_needs", pd.DataFrame()).client_id == client_id
    ]
    cash_needs = []
    for _, need in needs.iterrows():
        amount = float(need.amount)
        amount_usd = amount * usd_per_unit(data["market_context"], str(need.currency), latest)
        cash_needs.append(
            {
                "need_id": str(need.need_id),
                "description": str(need.description),
                "currency": str(need.currency),
                "amount": amount,
                "amount_usd": amount_usd,
                "due_from": str(need.due_from),
                "due_to": str(need.due_to),
                "recurrence": str(need.recurrence),
                "certainty": str(need.certainty),
                "daily_liquid_assets_usd": daily_liquid_usd,
                "liquid_assets_less_need_usd": daily_liquid_usd - amount_usd,
                "evidence_id": f"planned_cash_needs.csv:{need.need_id}",
            }
        )

    facilities = data.get("credit_facilities", pd.DataFrame()).loc[
        data.get("credit_facilities", pd.DataFrame()).client_id == client_id
    ]
    facility_rows = []
    for _, facility in facilities.iterrows():
        ltv = float(facility[f"ltv_pct_{latest}"])
        trigger = float(facility.margin_call_ltv_pct)
        facility_rows.append(
            {
                "facility_id": str(facility.facility_id),
                "facility_type": str(facility.facility_type),
                "facility_ccy": str(facility.facility_ccy),
                "portfolio_id": str(facility.collateral_portfolio_id),
                "drawn": float(facility[f"drawn_{latest}"]),
                "lending_value": float(facility[f"lending_value_{latest}"]),
                "headroom": float(facility[f"headroom_{latest}"]),
                "ltv_pct": ltv,
                "margin_call_ltv_pct": trigger,
                "headroom_to_margin_call_pct": trigger - ltv,
                "evidence_id": f"credit_facilities.csv:{facility.facility_id}",
            }
        )

    commitments = data.get("commitments", pd.DataFrame()).loc[
        data.get("commitments", pd.DataFrame()).client_id == client_id
    ]
    commitment_rows = _records(
        commitments,
        ["commitment_id", "portfolio_id", "currency", "uncalled", "expected_call_window"],
    )
    for row in commitment_rows:
        row["evidence_id"] = f"commitments.csv:{row['commitment_id']}"

    events = _event_rows(data, client, positions)
    allowed_evidence_ids = _evidence_ids(client_id, portfolios, needs, facilities, commitments, events, vault_text)

    packet = {
        "synthetic_data": True,
        "calculation_version": CALCULATION_VERSION,
        "client_id": client_id,
        "as_of": latest,
        "censored_static_note": _clean_note(vault_text),
        "client_context": {
            "risk_profile": str(client.risk_profile),
            "risk_tolerance_score": float(client.risk_tolerance_score),
            "investment_horizon_years": float(client.investment_horizon_years),
            "liquidity_needs": str(client.liquidity_needs),
            "life_stage": str(client.life_stage),
            "source_of_wealth": str(client.source_of_wealth),
            "tax_domicile": str(client.tax_domicile),
            "objectives": str(client.objectives),
            "base_currency": str(client.base_currency),
            "wealth_band": str(client.wealth_band),
        },
        "household": {
            "portfolio_ids": sorted(portfolios.portfolio_id.tolist()),
            "governed_portfolio_ids": sorted(governed.portfolio_id.tolist()),
            "total_market_value_usd": total,
            "allocation_by_asset_class": [
                {
                    "asset_class": str(asset_class),
                    "market_value_usd": float(value),
                    "household_weight_pct": round(float(value) / total * 100, 2),
                    "evidence_id": "holdings.csv:2026-08-26",
                }
                for asset_class, value in (
                    positions.groupby("asset_class").market_value_usd.sum().sort_values(ascending=False).items()
                )
            ],
            "sector_exposure": grouped_exposure("sector"),
            "region_exposure": grouped_exposure("region"),
            "liquidity_tiers": liquidity,
            "daily_liquid_assets_usd": daily_liquid_usd,
        },
        "mandate": {
            "portfolio_reviews": mandate_rows,
            "rules": rules,
            "binding_exclusion_flags": exclusions,
            "single_position_flags": concentration_rows,
        },
        "lookthrough_exposure": lookthrough,
        "planned_cash_needs": cash_needs,
        "credit_facilities": facility_rows,
        "commitments": commitment_rows,
        "curated_theme_exposure": _theme_exposure(positions, total),
        "matched_controlled_events": events,
        "allowed_evidence_ids": allowed_evidence_ids,
    }
    return packet


def _number_claims(text: str) -> list[tuple[Decimal, int, str]]:
    """Extract numeric claims, retaining precision for safe display rounding."""
    claims = []
    scales = {
        "": Decimal("1"),
        "%": Decimal("1"),
        "m": Decimal("1000000"),
        "bn": Decimal("1000000000"),
    }
    for token in NUMBER_PATTERN.findall(text):
        suffix = ""
        lower = token.lower()
        for candidate in ("bn", "%", "m"):
            if lower.endswith(candidate):
                suffix = candidate
                break
        raw = token[: -len(suffix)] if suffix else token
        try:
            decimal_places = len(raw.partition(".")[2])
            claims.append((Decimal(raw.replace(",", "")) * scales[suffix], decimal_places, token))
        except InvalidOperation:
            continue
    return claims


def _unsupported_number_tokens(source: str, candidate: str) -> set[str]:
    allowed_claims = _number_claims(source)
    allowed_values = {value for value, _, _ in allowed_claims}
    unsupported = set()
    for value, decimal_places, token in _number_claims(candidate):
        if value in allowed_values:
            continue
        quantum = Decimal(1).scaleb(-decimal_places)
        if any(value == allowed.quantize(quantum) for allowed in allowed_values):
            continue
        unsupported.add(token.lower())
    return unsupported


def _validate_numbers_and_language(report: AlignmentReport, fact_packet: dict[str, Any]) -> None:
    source = json.dumps(fact_packet, ensure_ascii=False)
    candidate = report.model_dump_json()
    unsupported = _unsupported_number_tokens(source, candidate)
    if unsupported:
        raise RuntimeError(f"AI report introduced unsupported numeric claims: {sorted(unsupported)}")
    for pattern in PROHIBITED_PATTERNS:
        if pattern.search(candidate):
            raise RuntimeError(f"AI report failed the prohibited-language guardrail: {pattern.pattern}")


def validate_alignment_report(report: AlignmentReport, fact_packet: dict[str, Any]) -> None:
    """Validate evidence, event provenance, numbers and advisory language."""
    if report.client_id != fact_packet["client_id"]:
        raise RuntimeError("AI report client_id does not match the fact packet.")
    allowed = set(fact_packet["allowed_evidence_ids"])
    event_evidence = {item["evidence_id"] for item in fact_packet["matched_controlled_events"]}
    for conflict in report.conflicts:
        unknown = set(conflict.evidence_ids) - allowed
        if conflict.category == "event":
            matched = set(conflict.evidence_ids) & event_evidence
            if not matched:
                raise RuntimeError("Event-consistency conflicts must cite at least one matched event_log.csv row.")
        if unknown:
            raise RuntimeError(f"AI returned unsupported evidence IDs: {sorted(unknown)}")
    _validate_numbers_and_language(report, fact_packet)


def analyze_alignment(
    data: dict[str, Any], client_id: str, vault_text: str | None = None
) -> tuple[AlignmentReport, str]:
    """Ask OpenAI to prioritise a deterministic packet for RM review."""
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured for alignment analysis.")
    model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
    reasoning_effort = os.getenv("OPENAI_REASONING_EFFORT", DEFAULT_REASONING_EFFORT)
    if reasoning_effort not in SUPPORTED_REASONING_EFFORTS:
        supported = ", ".join(sorted(SUPPORTED_REASONING_EFFORTS))
        raise RuntimeError(f"Unsupported OPENAI_REASONING_EFFORT={reasoning_effort!r}. Use one of: {supported}.")
    packet = build_alignment_fact_packet(data, client_id, vault_text)
    instructions = (
        "You are preparing a private-bank relationship manager's alignment review. "
        "Use only the supplied synthetic fact packet and censored note. Do not calculate, "
        "invent numbers, infer causation, recommend a trade, or give tax conclusions. "
        "Distinguish client belief from verified observation. Return concise strengths, "
        "uncertainties and review leads for the RM; discussion topics are not advice. "
        "Use all four dimensions in the schema. Return ONLY a single JSON object that "
        "matches the requested schema, never markdown prose. Every conflict needs an "
        "allowed evidence ID and a discussion topic. For event conflicts cite at least one "
        "matched event_log.csv ID (you may also cite the affected holdings or note); "
        "event_log.csv is the controlled source of truth."
    )
    last_error: Exception | None = None
    client = OpenAI(api_key=api_key)
    for _ in range(2):  # the model is nondeterministic; retry a transient failure once
        response = client.responses.parse(
            model=model,
            store=False,
            max_output_tokens=1200,
            text={"verbosity": "low"},
            reasoning={"effort": reasoning_effort, "context": "current_turn"},
            instructions=instructions,
            input=json.dumps(packet, ensure_ascii=False),
            text_format=AlignmentReport,
        )
        report = response.output_parsed
        if report is None:
            last_error = RuntimeError("The model did not return a structured alignment report.")
            continue
        try:
            validate_alignment_report(report, packet)
            return report, model
        except Exception as exc:  # retry once, then surface the guardrail error
            last_error = exc
    if last_error is None:
        last_error = RuntimeError("The model did not return a structured alignment report.")
    raise last_error


def _hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def vault_note_hash(vault_text: str | None) -> str:
    return _hash_text(vault_text or "")


def source_data_hash(data: dict[str, Any]) -> str:
    """Hash the source tables that can affect a deterministic alignment packet."""
    names = [
        "clients",
        "portfolios",
        "holdings",
        "instruments",
        "mandates",
        "credit_facilities",
        "commitments",
        "planned_cash_needs",
        "market_context",
        "event_log",
        "rm_notes",
    ]
    payload = {"calculation_version": CALCULATION_VERSION}
    for name in names:
        value = data.get(name)
        if isinstance(value, pd.DataFrame):
            payload[name] = value.to_json(orient="split", date_format="iso")
        else:
            payload[name] = value
    return _hash_text(json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str))


class AlignmentStore:
    """Local JSON cache for per-client alignment reports."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._write_lock = threading.Lock()

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return _empty_store()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return _empty_store()
        if not isinstance(payload, dict):
            return _empty_store()
        payload.setdefault("schema_version", "alignment/1.0")
        payload.setdefault("reports", {})
        return payload

    read = load

    def save_report(
        self,
        *,
        client_id: str,
        report: AlignmentReport | dict[str, Any],
        model: str,
        vault_hash: str,
        source_hash: str,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        payload = self.load()
        report_dict = report.model_dump(mode="json") if isinstance(report, AlignmentReport) else report
        record = {
            "client_id": client_id,
            "status": "ok",
            "report": report_dict,
            "model": model,
            "generated_at": generated_at or datetime.now(UTC).isoformat(timespec="seconds"),
            "vault_note_hash": vault_hash,
            "source_csv_hash": source_hash,
        }
        self._write(payload, client_id, record)
        return record

    def save_error(
        self,
        *,
        client_id: str,
        error: str,
        model: str,
        vault_hash: str,
        source_hash: str,
        generated_at: str | None = None,
    ) -> dict[str, Any]:
        """Persist a failed analysis so unchanged failures are not retried."""
        record = {
            "client_id": client_id,
            "status": "error",
            "report": None,
            "error": error,
            "model": model,
            "generated_at": generated_at or datetime.now(UTC).isoformat(timespec="seconds"),
            "vault_note_hash": vault_hash,
            "source_csv_hash": source_hash,
        }
        payload = self.load()
        self._write(payload, client_id, record)
        return record

    def _write(self, payload: dict[str, Any], client_id: str, record: dict[str, Any]) -> None:
        with self._write_lock:
            payload["reports"][client_id] = record
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.path)

    def save(self, **kwargs: Any) -> dict[str, Any]:
        return self.save_report(**kwargs)

    def get(self, client_id: str) -> dict[str, Any] | None:
        return self.load().get("reports", {}).get(client_id)

    def list_reports(self) -> list[dict[str, Any]]:
        reports = self.load().get("reports", {})
        return [reports[client_id] for client_id in sorted(reports)]

    def needs_refresh(
        self,
        client_id: str,
        vault_text: str | None = None,
        source_hash: str | None = None,
        force: bool = False,
        *,
        vault_hash: str | None = None,
        source_csv_hash: str | None = None,
    ) -> bool:
        if force:
            return True
        record = self.get(client_id)
        if record is None:
            return True
        expected_vault_hash = vault_hash if vault_hash is not None else vault_note_hash(vault_text)
        expected_source_hash = source_csv_hash if source_csv_hash is not None else source_hash
        return (
            record.get("vault_note_hash") != expected_vault_hash
            or record.get("source_csv_hash") != expected_source_hash
        )

    refresh_needed = needs_refresh


class AlignmentBackgroundLoader:
    """Process non-presentation clients serially without blocking the UI."""

    def __init__(self, store: AlignmentStore):
        self.store = store
        self._lock = threading.Lock()
        self._thread: threading.Thread | None = None
        self._status = {"running": False, "completed": 0, "pending": 0, "errors": []}

    def start(
        self,
        data: dict[str, Any],
        notes: dict[str, str],
        client_ids: list[str],
        source_hash: str,
    ) -> bool:
        pending = [
            client_id
            for client_id in client_ids
            if self.store.needs_refresh(client_id, notes.get(client_id, ""), source_hash)
        ]
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            if not pending:
                self._status = {"running": False, "completed": 0, "pending": 0, "errors": []}
                return False
            self._status = {
                "running": True,
                "completed": 0,
                "pending": len(pending),
                "errors": [],
            }
            self._thread = threading.Thread(
                target=self._run,
                args=(data, notes, pending, source_hash),
                daemon=True,
                name="alignment-background-loader",
            )
            self._thread.start()
            return True

    def _run(
        self,
        data: dict[str, Any],
        notes: dict[str, str],
        client_ids: list[str],
        source_hash: str,
    ) -> None:
        model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
        for client_id in client_ids:
            try:
                report, model = analyze_alignment(data, client_id, notes.get(client_id, ""))
                self.store.save_report(
                    client_id=client_id,
                    report=report,
                    model=model,
                    vault_hash=vault_note_hash(notes.get(client_id, "")),
                    source_hash=source_hash,
                )
            except Exception as exc:  # persist feature-level failures, then continue the batch
                message = f"{client_id}: {exc}"
                self.store.save_error(
                    client_id=client_id,
                    error=message,
                    model=model,
                    vault_hash=vault_note_hash(notes.get(client_id, "")),
                    source_hash=source_hash,
                )
                with self._lock:
                    self._status["errors"].append(message)
            with self._lock:
                self._status["completed"] += 1
                self._status["pending"] -= 1
        with self._lock:
            self._status["running"] = False

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._status)


def conflict_inbox(reports: Any) -> pd.DataFrame:
    """Flatten and rank report conflicts for the RM attention surface."""
    if isinstance(reports, dict):
        reports = list(reports.values())
    rows: list[dict[str, Any]] = []
    for item in reports or []:
        if isinstance(item, AlignmentReport):
            report = item
        elif isinstance(item, dict) and "report" in item:
            report = item["report"]
        else:
            report = item
        report_dict = report.model_dump(mode="json") if isinstance(report, AlignmentReport) else report
        if not isinstance(report_dict, dict):
            continue
        for conflict in report_dict.get("conflicts", []):
            severity = str(conflict.get("severity", "Low"))
            rows.append(
                {
                    "client_id": report_dict.get("client_id"),
                    "as_of": report_dict.get("as_of", AS_OF),
                    "conflict_id": conflict.get("conflict_id"),
                    "category": conflict.get("category"),
                    "severity": severity,
                    "severity_rank": SEVERITY_RANK.get(severity, 0),
                    "headline": conflict.get("headline", ""),
                    "detail": conflict.get("detail", ""),
                    "evidence_ids": conflict.get("evidence_ids", []),
                    "discussion_topic": conflict.get("discussion_topic", ""),
                    "review_lead": "Review lead — not proof of causation or advice.",
                }
            )
    columns = [
        "client_id",
        "as_of",
        "conflict_id",
        "category",
        "severity",
        "severity_rank",
        "headline",
        "detail",
        "evidence_ids",
        "discussion_topic",
        "review_lead",
    ]
    if not rows:
        return pd.DataFrame(columns=columns)
    return (
        pd.DataFrame(rows, columns=columns)
        .sort_values(["severity_rank", "category", "client_id"], ascending=[False, True, True])
        .reset_index(drop=True)
    )
