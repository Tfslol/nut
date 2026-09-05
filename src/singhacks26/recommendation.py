"""Guardrailed, RM-initiated recommendation drafting.

The LLM receives only censored, pre-selected facts: the censored static note,
the client's ``AlignmentReport`` (Role 0 contract), surfaced conflicts, the
latest cached news, and deterministic numbers computed locally. It returns a
structured ``RecommendationDraft`` for RM review — topics, questions and risks,
never orders or advice. Guardrails mirror ``ai_brief.py``: no invented numbers,
no direct-advice phrasing, evidence ID allow-list.
"""

from __future__ import annotations

import json
import os

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


class RecommendationDraft(BaseModel):
    """Strict output contract for a recommendation draft (PRD §5.3)."""

    client_id: str
    summary: str
    alignment_and_conflicts_to_discuss: list[str] = Field(min_length=1)
    news_drivers: list[str] = Field(default_factory=list)
    rm_recommendation_topics: list[str] = Field(min_length=1)
    questions_to_ask: list[str] = Field(min_length=1)
    risks_and_uncertainties: list[str] = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)
    guardrail_note: str = "Draft for RM review; not investment advice"


def _news_evidence_id(item: dict) -> str:
    if item.get("uuid"):
        return f"news:{item['uuid']}"
    return f"news:{item.get('title', 'untitled')}"


def build_recommendation_fact_packet(
    data: dict,
    client_id: str,
    vault_text: str,
    alignment_report: dict,
    news_items: list[dict],
) -> dict:
    """Assemble the only payload the recommendation LLM may see (censored)."""
    client = data["clients"].loc[data["clients"].client_id == client_id].iloc[0]
    holdings = data["holdings"]
    latest = holdings["snapshot_date"].max()
    positions = holdings[(holdings["client_id"] == client_id) & (holdings["snapshot_date"] == latest)]

    allocation = positions.groupby("asset_class")["market_value_usd"].sum().round(2).to_dict()
    sector_exposure = positions.groupby("sector")["market_value_usd"].sum().round(2).to_dict()
    region_exposure = positions.groupby("region")["market_value_usd"].sum().round(2).to_dict()

    conflicts = list(alignment_report.get("conflicts", []))
    news_items = news_items[:15]

    evidence_ids = [f"note:{client_id}", "clients.csv", f"holdings.csv:{latest}"]
    for conflict in conflicts:
        evidence_ids.extend(conflict.get("evidence_ids", []))
    evidence_ids.extend(_news_evidence_id(item) for item in news_items)

    return {
        "synthetic_data": True,
        "client_id": client_id,
        "as_of": str(latest),
        "risk_profile": client.risk_profile,
        "investment_horizon_years": int(client.investment_horizon_years),
        "liquidity_needs": client.liquidity_needs,
        "life_stage": client.life_stage,
        "source_of_wealth": client.source_of_wealth,
        "objectives": client.objectives,
        "base_currency": client.base_currency,
        "total_aum_usd": float(client.total_aum_usd),
        "censored_static_note": vault_text,
        "allocation_by_asset_class_usd": allocation,
        "sector_exposure_usd": sector_exposure,
        "region_exposure_usd": region_exposure,
        "alignment_report": alignment_report,
        "surfaced_conflicts": conflicts,
        "latest_news_items": news_items,
        "allowed_evidence_ids": list(dict.fromkeys(evidence_ids)),
    }


def validate_recommendation_draft(draft: RecommendationDraft, fact_packet: dict) -> None:
    """Block new numeric claims and prohibited advisory language."""
    source = json.dumps(fact_packet, ensure_ascii=False)
    candidate = draft.model_dump_json()
    allowed_numbers = {token.lower() for token in NUMBER_PATTERN.findall(source)}
    candidate_numbers = {token.lower() for token in NUMBER_PATTERN.findall(candidate)}
    unsupported_numbers = candidate_numbers - allowed_numbers
    if unsupported_numbers:
        raise RuntimeError(
            f"Recommendation draft introduced unsupported numeric claims: " f"{sorted(unsupported_numbers)}"
        )
    for pattern in PROHIBITED_PATTERNS:
        if pattern.search(candidate):
            raise RuntimeError(f"Recommendation draft failed the prohibited-language guardrail: {pattern.pattern}")


def validate_recommendation_evidence(draft: RecommendationDraft, allowed_evidence_ids: list[str]) -> None:
    """Reject evidence IDs outside the fact-packet allow-list."""
    unknown = set(draft.evidence_ids) - set(allowed_evidence_ids)
    if unknown:
        raise RuntimeError(f"AI returned unsupported evidence IDs: {sorted(unknown)}")


def generate_recommendation(fact_packet: dict) -> tuple[RecommendationDraft, str]:
    """Draft a recommendation from the fact packet (OpenAI, ``responses.parse``)."""
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
    reasoning_effort = os.getenv("OPENAI_REASONING_EFFORT", DEFAULT_REASONING_EFFORT)
    if reasoning_effort not in SUPPORTED_REASONING_EFFORTS:
        supported = ", ".join(sorted(SUPPORTED_REASONING_EFFORTS))
        raise RuntimeError(f"Unsupported OPENAI_REASONING_EFFORT={reasoning_effort!r}. Use one of: {supported}.")

    client = OpenAI(api_key=api_key)
    response = client.responses.parse(
        model=model,
        store=False,
        max_output_tokens=1200,
        text={"verbosity": "low"},
        reasoning={"effort": reasoning_effort, "context": "current_turn"},
        instructions=(
            "You prepare a private-bank relationship manager to review a client's situation. "
            "Use only the supplied synthetic, pre-selected facts (static note, alignment "
            "report, conflicts and cached news). Do not calculate, diagnose, predict markets, "
            "recommend a trade, promise an outcome, or add facts. Topics are for RM review, "
            "never orders. Distinguish client beliefs from verified observations. Explicitly "
            "name missing information and uncertainty. Cite only evidence IDs from "
            "allowed_evidence_ids."
        ),
        input=json.dumps(fact_packet, ensure_ascii=False),
        text_format=RecommendationDraft,
    )
    draft = response.output_parsed
    if draft is None:
        raise RuntimeError("The model did not return a structured recommendation.")
    validate_recommendation_evidence(draft, fact_packet["allowed_evidence_ids"])
    validate_recommendation_draft(draft, fact_packet)
    return draft, model
