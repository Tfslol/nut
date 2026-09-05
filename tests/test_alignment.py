import json
from pathlib import Path

import pandas as pd
import pytest

from singhacks26.alignment import (
    AlignmentDimensions,
    AlignmentReport,
    AlignmentStore,
    Conflict,
    build_alignment_fact_packet,
    conflict_inbox,
    source_data_hash,
    validate_alignment_report,
    vault_note_hash,
)

ROOT = Path(__file__).parents[1]
DATA = ROOT / "data"


@pytest.fixture(scope="module")
def data():
    names = [
        "clients",
        "portfolios",
        "holdings",
        "instruments",
        "mandates",
        "transactions",
        "credit_facilities",
        "commitments",
        "planned_cash_needs",
        "market_context",
        "event_log",
    ]
    result = {name: pd.read_csv(DATA / f"{name}.csv") for name in names}
    result["rm_notes"] = json.loads((DATA / "rm_notes.json").read_text(encoding="utf-8"))
    return result


def censored_note(client_id: str) -> str:
    return (ROOT / "obsidian_vault" / "Clients" / f"{client_id}.md").read_text(encoding="utf-8")


def test_fact_packet_has_deterministic_sections_and_cites_sources(data):
    packet = build_alignment_fact_packet(data, "CL-0003", censored_note("CL-0003"))

    assert packet["synthetic_data"] is True
    assert packet["as_of"] == "2026-08-26"
    assert packet["household"]["allocation_by_asset_class"]
    assert packet["mandate"]["portfolio_reviews"]
    assert packet["mandate"]["single_position_flags"]
    assert packet["planned_cash_needs"][0]["need_id"] == "CN-004"
    assert packet["matched_controlled_events"]
    assert "event_log.csv:2026-06-05" in packet["allowed_evidence_ids"]
    assert "note:RM notes" in packet["allowed_evidence_ids"]
    assert "note:Transaction activity (censored)" in packet["allowed_evidence_ids"]


def test_fact_packet_does_not_leak_uncensored_identity(data):
    packet = build_alignment_fact_packet(data, "CL-0001", censored_note("CL-0001"))
    encoded = json.dumps(packet, ensure_ascii=False)
    client = data["clients"].loc[data["clients"].client_id == "CL-0001"].iloc[0]

    assert client.client_name not in encoded
    assert '"age"' not in encoded
    assert f"{int(client.age)}" not in packet["censored_static_note"].split("\n", 5)[0]


def test_event_conflict_must_use_matched_controlled_event(data):
    packet = build_alignment_fact_packet(data, "CL-0003", censored_note("CL-0003"))
    report = AlignmentReport(
        client_id="CL-0003",
        as_of="2026-08-26",
        overall_band="misaligned",
        dimensions=AlignmentDimensions(
            risk_profile_alignment="misaligned",
            mandate_alignment="misaligned",
            objectives_life_event_alignment="review",
            event_consistency="conflict",
        ),
        conflicts=[
            Conflict(
                conflict_id="CL-0003-C-1",
                category="event",
                severity="High",
                headline="Controlled event review",
                detail="Discuss the dated event evidence.",
                evidence_ids=["event_log.csv:2026-06-05"],
                discussion_topic="Ask what the client understood about the exposure.",
            )
        ],
    )
    validate_alignment_report(report, packet)
    report.conflicts[0].evidence_ids = ["event_log.csv:2099-01-01"]
    with pytest.raises(RuntimeError, match="matched event_log.csv"):
        validate_alignment_report(report, packet)


def test_event_conflict_may_also_cite_affected_holdings(data):
    """Event conflicts need >=1 matched event row; holdings/note may also be cited."""
    packet = build_alignment_fact_packet(data, "CL-0003", censored_note("CL-0003"))
    report = AlignmentReport(
        client_id="CL-0003",
        as_of="2026-08-26",
        overall_band="review",
        dimensions=AlignmentDimensions(
            risk_profile_alignment="review",
            mandate_alignment="review",
            objectives_life_event_alignment="review",
            event_consistency="conflict",
        ),
        conflicts=[
            Conflict(
                conflict_id="CL-0003-C-2",
                category="event",
                severity="High",
                headline="Controlled event review",
                detail="Discuss the dated event evidence against the exposure.",
                evidence_ids=["event_log.csv:2026-06-05", "holdings.csv:2026-08-26"],
                discussion_topic="Ask what the client understood about the exposure.",
            )
        ],
    )
    validate_alignment_report(report, packet)


def test_numeric_guardrail_accepts_percent_formatting_but_rejects_new_value(data):
    packet = build_alignment_fact_packet(data, "CL-0002", censored_note("CL-0002"))
    ltv = packet["credit_facilities"][0]["ltv_pct"]
    report = AlignmentReport(
        client_id="CL-0002",
        as_of="2026-08-26",
        overall_band="review",
        dimensions=AlignmentDimensions(
            risk_profile_alignment="review",
            mandate_alignment="aligned",
            objectives_life_event_alignment="review",
            event_consistency="aligned",
        ),
        conflicts=[
            Conflict(
                conflict_id="CL-0002-C-1",
                category="risk_profile",
                severity="High",
                headline="Collateral review",
                detail=f"The recorded collateral reading is {ltv:.2f}%.",
                evidence_ids=["credit_facilities.csv:CF-0001"],
                discussion_topic="Confirm the bridge plan.",
            )
        ],
    )
    validate_alignment_report(report, packet)
    report.conflicts[0].detail = f"The recorded collateral reading is {ltv + 0.01:.2f}%."
    with pytest.raises(RuntimeError, match="unsupported numeric claims"):
        validate_alignment_report(report, packet)


def test_numeric_guardrail_accepts_one_decimal_display_rounding(data):
    packet = build_alignment_fact_packet(data, "CL-0013", censored_note("CL-0013"))
    illiquid_share = next(
        item["household_weight_pct"]
        for item in packet["household"]["liquidity_tiers"]
        if item["liquidity_tier"] == "Illiquid"
    )
    report = AlignmentReport(
        client_id="CL-0013",
        as_of="2026-08-26",
        overall_band="review",
        dimensions=AlignmentDimensions(
            risk_profile_alignment="review",
            mandate_alignment="review",
            objectives_life_event_alignment="review",
            event_consistency="aligned",
        ),
        conflicts=[
            Conflict(
                conflict_id="CL-0013-C-1",
                category="mandate",
                severity="Medium",
                headline="Liquidity review",
                detail=f"Illiquid holdings represent {illiquid_share:.1f}% of the household.",
                evidence_ids=["holdings.csv:2026-08-26"],
                discussion_topic="Confirm the liquidity plan.",
            )
        ],
    )
    validate_alignment_report(report, packet)


def test_alignment_store_refreshes_on_note_or_source_change(tmp_path):
    store = AlignmentStore(tmp_path / "alignment_state.json")
    report = AlignmentReport(
        client_id="CL-0003",
        as_of="2026-08-26",
        overall_band="review",
        dimensions=AlignmentDimensions(
            risk_profile_alignment="review",
            mandate_alignment="review",
            objectives_life_event_alignment="review",
            event_consistency="aligned",
        ),
    )
    store.save_report(
        client_id="CL-0003",
        report=report,
        model="test-model",
        vault_hash=vault_note_hash("note-a"),
        source_hash="source-a",
    )
    assert not store.needs_refresh("CL-0003", "note-a", "source-a")
    assert store.needs_refresh("CL-0003", "note-b", "source-a")
    assert store.needs_refresh("CL-0003", "note-a", "source-b")
    assert store.needs_refresh("CL-0004", "note-a", "source-a")
    assert store.needs_refresh("CL-0003", "note-a", "source-a", force=True)
    assert store.list_reports()[0]["report"]["client_id"] == "CL-0003"
    error = store.save_error(
        client_id="CL-0004",
        error="CL-0004: validation failed",
        model="test-model",
        vault_hash=vault_note_hash("note-a"),
        source_hash="source-a",
    )
    assert error["status"] == "error"
    assert not store.needs_refresh("CL-0004", "note-a", "source-a")


def test_conflict_inbox_ranks_severity_and_preserves_evidence():
    reports = [
        {
            "client_id": "CL-0002",
            "as_of": "2026-08-26",
            "conflicts": [
                {
                    "conflict_id": "CL-0002-C-1",
                    "category": "objectives",
                    "severity": "Medium",
                    "headline": "Liquidity review",
                    "detail": "Review the bridge.",
                    "evidence_ids": ["planned_cash_needs.csv:CN-002"],
                    "discussion_topic": "Confirm timing.",
                }
            ],
        },
        {
            "client_id": "CL-0003",
            "as_of": "2026-08-26",
            "conflicts": [
                {
                    "conflict_id": "CL-0003-C-1",
                    "category": "mandate",
                    "severity": "Urgent",
                    "headline": "Mandate review",
                    "detail": "Review the allocation.",
                    "evidence_ids": ["mandates.csv"],
                    "discussion_topic": "Explain the inherited risk.",
                }
            ],
        },
    ]
    inbox = conflict_inbox(reports)

    assert inbox.iloc[0].client_id == "CL-0003"
    assert inbox.iloc[0].evidence_ids == ["mandates.csv"]
    assert "not proof of causation" in inbox.iloc[0].review_lead


def test_source_hash_changes_when_source_table_changes(data):
    first = source_data_hash(data)
    changed = dict(data)
    changed["clients"] = data["clients"].copy()
    changed["clients"].loc[0, "objectives"] = "Changed only for the test"
    assert source_data_hash(changed) != first


def test_fact_packet_builds_for_every_client(data):
    for client_id in data["clients"].client_id:
        packet = build_alignment_fact_packet(data, client_id, censored_note(client_id))
        assert packet["client_id"] == client_id
        assert packet["household"]["total_market_value_usd"] > 0
