import json
from pathlib import Path

import pandas as pd
import pytest

from singhacks26.intelligence import (
    AS_OF,
    attention_queue,
    attribute_change,
    collateral_scenario,
    portfolio_mandate_review,
    usd_per_unit,
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


def test_source_holdings_reconcile_to_every_portfolio_snapshot(data):
    for _, portfolio in data["portfolios"].iterrows():
        rows = data["holdings"].loc[data["holdings"].portfolio_id == portfolio.portfolio_id]
        for snapshot in rows.snapshot_date.unique():
            actual = rows.loc[rows.snapshot_date == snapshot, "market_value_base"].sum()
            expected = float(portfolio[f"aum_{snapshot}"])
            assert actual == pytest.approx(expected, abs=0.02)


def test_attribution_reconciles_for_all_clients(data):
    for client_id in data["clients"].client_id:
        result = attribute_change(data, client_id)
        assert result["reconciliation_difference_usd"] == pytest.approx(0, abs=0.01)


def test_fx_direction_uses_market_convention(data):
    assert usd_per_unit(data["market_context"], "EUR") == pytest.approx(1.092)
    assert usd_per_unit(data["market_context"], "HKD") == pytest.approx(1 / 7.81)


def test_margarethe_equity_band_is_review(data):
    review = portfolio_mandate_review(data, "CL-0003")
    equity = review.loc[review.asset_class == "Equity"].iloc[0]
    assert equity.actual_pct == pytest.approx(71.46, abs=0.1)
    assert equity.status == "review"


def test_lau_collateral_comparison_and_attention(data):
    facility = (
        data["credit_facilities"].loc[data["credit_facilities"].client_id == "CL-0014"].iloc[0]
    )
    scenario = collateral_scenario(facility, collateral_shock_pct=-1, target_ltv_pct=60)
    assert scenario["margin_call"] is True
    assert scenario["repayment_to_target"] > 0

    attention = attention_queue(data)
    assert len(attention) == 20
    assert attention.iloc[0].client_id == "CL-0014"
    assert attention.iloc[0].attention_index <= 100
    assert {"severity", "materiality", "urgency"}.issubset(attention.columns)
    assert AS_OF == "2026-08-26"
    cheung = attention.loc[attention.client_id == "CL-0012"].iloc[0]
    assert cheung.urgency == 100
