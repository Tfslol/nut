"""Deterministic RM action briefs from alignment leads and cached market news."""

from __future__ import annotations

from typing import Any

import pandas as pd

SEVERITY_RANK = {"Urgent": 4, "High": 3, "Medium": 2, "Low": 1}

WHEN_BY_SEVERITY = {
    "Urgent": "Today, before accepting a client instruction or proposing a portfolio action.",
    "High": "Before the next client contact; target this business week.",
    "Medium": "At the next scheduled review; bring it forward if the client situation changes.",
    "Low": "Include it in the next routine suitability review.",
}

WHAT_BY_CATEGORY = {
    "risk_profile": (
        "Run a suitability check on whether the portfolio risk still matches the client's "
        "stated profile."
    ),
    "mandate": (
        "Review the flagged exposure against the agreed mandate before discussing portfolio "
        "options."
    ),
    "objectives": (
        "Reconcile the portfolio with the client's current objective, life event and "
        "liquidity needs."
    ),
    "event": (
        "Ask whether the controlled event changed the client's preferences or behaviour "
        "without assuming causation."
    ),
}

HOW_BY_CATEGORY = {
    "risk_profile": (
        "Compare the latest allocation and concentration with the recorded risk profile, "
        "then confirm the client's understanding and capacity for loss."
    ),
    "mandate": (
        "Check the latest holdings against the relevant mandate range and prepare compliant "
        "review options for RM approval."
    ),
    "objectives": (
        "Map dated cash needs and stated objectives to available liquidity, investment "
        "horizon and portfolio constraints."
    ),
    "event": (
        "Build a dated sequence from the controlled event log and client records, then test "
        "the interpretation with an open question."
    ),
}


def _article_key(article: dict[str, Any]) -> str:
    return str(article.get("uuid") or article.get("url") or article.get("title") or "")


def market_signals_for_client(
    news_payload: dict[str, Any] | None,
    holdings: pd.DataFrame,
    client_id: str,
    *,
    limit: int = 3,
) -> list[dict[str, Any]]:
    """Return one recent cached headline per exposed sector, weighted by exposure.

    The news cache is already constrained to held sectors. This helper adds the
    latest-snapshot portfolio share and keeps the page compact; it does not infer
    sentiment, price impact or causation from a headline.
    """
    if not news_payload or limit <= 0:
        return []

    client_holdings = holdings.loc[holdings["client_id"] == client_id]
    if client_holdings.empty:
        return []
    latest = client_holdings["snapshot_date"].max()
    latest_holdings = client_holdings.loc[client_holdings["snapshot_date"] == latest]
    total_value = float(latest_holdings["market_value_usd"].sum())
    if total_value <= 0:
        return []
    sector_values = latest_holdings.groupby("sector")["market_value_usd"].sum().to_dict()

    entry = news_payload.get("clients", {}).get(client_id, {})
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for sector_entry in entry.get("sectors", []):
        sector = str(sector_entry.get("sector") or "Unclassified")
        sector_value = float(sector_values.get(sector, 0.0))
        if sector_value <= 0:
            continue
        articles = sorted(
            (article for article in sector_entry.get("articles", []) if article.get("title")),
            key=lambda article: str(article.get("published_at") or ""),
            reverse=True,
        )
        for article in articles:
            key = _article_key(article)
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            candidates.append(
                {
                    "sector": sector,
                    "sector_exposure_pct": round(sector_value / total_value * 100, 1),
                    "title": str(article.get("title") or "Untitled market signal"),
                    "source": str(article.get("source") or "Unknown source"),
                    "published_at": article.get("published_at"),
                    "url": article.get("url"),
                    "snippet": str(article.get("snippet") or ""),
                    "evidence_id": f"news:{key or article.get('title', 'untitled')}",
                }
            )
            break

    return sorted(
        candidates,
        key=lambda signal: (
            float(signal["sector_exposure_pct"]),
            str(signal.get("published_at") or ""),
        ),
        reverse=True,
    )[:limit]


def _signal_matches_conflict(signal: dict[str, Any], conflict: dict[str, Any]) -> bool:
    text = " ".join(
        str(conflict.get(field) or "") for field in ("headline", "detail", "discussion_topic")
    ).lower()
    sector = str(signal.get("sector") or "").lower()
    terms = {sector}
    terms.update(part for part in sector.replace("&", " ").split() if len(part) >= 4)
    if "information technology" in sector:
        terms.update({"technology", "tech"})
    if "basic materials" in sector:
        terms.update({"materials", "gold", "metals"})
    return any(term and term in text for term in terms)


def build_action_briefs(
    alignment_report: dict[str, Any] | None,
    market_signals: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Decompose alignment conflicts into ordered what/when/why/how briefs."""
    if not alignment_report:
        return []

    signals = market_signals or []
    conflicts = sorted(
        alignment_report.get("conflicts", []),
        key=lambda conflict: SEVERITY_RANK.get(str(conflict.get("severity")), 0),
        reverse=True,
    )
    briefs: list[dict[str, Any]] = []
    for position, conflict in enumerate(conflicts, start=1):
        category = str(conflict.get("category") or "review")
        severity = str(conflict.get("severity") or "Low")
        direct_signals = [
            signal for signal in signals if _signal_matches_conflict(signal, conflict)
        ]
        contextual_signals = direct_signals or signals[:1]
        market_note = None
        if contextual_signals:
            signal = contextual_signals[0]
            relationship = (
                "Directly related market signal" if direct_signals else "Portfolio market context"
            )
            market_note = (
                f"{relationship}: {signal['sector']} represents "
                f"{signal['sector_exposure_pct']:.1f}% of the latest portfolio and has a "
                "cached headline. Validate its relevance before changing the client "
                "conversation."
            )

        evidence_ids = [str(item) for item in conflict.get("evidence_ids", [])]
        discussion_topic = conflict.get("discussion_topic") or (
            "Confirm the client view and what has changed."
        )
        how = [
            HOW_BY_CATEGORY.get(
                category,
                "Verify the underlying client, mandate and latest-holdings evidence before "
                "forming a view.",
            ),
            f"Use this as the client question: {discussion_topic}",
        ]
        if market_note:
            how.append(
                "Read the linked market signal and distinguish verified facts from headline "
                "framing; do not infer performance or causation."
            )
        how.append(
            "Record the RM's conclusion, client response, uncertainties and agreed follow-up "
            "in the action record."
        )

        briefs.append(
            {
                "position": position,
                "conflict_id": conflict.get("conflict_id"),
                "headline": str(conflict.get("headline") or "Review lead"),
                "severity": severity,
                "category": category,
                "what": WHAT_BY_CATEGORY.get(
                    category,
                    "Investigate the review lead and prepare a focused client discussion.",
                ),
                "when": WHEN_BY_SEVERITY.get(severity, WHEN_BY_SEVERITY["Low"]),
                "why": str(
                    conflict.get("detail") or "The alignment report raised this for RM review."
                ),
                "how": how,
                "market_note": market_note,
                "market_signals": contextual_signals,
                "evidence_ids": evidence_ids,
            }
        )
    return briefs
