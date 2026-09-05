"""Tests for the bounded Command Center allocation scenario."""

import json

import pandas as pd
import pytest

from singhacks26.scenario import (
    allocation_by_asset_class,
    relevant_market_cards,
    simulate_reallocation,
)


@pytest.fixture
def holdings():
    return pd.DataFrame(
        [
            {
                "client_id": "CL-1",
                "snapshot_date": "2025-12-31",
                "asset_class": "Equity",
                "sector": "Information Technology",
                "market_value_usd": 999.0,
            },
            {
                "client_id": "CL-1",
                "snapshot_date": "2026-08-26",
                "asset_class": "Equity",
                "sector": "Information Technology",
                "market_value_usd": 600.0,
            },
            {
                "client_id": "CL-1",
                "snapshot_date": "2026-08-26",
                "asset_class": "Fixed Income",
                "sector": "Sovereign",
                "market_value_usd": 300.0,
            },
            {
                "client_id": "CL-1",
                "snapshot_date": "2026-08-26",
                "asset_class": "Cash and Equivalents",
                "sector": "Cash",
                "market_value_usd": 100.0,
            },
        ]
    )


@pytest.fixture
def market_context():
    rows = []
    for date, spx, nasdaq, treasury, vix in [
        ("2026-07-29", 7000.0, 23000.0, 4.5, 20.0),
        ("2026-08-26", 7100.0, 23500.0, 4.4, 18.0),
    ]:
        for series_id, name, unit, value in [
            ("SPX", "S&P 500 Index", "points", spx),
            ("NASDAQ_COMP", "Nasdaq Composite", "points", nasdaq),
            ("UST_10Y_PCT", "US Treasury 10-year yield", "percent", treasury),
            ("VIX", "CBOE Volatility Index", "points", vix),
            ("GOLD_USD_OZ", "Gold spot", "USD/troy oz", 4000.0),
        ]:
            rows.append(
                {
                    "snapshot_date": date,
                    "series_id": series_id,
                    "series_name": name,
                    "unit": unit,
                    "value": value,
                }
            )
    return pd.DataFrame(rows)


def test_allocation_uses_latest_snapshot(holdings):
    allocation = allocation_by_asset_class(holdings, "CL-1")
    assert allocation.set_index("asset_class").loc["Equity", "current_pct"] == 60.0
    assert allocation["current_value_usd"].sum() == 1000.0


def test_simulation_preserves_value_and_moves_requested_weight(holdings):
    scenario = simulate_reallocation(
        holdings,
        "CL-1",
        source_asset_class="Equity",
        destination_asset_class="Cash and Equivalents",
        shift_pct=10.0,
    )
    allocation = scenario["allocation"].set_index("asset_class")
    assert scenario["shift_value_usd"] == 100.0
    assert allocation.loc["Equity", "scenario_pct"] == 50.0
    assert allocation.loc["Cash and Equivalents", "scenario_pct"] == 20.0
    assert allocation["scenario_value_usd"].sum() == pytest.approx(1000.0)
    json.dumps(allocation.reset_index().to_dict(orient="records"))


def test_simulation_rejects_impossible_shift(holdings):
    with pytest.raises(ValueError, match="exceeds"):
        simulate_reallocation(holdings, "CL-1", "Fixed Income", "Equity", 40.0)
    with pytest.raises(ValueError, match="must differ"):
        simulate_reallocation(holdings, "CL-1", "Equity", "Equity", 1.0)


def test_market_cards_are_relevant_and_show_scenario_exposure(holdings, market_context):
    scenario = simulate_reallocation(
        holdings,
        "CL-1",
        source_asset_class="Equity",
        destination_asset_class="Fixed Income",
        shift_pct=10.0,
    )
    cards = relevant_market_cards(
        market_context,
        holdings,
        "CL-1",
        scenario["allocation"],
    )
    by_id = {card["series_id"]: card for card in cards}
    assert set(by_id) == {"SPX", "NASDAQ_COMP", "UST_10Y_PCT", "VIX"}
    assert by_id["SPX"]["delta"] == 100.0
    assert by_id["SPX"]["current_exposure_pct"] == 60.0
    assert by_id["SPX"]["scenario_exposure_pct"] == 50.0
    assert by_id["UST_10Y_PCT"]["scenario_exposure_pct"] == 40.0
    assert "GOLD_USD_OZ" not in by_id
