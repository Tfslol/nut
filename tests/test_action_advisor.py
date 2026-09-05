"""Offline tests for the deterministic RM action-advisor layer."""

import pandas as pd

from singhacks26.action_advisor import build_action_briefs, market_signals_for_client


def _holdings():
    return pd.DataFrame(
        [
            {
                "client_id": "CL-1",
                "snapshot_date": "2026-08-26",
                "sector": "Gold",
                "market_value_usd": 700.0,
            },
            {
                "client_id": "CL-1",
                "snapshot_date": "2026-08-26",
                "sector": "Information Technology",
                "market_value_usd": 300.0,
            },
            {
                "client_id": "CL-1",
                "snapshot_date": "2025-12-31",
                "sector": "Gold",
                "market_value_usd": 9999.0,
            },
        ]
    )


def _news_payload():
    return {
        "fetched_utc": "2026-09-05T08:00:00+00:00",
        "clients": {
            "CL-1": {
                "sectors": [
                    {
                        "sector": "Gold",
                        "articles": [
                            {
                                "uuid": "gold-new",
                                "title": "Gold market reprices after volatile session",
                                "source": "Example Wire",
                                "published_at": "2026-09-05T07:00:00+00:00",
                                "url": "https://example.com/gold-new",
                                "snippet": "Latest gold-market context.",
                            },
                            {
                                "uuid": "gold-old",
                                "title": "Older gold story",
                                "source": "Example Wire",
                                "published_at": "2026-09-04T07:00:00+00:00",
                            },
                        ],
                    },
                    {
                        "sector": "Information Technology",
                        "articles": [
                            {
                                "uuid": "tech",
                                "title": "Technology earnings update",
                                "source": "Example Wire",
                                "published_at": "2026-09-05T06:00:00+00:00",
                            }
                        ],
                    },
                ]
            }
        },
    }


def test_market_signals_are_compact_exposure_weighted_and_recent():
    signals = market_signals_for_client(_news_payload(), _holdings(), "CL-1")
    assert [signal["sector"] for signal in signals] == ["Gold", "Information Technology"]
    assert signals[0]["sector_exposure_pct"] == 70.0
    assert signals[0]["title"] == "Gold market reprices after volatile session"
    assert signals[0]["evidence_id"] == "news:gold-new"


def test_action_briefs_prioritise_and_connect_matching_market_signal():
    report = {
        "client_id": "CL-1",
        "conflicts": [
            {
                "conflict_id": "C-LOW",
                "category": "event",
                "severity": "Low",
                "headline": "Review recent activity",
                "detail": "Timing warrants a client check-in.",
                "discussion_topic": "Ask what changed.",
                "evidence_ids": ["event_log.csv:E-1"],
            },
            {
                "conflict_id": "C-GOLD",
                "category": "risk_profile",
                "severity": "Urgent",
                "headline": "Gold concentration exceeds stated comfort",
                "detail": "The client's gold exposure conflicts with the recorded risk preference.",
                "discussion_topic": "Confirm the client's comfort with gold concentration.",
                "evidence_ids": ["holdings.csv:2026-08-26"],
            },
        ],
    }
    signals = market_signals_for_client(_news_payload(), _holdings(), "CL-1")
    briefs = build_action_briefs(report, signals)

    assert [brief["conflict_id"] for brief in briefs] == ["C-GOLD", "C-LOW"]
    assert briefs[0]["what"].startswith("Run a suitability check")
    assert briefs[0]["when"].startswith("Today")
    assert briefs[0]["market_signals"][0]["sector"] == "Gold"
    assert briefs[0]["market_note"].startswith("Directly related market signal")
    assert any("client question" in step for step in briefs[0]["how"])


def test_action_briefs_do_not_invent_a_lead_when_report_has_no_conflicts():
    assert build_action_briefs({"client_id": "CL-1", "conflicts": []}, []) == []
    assert market_signals_for_client(None, _holdings(), "CL-1") == []
