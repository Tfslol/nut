"""Offline tests for the recommendation fact packet and guardrails (LLM stubbed)."""

import json

import pandas as pd
import pytest
from ralph.stub_alignment import stub_alignment_report

from singhacks26.recommendation import (
    RecommendationDraft,
    build_recommendation_fact_packet,
    validate_recommendation_draft,
    validate_recommendation_evidence,
)


def data_fixture() -> dict:
    clients = pd.DataFrame(
        [
            {
                "client_id": "CL-X",
                "risk_profile": "Balanced",
                "investment_horizon_years": 10,
                "liquidity_needs": "Medium",
                "life_stage": "Peak earning years",
                "source_of_wealth": "Business",
                "objectives": "Grow capital",
                "base_currency": "USD",
                "total_aum_usd": 1000,
            }
        ]
    )
    holdings = pd.DataFrame(
        [
            {
                "client_id": "CL-X",
                "snapshot_date": "2026-08-26",
                "market_value_usd": 600.0,
                "asset_class": "Equity",
                "sector": "Energy",
                "region": "Global",
            },
            {
                "client_id": "CL-X",
                "snapshot_date": "2026-08-26",
                "market_value_usd": 400.0,
                "asset_class": "Fixed Income",
                "sector": "Corporate",
                "region": "Global",
            },
        ]
    )
    return {"clients": clients, "holdings": holdings}


def news_items() -> list[dict]:
    return [
        {
            "uuid": "n1",
            "title": "Energy markets reopen",
            "url": "",
            "source": "s",
            "published_at": "2026-08-26T00:00:00+00:00",
            "snippet": "x",
            "entities": [],
        }
    ]


def valid_draft(**overrides) -> RecommendationDraft:
    values = {
        "client_id": "CL-X",
        "summary": "Review the energy exposure against the mandate.",
        "alignment_and_conflicts_to_discuss": ["Mandate exclusions need confirmation."],
        "news_drivers": ["Energy markets reopen."],
        "rm_recommendation_topics": ["Confirm mandate exclusions."],
        "questions_to_ask": ["Has the objective changed?"],
        "risks_and_uncertainties": ["Specialist confirmation required."],
        "evidence_ids": ["note:CL-X"],
    }
    values.update(overrides)
    return RecommendationDraft(**values)


def test_fact_packet_is_censored_deterministic_and_allow_listed():
    data = data_fixture()
    report = stub_alignment_report("CL-X")
    packet = build_recommendation_fact_packet(data, "CL-X", "Censored note.", report, news_items())

    assert packet["synthetic_data"] is True
    assert packet["client_id"] == "CL-X"
    assert packet["censored_static_note"] == "Censored note."
    assert packet["allocation_by_asset_class_usd"] == {"Equity": 600.0, "Fixed Income": 400.0}
    assert packet["surfaced_conflicts"][0]["conflict_id"] == "CL-X-C-1"
    assert "note:CL-X" in packet["allowed_evidence_ids"]
    assert "clients.csv" in packet["allowed_evidence_ids"]
    assert "holdings.csv:2026-08-26" in packet["allowed_evidence_ids"]
    assert "news:n1" in packet["allowed_evidence_ids"]


def test_fact_packet_excludes_client_name():
    data = data_fixture()
    report = stub_alignment_report("CL-X")
    packet = build_recommendation_fact_packet(data, "CL-X", "Censored note.", report, news_items())
    assert "Margarethe" not in json.dumps(packet, ensure_ascii=False)


def test_guardrail_allows_existing_numbers():
    data = data_fixture()
    report = stub_alignment_report("CL-X")
    packet = build_recommendation_fact_packet(data, "CL-X", "Censored note.", report, news_items())
    validate_recommendation_draft(valid_draft(), packet)


def test_guardrail_blocks_new_number():
    data = data_fixture()
    report = stub_alignment_report("CL-X")
    packet = build_recommendation_fact_packet(data, "CL-X", "Censored note.", report, news_items())
    with pytest.raises(RuntimeError, match="unsupported numeric claims"):
        validate_recommendation_draft(valid_draft(summary="Introduce a USD 999m reserve."), packet)


def test_guardrail_blocks_direct_advice():
    data = data_fixture()
    report = stub_alignment_report("CL-X")
    packet = build_recommendation_fact_packet(data, "CL-X", "Censored note.", report, news_items())
    with pytest.raises(RuntimeError, match="prohibited-language"):
        validate_recommendation_draft(valid_draft(summary="You should sell the position."), packet)


def test_evidence_allowlist_blocks_unknown_id():
    draft = valid_draft(evidence_ids=["note:CL-X", "invented:source"])
    with pytest.raises(RuntimeError, match="unsupported evidence IDs"):
        validate_recommendation_evidence(draft, ["note:CL-X"])
