"""Bounded allocation scenarios and controlled market cards for RM review."""

from __future__ import annotations

from typing import Any

import pandas as pd

ASSET_CLASSES = (
    "Cash and Equivalents",
    "Fixed Income",
    "Equity",
    "Commodities",
    "Alternatives",
    "Structured Products",
)

MARKET_CARD_RULES = (
    {
        "series_id": "SPX",
        "label": "S&P 500",
        "exposure_asset_class": "Equity",
        "required_sector": None,
    },
    {
        "series_id": "NASDAQ_COMP",
        "label": "Nasdaq",
        "exposure_asset_class": "Equity",
        "required_sector": "Information Technology",
    },
    {
        "series_id": "GOLD_USD_OZ",
        "label": "Gold",
        "exposure_asset_class": "Commodities",
        "required_sector": "Gold",
    },
    {
        "series_id": "BRENT_USD_BBL",
        "label": "Brent",
        "exposure_asset_class": "Commodities",
        "required_sector": "Energy",
    },
    {
        "series_id": "UST_10Y_PCT",
        "label": "US 10Y",
        "exposure_asset_class": "Fixed Income",
        "required_sector": None,
    },
    {
        "series_id": "VIX",
        "label": "VIX",
        "exposure_asset_class": "Equity",
        "required_sector": None,
    },
)


def latest_client_positions(holdings: pd.DataFrame, client_id: str) -> pd.DataFrame:
    """Return a client's latest supplied holdings snapshot."""
    client = holdings.loc[holdings["client_id"] == client_id]
    if client.empty:
        return client.copy()
    latest = client["snapshot_date"].max()
    return client.loc[client["snapshot_date"] == latest].copy()


def allocation_by_asset_class(holdings: pd.DataFrame, client_id: str) -> pd.DataFrame:
    """Return latest USD allocation with explicit values and weights."""
    positions = latest_client_positions(holdings, client_id)
    columns = ["asset_class", "current_value_usd", "current_pct"]
    if positions.empty:
        return pd.DataFrame(columns=columns)
    grouped = positions.groupby("asset_class", as_index=False)["market_value_usd"].sum()
    grouped = grouped.rename(columns={"market_value_usd": "current_value_usd"})
    total = float(grouped["current_value_usd"].sum())
    grouped["current_pct"] = (
        grouped["current_value_usd"].div(total).mul(100).round(2) if total else 0.0
    )
    return grouped.sort_values("current_value_usd", ascending=False).reset_index(drop=True)


def simulate_reallocation(
    holdings: pd.DataFrame,
    client_id: str,
    source_asset_class: str,
    destination_asset_class: str,
    shift_pct: float,
) -> dict[str, Any]:
    """Move a portfolio-weight percentage between asset classes at unchanged prices."""
    if source_asset_class == destination_asset_class:
        raise ValueError("Source and destination asset classes must differ.")
    if shift_pct < 0:
        raise ValueError("Scenario shift cannot be negative.")

    current = allocation_by_asset_class(holdings, client_id)
    if current.empty:
        raise ValueError(f"No holdings available for {client_id}.")
    values = current.set_index("asset_class")["current_value_usd"].to_dict()
    if source_asset_class not in values:
        raise ValueError(f"No current {source_asset_class} allocation is available to reallocate.")

    total = float(sum(values.values()))
    shift_value = total * float(shift_pct) / 100
    if shift_value > float(values[source_asset_class]) + 0.01:
        raise ValueError("Scenario shift exceeds the available source allocation.")

    proposed = dict(values)
    proposed[source_asset_class] -= shift_value
    proposed[destination_asset_class] = proposed.get(destination_asset_class, 0.0) + shift_value
    asset_classes = [asset_class for asset_class in ASSET_CLASSES if asset_class in proposed]
    asset_classes.extend(sorted(set(proposed) - set(asset_classes)))
    rows = [
        {
            "asset_class": asset_class,
            "current_value_usd": round(float(values.get(asset_class, 0.0)), 2),
            "scenario_value_usd": round(float(proposed.get(asset_class, 0.0)), 2),
            "current_pct": round(float(values.get(asset_class, 0.0)) / total * 100, 2),
            "scenario_pct": round(float(proposed.get(asset_class, 0.0)) / total * 100, 2),
        }
        for asset_class in asset_classes
    ]
    allocation = pd.DataFrame(rows)
    return {
        "client_id": client_id,
        "source_asset_class": source_asset_class,
        "destination_asset_class": destination_asset_class,
        "shift_pct": round(float(shift_pct), 2),
        "shift_value_usd": round(shift_value, 2),
        "total_value_usd": round(total, 2),
        "allocation": allocation,
        "largest_current_pct": round(float(allocation["current_pct"].max()), 2),
        "largest_scenario_pct": round(float(allocation["scenario_pct"].max()), 2),
        "assumptions": [
            "Total portfolio value and all market prices remain unchanged.",
            (
                "The selected percentage is moved between asset classes only; instruments are "
                "not selected."
            ),
            (
                "Fees, spreads, tax, FX, suitability, liquidity and transaction feasibility "
                "are excluded."
            ),
        ],
    }


def relevant_market_cards(
    market_context: pd.DataFrame,
    holdings: pd.DataFrame,
    client_id: str,
    scenario_allocation: pd.DataFrame | None = None,
) -> list[dict[str, Any]]:
    """Return controlled market cards relevant to latest client exposures."""
    positions = latest_client_positions(holdings, client_id)
    if positions.empty or market_context.empty:
        return []
    current = allocation_by_asset_class(holdings, client_id).set_index("asset_class")
    current_weights = current["current_pct"].to_dict()
    scenario_weights = dict(current_weights)
    if scenario_allocation is not None and not scenario_allocation.empty:
        scenario_weights = scenario_allocation.set_index("asset_class")["scenario_pct"].to_dict()

    sectors = set(positions.loc[positions["market_value_usd"] > 0, "sector"].astype(str))
    dates = sorted(market_context["snapshot_date"].astype(str).unique())
    if not dates:
        return []
    latest_date = dates[-1]
    previous_date = dates[-2] if len(dates) > 1 else None
    latest = market_context.loc[
        market_context["snapshot_date"].astype(str) == latest_date
    ].set_index("series_id")
    previous = (
        market_context.loc[market_context["snapshot_date"].astype(str) == previous_date].set_index(
            "series_id"
        )
        if previous_date
        else pd.DataFrame()
    )

    cards: list[dict[str, Any]] = []
    for rule in MARKET_CARD_RULES:
        asset_class = str(rule["exposure_asset_class"])
        required_sector = rule["required_sector"]
        has_class_exposure = (
            max(
                float(current_weights.get(asset_class, 0.0)),
                float(scenario_weights.get(asset_class, 0.0)),
            )
            > 0
        )
        if not has_class_exposure or (required_sector and required_sector not in sectors):
            continue
        series_id = str(rule["series_id"])
        if series_id not in latest.index:
            continue
        latest_row = latest.loc[series_id]
        previous_value = (
            float(previous.loc[series_id, "value"])
            if previous_date and series_id in previous.index
            else None
        )
        value = float(latest_row["value"])
        cards.append(
            {
                "series_id": series_id,
                "label": rule["label"],
                "unit": str(latest_row["unit"]),
                "value": value,
                "delta": None if previous_value is None else round(value - previous_value, 4),
                "latest_date": latest_date,
                "previous_date": previous_date,
                "exposure_asset_class": asset_class,
                "current_exposure_pct": round(float(current_weights.get(asset_class, 0.0)), 2),
                "scenario_exposure_pct": round(float(scenario_weights.get(asset_class, 0.0)), 2),
            }
        )
    return cards
