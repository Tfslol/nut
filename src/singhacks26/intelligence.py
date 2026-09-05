"""Prototype compatibility adapter for upstream analytical inputs.

It reconstructs Block 1/2 evidence when their team payload is unavailable. Aurelia consumes
these outputs but does not claim portfolio explanation, risk detection or stress testing as
RM Intelligence Workbench capabilities.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any

import pandas as pd

AS_OF = "2026-08-26"
BASELINE = "2025-12-31"


@dataclass(frozen=True)
class Evidence:
    source_file: str
    row_or_id: str
    field: str
    value: Any
    snapshot_date: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AttentionResult:
    client_id: str
    attention_index: float
    attention_band: str
    severity: float
    materiality: float
    urgency: float
    reasons: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["evidence"] = [item.to_dict() for item in self.evidence]
        return payload


def usd_per_unit(market: pd.DataFrame, currency: str, snapshot: str = AS_OF) -> float:
    """Convert one currency unit to USD using explicit market quote direction."""
    if currency == "USD":
        return 1.0
    rows = market.loc[market.snapshot_date == snapshot]
    direct = rows.loc[rows.series_id == f"{currency}USD", "value"]
    if not direct.empty:
        return float(direct.iloc[0])
    inverse = rows.loc[rows.series_id == f"USD{currency}", "value"]
    if not inverse.empty and float(inverse.iloc[0]):
        return 1 / float(inverse.iloc[0])
    raise ValueError(f"No controlled FX rate for {currency} at {snapshot}")


def portfolio_mandate_review(data: dict[str, Any], client_id: str) -> pd.DataFrame:
    """Evaluate mandate bands per governed portfolio; custody remains out of scope."""
    holdings = data["holdings"]
    latest = holdings.loc[(holdings.client_id == client_id) & (holdings.snapshot_date == AS_OF)]
    rows: list[dict[str, Any]] = []
    for _, portfolio in (
        data["portfolios"].loc[data["portfolios"].client_id == client_id].iterrows()
    ):
        if portfolio.service_model == "Custody":
            rows.append(
                {
                    "portfolio_id": portfolio.portfolio_id,
                    "asset_class": "All",
                    "actual_pct": None,
                    "min_pct": None,
                    "max_pct": None,
                    "status": "Not governed — custody",
                }
            )
            continue
        positions = latest.loc[latest.portfolio_id == portfolio.portfolio_id]
        total = positions.market_value_base.sum()
        allocation = positions.groupby("asset_class").market_value_base.sum()
        rules = data["mandates"].loc[data["mandates"].mandate_code == portfolio.mandate_code]
        for _, rule in rules.iterrows():
            actual = float(allocation.get(rule.asset_class, 0) / total * 100) if total else 0
            rows.append(
                {
                    "portfolio_id": portfolio.portfolio_id,
                    "asset_class": rule.asset_class,
                    "actual_pct": round(actual, 2),
                    "min_pct": float(rule.min_pct),
                    "max_pct": float(rule.max_pct),
                    "status": "pass"
                    if float(rule.min_pct) <= actual <= float(rule.max_pct)
                    else "review",
                }
            )
    return pd.DataFrame(rows)


def attribute_change(
    data: dict[str, Any],
    client_id: str,
    start: str = BASELINE,
    end: str = AS_OF,
) -> dict[str, Any]:
    """Exactly bridge USD value into price, FX and position-flow effects.

    New positions use closing-snapshot USD cost basis as deployed capital. Closed
    positions are treated as flows at their opening snapshot value. Any source
    rounding residual is assigned to price so the bridge reconciles exactly.
    """
    holdings = data["holdings"]
    rows = holdings.loc[
        (holdings.client_id == client_id) & holdings.snapshot_date.isin([start, end])
    ].copy()
    contributions: list[dict[str, Any]] = []
    keys = rows[["portfolio_id", "instrument_id"]].drop_duplicates().itertuples(index=False)
    for portfolio_id, instrument_id in keys:
        position = rows.loc[
            (rows.portfolio_id == portfolio_id) & (rows.instrument_id == instrument_id)
        ]
        before_rows = position.loc[position.snapshot_date == start]
        after_rows = position.loc[position.snapshot_date == end]
        before = None if before_rows.empty else before_rows.iloc[0]
        after = None if after_rows.empty else after_rows.iloc[0]
        start_value = 0.0 if before is None else float(before.market_value_usd)
        end_value = 0.0 if after is None else float(after.market_value_usd)
        if after is None:
            price_effect = fx_effect = 0.0
            flow_effect = -start_value
        elif before is None:
            base_to_usd = (
                float(after.market_value_usd) / float(after.market_value_base)
                if float(after.market_value_base)
                else 1.0
            )
            deployed = float(after.cost_basis_base) * base_to_usd
            flow_effect = deployed or end_value
            price_effect = end_value - flow_effect
            fx_effect = 0.0
        else:
            q0, q1 = float(before.quantity), float(after.quantity)
            p0, p1 = float(before.price_local), float(after.price_local)
            f0 = start_value / (q0 * p0) if q0 and p0 else 1.0
            f1 = end_value / (q1 * p1) if q1 and p1 else f0
            price_effect = q0 * (p1 - p0) * f0
            fx_effect = q0 * p1 * (f1 - f0)
            flow_effect = (q1 - q0) * p1 * f1
            residual = end_value - start_value - price_effect - fx_effect - flow_effect
            price_effect += residual
        contributions.append(
            {
                "portfolio_id": portfolio_id,
                "instrument_id": instrument_id,
                "instrument_name": (after if after is not None else before).instrument_name,
                "start_value_usd": start_value,
                "end_value_usd": end_value,
                "price_effect_usd": price_effect,
                "fx_effect_usd": fx_effect,
                "flow_effect_usd": flow_effect,
                "total_change_usd": end_value - start_value,
            }
        )
    frame = pd.DataFrame(contributions)
    start_value = float(frame.start_value_usd.sum())
    end_value = float(frame.end_value_usd.sum())
    price = float(frame.price_effect_usd.sum())
    fx = float(frame.fx_effect_usd.sum())
    flow = float(frame.flow_effect_usd.sum())
    return {
        "client_id": client_id,
        "start": start,
        "end": end,
        "start_value_usd": start_value,
        "end_value_usd": end_value,
        "change_usd": end_value - start_value,
        "price_effect_usd": price,
        "fx_effect_usd": fx,
        "flow_effect_usd": flow,
        "reconciliation_difference_usd": end_value - start_value - price - fx - flow,
        "contributions": frame.sort_values("total_change_usd").to_dict(orient="records"),
        "evidence": [
            Evidence(
                "holdings.csv",
                client_id,
                "market_value_usd, quantity, price_local",
                f"{start_value:.2f} -> {end_value:.2f}",
                end,
                "Price/FX/flow bridge across all client portfolios.",
            ).to_dict()
        ],
    }


def collateral_scenario(
    facility: pd.Series, collateral_shock_pct: float, target_ltv_pct: float
) -> dict[str, float | bool]:
    """Apply a static lending-value shock and solve repayment to target LTV."""
    lending = float(facility["lending_value_2026-08-26"])
    drawn = float(facility["drawn_2026-08-26"])
    stressed_lending = lending * (1 + collateral_shock_pct / 100)
    stressed_ltv = drawn / stressed_lending * 100 if stressed_lending else float("inf")
    repayment = max(drawn - stressed_lending * target_ltv_pct / 100, 0)
    return {
        "baseline_ltv_pct": drawn / lending * 100,
        "stressed_lending_value": stressed_lending,
        "stressed_ltv_pct": stressed_ltv,
        "margin_call": stressed_ltv >= float(facility.margin_call_ltv_pct),
        "repayment_to_target": repayment,
        "target_ltv_pct": target_ltv_pct,
    }


def attention_queue(data: dict[str, Any]) -> pd.DataFrame:
    """Order clients with a risk-led index and bounded context uplifts."""
    results: list[AttentionResult] = []
    as_of_date = date.fromisoformat(AS_OF)
    for _, client in data["clients"].iterrows():
        client_id = client.client_id
        severity = 20.0
        materiality = 0.0
        urgency = 20.0
        reasons: list[str] = []
        evidence: list[Evidence] = []

        facilities = data["credit_facilities"].loc[data["credit_facilities"].client_id == client_id]
        for _, facility in facilities.iterrows():
            ltv = float(facility["ltv_pct_2026-08-26"])
            trigger = float(facility.margin_call_ltv_pct)
            gap = trigger - ltv
            historical_ltvs = [
                float(facility[column])
                for column in facility.index
                if str(column).startswith("ltv_pct_") and pd.notna(facility[column])
            ]
            if ltv >= trigger:
                severity = max(severity, 100)
                reasons.append(f"Facility at {ltv:.1f}% exceeds {trigger:.1f}% trigger")
            elif gap <= 1:
                severity = max(severity, 100)
                reasons.append(f"Only {gap:.2f} LTV points to margin-call trigger")
            elif gap <= 2:
                severity = max(severity, 95)
                reasons.append(f"Only {gap:.2f} LTV points to margin-call trigger")
            elif historical_ltvs and max(historical_ltvs) >= trigger:
                severity = max(severity, 82)
                reasons.append(
                    f"Facility previously breached {trigger:.1f}% and is currently below it"
                )
            materiality = max(
                materiality,
                min(
                    float(facility["drawn_2026-08-26"])
                    * usd_per_unit(data["market_context"], facility.facility_ccy)
                    * 100
                    / max(float(client.total_aum_usd), 1),
                    30,
                )
                / 30
                * 100,
            )
            evidence.append(
                Evidence(
                    "credit_facilities.csv",
                    facility.facility_id,
                    "ltv_pct_2026-08-26",
                    ltv,
                    AS_OF,
                )
            )

        mandate = portfolio_mandate_review(data, client_id)
        breaches = mandate.loc[mandate.status == "review"]
        if not breaches.empty:
            severity = max(severity, 78)
            materiality = max(materiality, min(len(breaches) * 18, 100))
            reasons.append(f"{len(breaches)} portfolio mandate band(s) need review")
            evidence.append(
                Evidence("mandates.csv", client_id, "allocation_bands", len(breaches), AS_OF)
            )

        latest_positions = data["holdings"].loc[
            (data["holdings"].client_id == client_id) & (data["holdings"].snapshot_date == AS_OF)
        ]
        stale = latest_positions.loc[latest_positions.valuation_date < AS_OF]
        if not stale.empty:
            stale_share = (
                float(stale.market_value_usd.sum())
                / max(float(latest_positions.market_value_usd.sum()), 1)
                * 100
            )
            severity = max(severity, 85)
            materiality = max(materiality, min(stale_share, 30) / 30 * 100)
            reasons.append(f"{stale_share:.1f}% of household value uses stale marks")
            evidence.append(
                Evidence(
                    "holdings.csv",
                    client_id,
                    "valuation_date",
                    sorted(stale.valuation_date.unique().tolist()),
                    AS_OF,
                )
            )

        governed = data["portfolios"].loc[
            (data["portfolios"].client_id == client_id)
            & (data["portfolios"].service_model == "Discretionary")
        ]
        excluded = latest_positions.merge(
            data["instruments"][["instrument_id", "sustainability_excluded"]],
            on="instrument_id",
            how="left",
        )
        excluded = excluded.loc[
            excluded.portfolio_id.isin(governed.portfolio_id)
            & (excluded.sustainability_excluded == "Y")
        ]
        if not excluded.empty and governed.mandate_code.str.contains("SUST").any():
            excluded_share = (
                float(excluded.market_value_usd.sum())
                / max(float(latest_positions.market_value_usd.sum()), 1)
                * 100
            )
            severity = max(severity, 88)
            materiality = max(materiality, min(excluded_share, 30) / 30 * 100)
            reasons.append(
                f"{excluded_share:.1f}% is flagged excluded inside a sustainable "
                "discretionary mandate"
            )
            evidence.append(
                Evidence(
                    "instruments.csv",
                    client_id,
                    "sustainability_excluded",
                    excluded.instrument_id.tolist(),
                    AS_OF,
                )
            )

        commitments = data["commitments"].loc[data["commitments"].client_id == client_id]
        if not commitments.empty:
            uncalled_usd = 0.0
            sleeve_cash_usd = 0.0
            for _, commitment in commitments.iterrows():
                uncalled_usd += float(commitment.uncalled) * usd_per_unit(
                    data["market_context"], commitment.currency
                )
                sleeve_cash_usd += float(
                    latest_positions.loc[
                        (latest_positions.portfolio_id == commitment.portfolio_id)
                        & (latest_positions.asset_class == "Cash and Equivalents"),
                        "market_value_usd",
                    ].sum()
                )
            if uncalled_usd > sleeve_cash_usd:
                gap = uncalled_usd - sleeve_cash_usd
                severity = max(severity, 80)
                materiality = max(
                    materiality,
                    min(gap / max(float(client.total_aum_usd), 1) * 100, 30) / 30 * 100,
                )
                reasons.append(f"Uncalled commitments exceed same-sleeve cash by USD {gap:,.0f}")
                evidence.append(
                    Evidence(
                        "commitments.csv",
                        client_id,
                        "uncalled",
                        uncalled_usd,
                        AS_OF,
                        "Compared with cash in the committed portfolios; duplicate "
                        "planned needs are not added.",
                    )
                )

        needs = data["planned_cash_needs"].loc[data["planned_cash_needs"].client_id == client_id]
        for _, need in needs.iterrows():
            due_from = date.fromisoformat(str(need.due_from))
            due_to = date.fromisoformat(str(need.due_to))
            active_recurring = due_from <= as_of_date <= due_to and str(
                need.recurrence
            ).lower().startswith("annual")
            days = 0 if active_recurring else (due_from - as_of_date).days
            need_urgency = 100 if days <= 30 else 80 if days <= 90 else 55 if days <= 365 else 30
            urgency = max(urgency, need_urgency)
            if str(need.certainty).lower() == "confirmed":
                severity = max(severity, 75 if days <= 365 else 45)
                amount_usd = float(need.amount) * usd_per_unit(
                    data["market_context"], need.currency
                )
                materiality = max(
                    materiality,
                    min(amount_usd / max(float(client.total_aum_usd), 1) * 100, 30) / 30 * 100,
                )
                reasons.append(
                    f"Confirmed {need.currency} {float(need.amount):,.0f} need "
                    f"from {need.due_from} ({need.recurrence})"
                )
                evidence.append(
                    Evidence(
                        "planned_cash_needs.csv",
                        need.need_id,
                        "amount,due_from,due_to,recurrence,certainty",
                        f"{need.currency} {need.amount}; {need.due_from} to "
                        f"{need.due_to}; {need.recurrence}; {need.certainty}",
                    )
                )

        time_uplift = 6 if urgency >= 100 else 4 if urgency >= 80 else 2 if urgency >= 55 else 0
        exposure_uplift = min(materiality / 10, 10)
        convergence_uplift = min(max(len(reasons) - 1, 0) * 2, 4)
        score = min(100, 0.8 * severity + time_uplift + exposure_uplift + convergence_uplift)
        band = "Call first" if score >= 75 else "Prepare soon" if score >= 55 else "Keep in view"
        results.append(
            AttentionResult(
                client_id=client_id,
                attention_index=round(score, 1),
                attention_band=band,
                severity=round(severity, 1),
                materiality=round(materiality, 1),
                urgency=round(urgency, 1),
                reasons=reasons or ["No hard override; routine review"],
                evidence=evidence,
            )
        )
    return pd.DataFrame([result.to_dict() for result in results]).sort_values(
        ["attention_index", "urgency", "materiality"], ascending=False
    )


def integrity_report(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Return visible source-quality checks instead of silently fixing records."""
    issues: list[dict[str, Any]] = []
    latest = data["holdings"].loc[data["holdings"].snapshot_date == AS_OF]
    stale = latest.loc[latest.valuation_date < AS_OF]
    if not stale.empty:
        issues.append(
            {
                "check": "stale_valuations",
                "status": "review",
                "records": int(len(stale)),
                "affected_clients": sorted(stale.client_id.unique().tolist()),
                "evidence": "holdings.csv · valuation_date",
            }
        )
    for _, portfolio in data["portfolios"].iterrows():
        rows = data["holdings"].loc[data["holdings"].portfolio_id == portfolio.portfolio_id]
        for snapshot in rows.snapshot_date.unique():
            actual = float(rows.loc[rows.snapshot_date == snapshot, "market_value_base"].sum())
            expected = float(portfolio[f"aum_{snapshot}"])
            if abs(actual - expected) > 0.02:
                issues.append(
                    {
                        "check": "portfolio_aum_reconciliation",
                        "status": "block",
                        "records": 1,
                        "affected_clients": [portfolio.client_id],
                        "detail": f"{portfolio.portfolio_id} differs by {actual - expected:,.2f}",
                        "evidence": f"holdings.csv; portfolios.csv · {snapshot}",
                    }
                )
    for _, facility in data["credit_facilities"].iterrows():
        balance_change = float(facility["drawn_2026-03-31"]) - float(facility["drawn_2026-02-27"])
        transactions = (
            data["transactions"]
            .loc[
                (data["transactions"].client_id == facility.client_id)
                & (data["transactions"].transaction_type == "Facility Drawdown")
                & (data["transactions"].trade_date > "2026-02-27")
                & (data["transactions"].trade_date <= "2026-03-31"),
                "amount",
            ]
            .sum()
        )
        difference = balance_change - float(transactions)
        if abs(difference) > 1:
            issues.append(
                {
                    "check": "facility_drawdown_reconciliation",
                    "status": "block",
                    "records": 1,
                    "affected_clients": [facility.client_id],
                    "detail": (
                        f"Facility change less ledger drawdowns: {difference:,.0f} "
                        f"{facility.facility_ccy}"
                    ),
                    "evidence": f"credit_facilities.csv · {facility.facility_id}; transactions.csv",
                }
            )
    for client_id, commitments in data["commitments"].groupby("client_id"):
        for currency, currency_commitments in commitments.groupby("currency"):
            uncalled = float(currency_commitments.uncalled.sum())
            duplicates = data["planned_cash_needs"].loc[
                (data["planned_cash_needs"].client_id == client_id)
                & (data["planned_cash_needs"].currency == currency)
                & (data["planned_cash_needs"].amount.sub(uncalled).abs() < 0.01)
                & data["planned_cash_needs"].description.str.contains(
                    "commitment", case=False, na=False
                )
            ]
            if not duplicates.empty:
                issues.append(
                    {
                        "check": "duplicate_obligation_representation",
                        "status": "review",
                        "records": int(len(duplicates)),
                        "affected_clients": [client_id],
                        "detail": (
                            f"{currency} {uncalled:,.0f} appears in commitments and "
                            "planned needs; count once."
                        ),
                        "evidence": "commitments.csv; planned_cash_needs.csv",
                    }
                )
    unverifiable = data["instruments"].loc[
        data["instruments"]
        .underlying_reference.fillna("")
        .str.contains("three Asian banking majors", case=False)
    ]
    if not unverifiable.empty:
        issues.append(
            {
                "check": "unnamed_structured_product_underlyings",
                "status": "review",
                "records": int(len(unverifiable)),
                "affected_clients": sorted(
                    latest.loc[
                        latest.instrument_id.isin(unverifiable.instrument_id), "client_id"
                    ].unique()
                ),
                "detail": "Underlying issuers are not named and must not be guessed.",
                "evidence": "instruments.csv · underlying_reference",
            }
        )
    return issues
