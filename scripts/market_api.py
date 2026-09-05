"""Fetch the latest Marketaux news for the sectors a client holds (default CL-0001).

The API key is read from the ``MARKETAUX_API_KEY`` environment variable, which is
loaded from the repo-root ``.env`` file if present (the key value is never printed,
logged or hard-coded).

Data notes
----------
The synthetic holdings have no tickers, so symbol-based queries are impossible.
Instead we translate each holding's ``sector`` label into the Marketaux industry
taxonomy (``industries=``) and query the news feed per sector. Internal
classification labels that are not real industries (e.g. "Diversified",
"Corporate", "Macro", "Multi", "Cash") are skipped; themes such as "Gold" are
queried with the free-text ``search`` parameter.

Usage
-----
    python scripts/market_api.py                # CL-0001, last 7 days
    python scripts/market_api.py CL-0002 --days 3 --limit 5
    python scripts/market_api.py CL-0001 --out news_cl0001.json
"""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
ENV_FILE = ROOT / ".env"
NEWS_URL = "https://api.marketaux.com/v1/news/all"
DEFAULT_CLIENT = "CL-0001"
USER_AGENT = "singhacks26-wealth-intel/0.1 (hackathon)"

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
    """Load ``KEY=VALUE`` lines from ``.env`` into os.environ (never overwrites).

    Exists only so the script can run without the key exported in the shell; the
    key value itself is only referenced via ``os.environ`` below.
    """
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


def api_key() -> str:
    load_dotenv()
    key = os.environ.get("MARKETAUX_API_KEY", "").strip()
    if not key:
        raise SystemExit(
            "MARKETAUX_API_KEY is not set. Add it to the repo-root .env file " "(MARKETAUX_API_KEY=...) and re-run."
        )
    return key


def held_sectors(client_id: str) -> dict[str, float]:
    """Latest-snapshot sector exposure (USD) for a client, from holdings.csv."""
    hold = pd.read_csv(DATA / "holdings.csv")
    client = hold[hold["client_id"] == client_id]
    if client.empty:
        raise SystemExit(f"No holdings found for {client_id} in data/holdings.csv")
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
    url = NEWS_URL + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if isinstance(payload, dict) and "error" in payload:
        code = payload["error"].get("code", "unknown")
        message = payload["error"].get("message", "")
        raise RuntimeError(f"Marketaux API error {code}: {message}")
    return payload.get("data", []) if isinstance(payload, dict) else []


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client_id", nargs="?", default=DEFAULT_CLIENT)
    parser.add_argument("--days", type=int, default=7, help="look-back window in days")
    parser.add_argument("--limit", type=int, default=5, help="max articles per sector")
    parser.add_argument("--language", default="en")
    parser.add_argument("--out", default=None, help="write combined JSON to this file")
    parser.add_argument("--no-sleep", action="store_true", help="disable rate-limit sleep")
    args = parser.parse_args()

    key = api_key()
    exposure = held_sectors(args.client_id)
    queries = queries_for(exposure)
    if not queries:
        raise SystemExit("No queryable (industry) sectors found for this client.")

    published_after = (datetime.now(UTC) - timedelta(days=args.days)).strftime("%Y-%m-%dT%H:%M:%S")
    results = {
        "client_id": args.client_id,
        "fetched_utc": datetime.now(UTC).isoformat(),
        "days": args.days,
        "sectors": [],
    }

    print(f"Fetching news for {args.client_id} sectors: " + ", ".join(q["sector"] for q in queries))
    for query in queries:
        params = {
            "api_token": key,
            "language": args.language,
            "group_similar": "true",
            "published_after": published_after,
            "limit": str(args.limit),
        }
        params[query["kind"]] = query["value"]
        try:
            articles = fetch_news(key, params)
        except urllib.error.HTTPError as exc:
            print(f"  {query['sector']}: HTTP {exc.code}")
            continue
        except RuntimeError as exc:
            print(f"  {query['sector']}: {exc}")
            continue
        entries = [
            {
                "uuid": a.get("uuid"),
                "title": a.get("title"),
                "url": a.get("url"),
                "source": a.get("source"),
                "published_at": a.get("published_at"),
                "snippet": (a.get("snippet") or "")[:300],
                "entities": [
                    {
                        "symbol": e.get("symbol"),
                        "name": e.get("name"),
                        "industry": e.get("industry"),
                    }
                    for e in (a.get("entities") or [])
                ],
            }
            for a in articles
        ]
        results["sectors"].append(
            {
                "sector": query["sector"],
                "market_value_usd": query["market_value_usd"],
                "query": {query["kind"]: query["value"]},
                "articles": entries,
            }
        )
        print(f"  {query['sector']} ({query['value']}): {len(entries)} article(s)")
        if not args.no_sleep:
            time.sleep(1.0)

    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"wrote {args.out}")
    else:
        print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
