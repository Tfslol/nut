"""Offline tests for the importable news module (no live Marketaux calls)."""

from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest

import singhacks26.news as news
from singhacks26.news import NewsCache, held_sectors, most_affected, queries_for


def test_sector_query_mapping_skips_non_industries():
    exposure = {"Energy": 100.0, "Gold": 50.0, "Diversified": 30.0, "Cash": 10.0}
    queries = queries_for(exposure)
    assert [(q["sector"], q["kind"], q["value"]) for q in queries] == [
        ("Energy", "industries", "Energy"),
        ("Gold", "search", "gold"),
    ]


def test_held_sectors_uses_latest_snapshot_and_sorts():
    holdings = pd.DataFrame(
        [
            {
                "client_id": "CL-1",
                "snapshot_date": "2025-12-31",
                "sector": "Energy",
                "market_value_usd": 999.0,
            },
            {
                "client_id": "CL-1",
                "snapshot_date": "2026-08-26",
                "sector": "Energy",
                "market_value_usd": 300.0,
            },
            {
                "client_id": "CL-1",
                "snapshot_date": "2026-08-26",
                "sector": "Cash",
                "market_value_usd": 50.0,
            },
            {
                "client_id": "CL-2",
                "snapshot_date": "2026-08-26",
                "sector": "Energy",
                "market_value_usd": 1.0,
            },
        ]
    )
    exposure = held_sectors(holdings, "CL-1")
    assert exposure == {"Energy": 300.0, "Cash": 50.0}
    with pytest.raises(RuntimeError, match="No holdings found"):
        held_sectors(holdings, "CL-MISSING")


def test_cache_roundtrip_and_ttl(tmp_path):
    cache = NewsCache(tmp_path / "news_cache.json")
    assert cache.needs_refresh()

    fresh = {
        "schema_version": "news-cache/1.0",
        "fetched_utc": datetime.now(UTC).isoformat(),
        "clients": {},
    }
    cache.save(fresh)
    assert cache.load() == fresh
    assert not cache.needs_refresh()

    stale = {
        "schema_version": "news-cache/1.0",
        "fetched_utc": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        "clients": {},
    }
    cache.save(stale)
    assert cache.needs_refresh()

    cache.invalidate()
    assert cache.needs_refresh()


def test_missing_key_raises_feature_error(monkeypatch):
    monkeypatch.delenv("MARKETAUX_API_KEY", raising=False)
    monkeypatch.setattr(news, "load_dotenv", lambda *args, **kwargs: None)
    with pytest.raises(RuntimeError, match="MARKETAUX_API_KEY"):
        news.marketaux_api_key()


def test_refresh_news_honours_ttl_without_hitting_api(monkeypatch, tmp_path):
    cache = NewsCache(tmp_path / "news_cache.json")
    cache.save(
        {
            "schema_version": "news-cache/1.0",
            "fetched_utc": datetime.now(UTC).isoformat(),
            "clients": {"marker": "cached"},
        }
    )

    def boom(*args, **kwargs):
        raise AssertionError("the API must not be called within the TTL")

    monkeypatch.setattr(news, "marketaux_api_key", boom)
    monkeypatch.setattr(news, "fetch_news", boom)
    result = news.refresh_news({"clients": pd.DataFrame(), "holdings": pd.DataFrame()}, cache=cache)
    assert result["clients"]["marker"] == "cached"


def test_refresh_news_force_fetches_and_normalises(monkeypatch, tmp_path):
    cache = NewsCache(tmp_path / "news_cache.json")
    holdings = pd.DataFrame(
        [
            {
                "client_id": "CL-A",
                "snapshot_date": "2026-08-26",
                "sector": "Energy",
                "market_value_usd": 500.0,
            }
        ]
    )
    clients = pd.DataFrame({"client_id": ["CL-A"]})

    monkeypatch.setattr(news, "marketaux_api_key", lambda: "test-key")

    def fake_fetch(key, params):
        return [
            {
                "uuid": "u1",
                "title": "T1",
                "url": "",
                "source": "s",
                "published_at": "2026-08-26T00:00:00+00:00",
                "snippet": "x",
                "entities": [],
            },
            {
                "uuid": "u1",
                "title": "T1",
                "url": "",
                "source": "s",
                "published_at": "2026-08-26T00:00:00+00:00",
                "snippet": "x",
                "entities": [],
            },
        ]

    monkeypatch.setattr(news, "fetch_news", fake_fetch)
    result = news.refresh_news({"clients": clients, "holdings": holdings}, cache=cache, force=True, sleep_seconds=0)
    sector = result["clients"]["CL-A"]["sectors"][0]
    assert sector["sector"] == "Energy"
    assert len(sector["articles"]) == 1  # de-duplicated by uuid
    assert sector["articles"][0]["uuid"] == "u1"


def test_most_affected_exposure_weighting():
    holdings = pd.DataFrame(
        [
            {
                "client_id": "CL-A",
                "snapshot_date": "2026-08-26",
                "sector": "Energy",
                "market_value_usd": 900.0,
            },
            {
                "client_id": "CL-A",
                "snapshot_date": "2026-08-26",
                "sector": "Cash",
                "market_value_usd": 100.0,
            },
            {
                "client_id": "CL-B",
                "snapshot_date": "2026-08-26",
                "sector": "Energy",
                "market_value_usd": 100.0,
            },
            {
                "client_id": "CL-B",
                "snapshot_date": "2026-08-26",
                "sector": "Cash",
                "market_value_usd": 900.0,
            },
        ]
    )
    article = {"uuid": "1", "title": "Energy headline", "published_at": "2026-08-26T00:00:00+00:00"}
    cache = {
        "clients": {
            "CL-A": {"client_id": "CL-A", "sectors": [{"sector": "Energy", "articles": [article]}]},
            "CL-B": {"client_id": "CL-B", "sectors": [{"sector": "Energy", "articles": [article]}]},
        }
    }
    ranking = most_affected(cache, holdings, as_of=datetime(2026, 8, 26, tzinfo=UTC))
    assert ranking.iloc[0]["client_id"] == "CL-A"
    assert ranking.iloc[0]["exposure_weighted_score"] == pytest.approx(0.9)
    assert ranking.iloc[0]["exposed_sectors"] == ["Energy"]


def test_most_affected_skips_clients_without_articles():
    holdings = pd.DataFrame(
        [
            {
                "client_id": "CL-A",
                "snapshot_date": "2026-08-26",
                "sector": "Cash",
                "market_value_usd": 100.0,
            },
        ]
    )
    cache = {"clients": {"CL-A": {"client_id": "CL-A", "sectors": [{"sector": "Cash", "articles": []}]}}}
    ranking = most_affected(cache, holdings, as_of=datetime(2026, 8, 26, tzinfo=UTC))
    assert ranking.empty


def test_news_cache_is_separate_from_controlled_event_log(tmp_path):
    """Live news must never be persisted over the authoritative event_log.csv."""
    event_log_path = news.DATA / "event_log.csv"
    assert event_log_path.exists()

    assert news.CACHE_PATH.name == "news_cache.json"
    assert "obsidian_vault" in str(news.CACHE_PATH)
    assert news.CACHE_PATH.resolve() != event_log_path.resolve()

    cache = NewsCache(tmp_path / "news_cache.json")
    before = event_log_path.read_bytes()
    cache.save({"schema_version": "news-cache/1.0", "fetched_utc": "2026-09-05T00:00:00+00:00", "clients": {}})
    assert cache.load()["schema_version"] == "news-cache/1.0"
    assert event_log_path.read_bytes() == before  # event_log.csv is untouched
    assert cache.path != event_log_path
