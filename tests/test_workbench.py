import json

import pandas as pd

from singhacks26.workbench import (
    WorkbenchStore,
    liquidity_profile,
    snapshot_history,
    theme_exposure,
)


def test_snapshot_and_liquidity_roll_up_household():
    holdings = pd.DataFrame(
        [
            {
                "client_id": "C1",
                "snapshot_date": "2026-01-01",
                "market_value_usd": 100,
                "liquidity_tier": "Daily",
            },
            {
                "client_id": "C1",
                "snapshot_date": "2026-02-01",
                "market_value_usd": 80,
                "liquidity_tier": "Daily",
            },
            {
                "client_id": "C1",
                "snapshot_date": "2026-02-01",
                "market_value_usd": 20,
                "liquidity_tier": "Illiquid",
            },
        ]
    )

    history = snapshot_history(holdings, "C1")
    liquidity = liquidity_profile(holdings, "C1", "2026-02-01")

    assert history.household_value_usd.tolist() == [100, 100]
    assert liquidity.set_index("liquidity_tier").weight_pct.to_dict() == {
        "Daily": 80.0,
        "Illiquid": 20.0,
    }


def test_workbench_store_appends_task_and_audit(tmp_path):
    path = tmp_path / "workflow.json"
    store = WorkbenchStore(path)

    task = store.add_task(
        client_id="CL-0003",
        title="Confirm tax advice",
        owner="Tax specialist",
        due_date="2026-09-10",
        task_type="Specialist referral",
        evidence_ref="cash need CN-004",
    )

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["tasks"][0]["task_id"] == task["task_id"]
    assert payload["audit"][0]["action"] == "task_created"
    updated = store.update_task(
        task_id=task["task_id"],
        status="complete",
        rationale="Specialist response received.",
    )
    assert updated["status"] == "complete"
    assert store.read()["audit"][-1]["detail"]["prior_state"] == "open"


def test_decisions_comparisons_and_call_plans_retain_versions(tmp_path):
    store = WorkbenchStore(tmp_path / "workflow.json")
    first = store.record_decision(
        client_id="CL-0014",
        decision="Needs review",
        rationale="Confirm the facility balance.",
        evidence_version="2026-08-26",
        original_next_step="Review collateral.",
        gates={"evidence": True, "data_model": False},
    )
    second = store.record_decision(
        client_id="CL-0014",
        decision="Proceed to client discussion",
        rationale="Operations confirmed the balance.",
        evidence_version="2026-08-26",
        gates={"evidence": True, "data_model": True},
    )
    comparison = store.save_comparison(
        client_id="CL-0014",
        name="One-percent shock",
        inputs={"shock_pct": -1},
        outputs={"ltv_pct": 70.11},
        assumptions=["Debt unchanged"],
        evidence_version="2026-08-26",
    )
    call_plan_v1 = store.save_call_plan_version(
        client_id="CL-0014",
        content="Internal brief",
        evidence_version="2026-08-26",
        reason="Initial review",
    )
    call_plan_v2 = store.save_call_plan_version(
        client_id="CL-0014",
        content="Revised internal brief",
        evidence_version="2026-08-26",
        reason="Added credit caveat",
    )

    assert first["prior_state"] == "new"
    assert second["prior_state"] == "Needs review"
    assert comparison["calculation_version"] == "decision-lens/1.0"
    assert call_plan_v1["version"] == 1
    assert call_plan_v2["version"] == 2


def test_lau_hong_kong_property_theme_is_household_level():
    holdings = pd.read_csv("data/holdings.csv")
    themes = theme_exposure(holdings, "CL-0014", "2026-08-26")
    property_row = themes.loc[themes.theme == "Hong Kong property"].iloc[0]
    assert property_row.household_weight_pct == 49.03
    assert property_row.instruments == 4


def test_client_words_remain_separate_from_rm_interpretation(tmp_path):
    store = WorkbenchStore(tmp_path / "workflow.json")
    outcome = store.record_conversation_outcome(
        client_id="CL-0012",
        disposition="Understanding changed",
        client_statement="I need certainty for my medical expenses.",
        rm_interpretation="Security may matter more than avoiding every realised loss.",
        requested_documents=["Updated medical-cost estimate"],
    )

    assert outcome["client_statement"].startswith("I need certainty")
    assert outcome["rm_interpretation"].startswith("Security may matter")
    assert store.read()["audit"][-1]["action"] == "conversation_outcome_recorded"
