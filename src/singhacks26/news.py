"""Importable Marketaux news loop for the RM workbench.

This module factors ``scripts/market_api.py`` into reusable functions so the
Streamlit app can refresh and display live news without re-implementing the
fetch logic. The script remains a thin CLI wrapper around this module.

Data notes
----------
The synthetic holdings have no tickers, so symbol-based queries are impossible.
Instead each holding's ``sector`` label is translated into the Marketaux
industry taxonomy (``industries=``) and the news feed is queried per sector.
Internal classification labels that are not real industries (e.g. "Diversified",
"Corporate", "Macro", "Multi", "Cash") are skipped; themes such as "Gold" are
queried with the free-text ``search`` parameter.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
DATA = ROOT / "data"
ENV_FILE = ROOT / ".env"
VAULT = ROOT / "obsidian_vault"
NEWS_URL = "https://api.marketaux.com/v1/news/all"
DEFAULT_CLIENT = "CL-0001"
USER_AGENT = "singhacks26-wealth-intel/0.1 (hackathon)"
CACHE_PATH = VAULT / "news_cache.json"
TTL_SECONDS = 60 * 60  # one hour

# data/ `sector` label -> Marketaux query. None => not a real industry, skip it.
# Marketaux industry names come from /v1/entity/industry/list.
SECTOR_QUERY: dict[str, tuple[str, str] | None] = {
    "Energy": ("industries", "Energy"),
    "Information Technology": ("industries", "Technology"),
    "Industrials": ("industries", "Industrials"),
    "Health Care": ("industries", "Healthcare"),
    "Real Estate": ("industries", "Real Estate"),
    "Utilities": ("industries", "Utilities"),
    "Consumer Discretionary": ("industries", "Consumer Cyclical"),
    "Consumer Staples": ("industries", "Consumer Defensive"),
    "Financials": ("industries", "Financial Services"),
    "Basic Materials": ("industries", "Basic Materials"),
    "Communication Services": ("industries", "Communication Services"),
    # Internal / synthetic labels and themes that are not Marketaux industries.
    "Gold": ("search", "gold"),
    "Diversified": None,
    "Corporate": None,
    "Cash": None,
    "Macro": None,
    "Multi": None,
    "Sovereign": None,
    "Equity Long Short": None,
    "Infrastructure": None,
    "Financial": ("industries", "Financial"),
    "Services": ("industries", "Services"),
}


def load_dotenv(path: Path = ENV_FILE) -> None:
    """Load ``KEY=VALUE`` lines from ``.env`` into os.environ (never overwrites)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def marketaux_api_key() -> str:
    """Return the Marketaux key or raise a clear feature-level error."""
    load_dotenv()
    key = os.environ.get("MARKETAUX_API_KEY", "").strip()
    if not key:
        raise RuntimeError(
            "MARKETAUX_API_KEY is not set. Add it to the repo-root .env file "
            "(MARKETAUX_API_KEY=...) to enable the live news feed."
        )
    return key


def held_sectors(holdings: pd.DataFrame, client_id: str) -> dict[str, float]:
    """Latest-snapshot sector exposure (USD) for a client, from holdings rows."""
    client = holdings[holdings["client_id"] == client_id]
    if client.empty:
        raise RuntimeError(f"No holdings found for {client_id} in holdings data")
    latest = client[client["snapshot_date"] == client["snapshot_date"].max()]
    grouped = latest.groupby("sector")["market_value_usd"].sum()
    return grouped.sort_values(ascending=False).to_dict()


def queries_for(sector_exposure: dict[str, float]) -> list[dict]:
    """Translate held sectors into Marketaux query descriptors."""
    queries: list[dict] = []
    for sector, usd in sector_exposure.items():
        mapping = SECTOR_QUERY.get(sector)
        if mapping is None:
            continue
        kind, value = mapping
        queries.append(
            {
                "sector": sector,
                "market_value_usd": usd,
                "kind": kind,
                "value": value,
            }
        )
    return queries


def fetch_news(key: str, params: dict) -> list[dict]:
    """Fetch one page of Marketaux news and return the ``data`` list."""
    url = NEWS_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if isinstance(payload, dict) and "error" in payload:
        code = payload["error"].get("code", "unknown")
        message = payload["error"].get("message", "")
        raise RuntimeError(f"Marketaux API error {code}: {message}")
    return payload.get("data", []) if isinstance(payload, dict) else []


def _normalise_article(article: dict) -> dict:
    """Reduce a raw Marketaux article to the cached, provider-safe fields."""
    return {
        "uuid": article.get("uuid"),
        "title": article.get("title"),
        "url": article.get("url"),
        "source": article.get("source"),
        "published_at": article.get("published_at"),
        "snippet": (article.get("snippet") or "")[:300],
        "entities": [
            {
                "symbol": entity.get("symbol"),
                "name": entity.get("name"),
                "industry": entity.get("industry"),
            }
            for entity in (article.get("entities") or [])
        ],
    }


def _dedupe(entries: list[dict]) -> list[dict]:
    """Drop repeated articles by ``uuid`` (Marketaux group_similar duplicates)."""
    seen: set[str] = set()
    result: list[dict] = []
    for entry in entries:
        uuid = entry.get("uuid")
        if uuid is not None and uuid in seen:
            continue
        if uuid is not None:
            seen.add(uuid)
        result.append(entry)
    return result


def normalise_articles(articles: list[dict], *, limit: int | None = None) -> list[dict]:
    """Normalise and de-duplicate raw articles, optionally capping per sector."""
    entries = _dedupe([_normalise_article(article) for article in articles])
    return entries[:limit] if limit is not None else entries


def _describe_error(exc: BaseException) -> str:
    if isinstance(exc, urllib.error.HTTPError):
        return f"HTTP {exc.code}"
    return str(exc)


class NewsCache:
    """JSON cache for per-client sector news in ``obsidian_vault/news_cache.json``."""

    def __init__(self, path: Path = CACHE_PATH):
        self.path = path

    def empty(self) -> dict:
        return {"schema_version": "news-cache/1.0", "fetched_utc": None, "clients": {}}

    def load(self) -> dict:
        if not self.path.exists():
            return self.empty()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return self.empty()
        payload.setdefault("schema_version", "news-cache/1.0")
        payload.setdefault("fetched_utc", None)
        payload.setdefault("clients", {})
        return payload

    def save(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)

    def fetched_at(self, payload: dict | None = None) -> datetime | None:
        payload = payload if payload is not None else self.load()
        value = payload.get("fetched_utc")
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            return None
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)

    def needs_refresh(self, ttl_seconds: int = TTL_SECONDS) -> bool:
        fetched = self.fetched_at()
        if fetched is None:
            return True
        return datetime.now(UTC) - fetched >= timedelta(seconds=ttl_seconds)

    def invalidate(self) -> None:
        if self.path.exists():
            self.path.unlink()

    def client_entry(self, payload: dict, client_id: str) -> dict:
        return payload.get("clients", {}).get(client_id, {"client_id": client_id, "sectors": []})

    def articles_for(self, payload: dict, client_id: str) -> list[dict]:
        articles: list[dict] = []
        entry = self.client_entry(payload, client_id)
        for sector in entry.get("sectors", []):
            articles.extend(sector.get("articles", []))
        return articles


def refresh_news(
    data: dict,
    *,
    cache: NewsCache | None = None,
    force: bool = False,
    sleep_seconds: float = 1.0,
    days: int = 7,
    limit: int = 5,
    language: str = "en",
) -> dict:
    """Loop all clients, fetch per-sector Marketaux news and persist the cache.

    Returns the full cache payload. A plain call within the cache TTL returns the
    stored payload without re-hitting the API; ``force=True`` refetches.
    ``MARKETAUX_API_KEY`` missing raises a feature-level ``RuntimeError``.
    """
    cache = cache or NewsCache()
    if not force and not cache.needs_refresh():
        return cache.load()

    key = marketaux_api_key()
    holdings = data["holdings"]
    client_ids = sorted(data["clients"]["client_id"].unique().tolist())
    published_after = (datetime.now(UTC) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")

    payload = {
        "schema_version": "news-cache/1.0",
        "fetched_utc": datetime.now(UTC).isoformat(),
        "days": days,
        "clients": {},
    }
    for client_id in client_ids:
        sectors: list[dict] = []
        errors: list[str] = []
        for query in queries_for(held_sectors(holdings, client_id)):
            params = {
                "api_token": key,
                "language": language,
                "group_similar": "true",
                "published_after": published_after,
                "limit": str(limit),
            }
            params[query["kind"]] = query["value"]
            try:
                articles = fetch_news(key, params)
            except (urllib.error.HTTPError, urllib.error.URLError, RuntimeError, OSError) as exc:
                message = _describe_error(exc)
                errors.append(f"{query['sector']}: {message}")
                sectors.append(
                    {
                        "sector": query["sector"],
                        "market_value_usd": query["market_value_usd"],
                        "query": {query["kind"]: query["value"]},
                        "articles": [],
                        "error": message,
                    }
                )
            else:
                sectors.append(
                    {
                        "sector": query["sector"],
                        "market_value_usd": query["market_value_usd"],
                        "query": {query["kind"]: query["value"]},
                        "articles": normalise_articles(articles, limit=limit),
                        "error": None,
                    }
                )
            if sleep_seconds > 0:
                time.sleep(sleep_seconds)
        payload["clients"][client_id] = {
            "client_id": client_id,
            "sectors": sectors,
            "errors": errors,
        }

    cache.save(payload)
    return payload


def _recency_weight(published_at: str | None, as_of: datetime) -> float:
    """Return a 0..1 weight that decays linearly over the 7-day look-back window."""
    if not published_at:
        return 0.0
    try:
        published = datetime.fromisoformat(published_at)
    except ValueError:
        return 0.0
    if published.tzinfo is None:
        published = published.replace(tzinfo=UTC)
    age_days = (as_of - published).total_seconds() / 86400
    if age_days < 0:
        return 0.0
    return max(0.0, 1.0 - age_days / 7.0)


def most_affected(
    cache: NewsCache | dict,
    holdings: pd.DataFrame,
    *,
    as_of: datetime | None = None,
) -> pd.DataFrame:
    """Rank clients by exposure-weighted, recency-decayed news relevance.

    Score = sum over the client's sectors of (sector share of latest household
    value × sum of article recency weights). The result is a review lead labelled
    as live news, distinct from the controlled ``event_log.csv`` surface.
    """
    payload = cache.load() if isinstance(cache, NewsCache) else cache
    as_of = as_of or datetime.now(UTC)
    if as_of.tzinfo is None:
        as_of = as_of.replace(tzinfo=UTC)

    latest = holdings["snapshot_date"].max()
    rows: list[dict] = []
    for client_id, entry in payload.get("clients", {}).items():
        client_positions = holdings[(holdings["client_id"] == client_id) & (holdings["snapshot_date"] == latest)]
        total = float(client_positions["market_value_usd"].sum())
        if total <= 0:
            continue
        exposure = client_positions.groupby("sector")["market_value_usd"].sum()

        score = 0.0
        exposed_sectors: list[str] = []
        headlines: list[str] = []
        for sector in entry.get("sectors", []):
            articles = [a for a in sector.get("articles", []) if a.get("published_at")]
            if not articles:
                continue
            share = float(exposure.get(sector["sector"], 0.0)) / total
            sector_score = sum(_recency_weight(a.get("published_at"), as_of) for a in articles)
            weighted = share * sector_score
            score += weighted
            if weighted > 0:
                exposed_sectors.append(sector["sector"])
                driving = max(articles, key=lambda a: _recency_weight(a.get("published_at"), as_of))
                if driving.get("title"):
                    headlines.append(driving["title"])

        if score <= 0:
            continue
        rows.append(
            {
                "client_id": client_id,
                "exposure_weighted_score": round(score, 6),
                "exposed_sectors": exposed_sectors,
                "driving_headlines": headlines[:3],
            }
        )
    columns = ["client_id", "exposure_weighted_score", "exposed_sectors", "driving_headlines"]
    if not rows:
        return pd.DataFrame(columns=columns)
    return pd.DataFrame(rows, columns=columns).sort_values("exposure_weighted_score", ascending=False)
