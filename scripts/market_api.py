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
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd

from singhacks26.news import (
    DATA,
    DEFAULT_CLIENT,
    fetch_news,
    held_sectors,
    marketaux_api_key,
    normalise_articles,
    queries_for,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client_id", nargs="?", default=DEFAULT_CLIENT)
    parser.add_argument("--days", type=int, default=7, help="look-back window in days")
    parser.add_argument("--limit", type=int, default=5, help="max articles per sector")
    parser.add_argument("--language", default="en")
    parser.add_argument("--out", default=None, help="write combined JSON to this file")
    parser.add_argument("--no-sleep", action="store_true", help="disable rate-limit sleep")
    args = parser.parse_args()

    try:
        key = marketaux_api_key()
        holdings = pd.read_csv(DATA / "holdings.csv")
        exposure = held_sectors(holdings, args.client_id)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc

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
        except Exception as exc:  # network / API failures print per-sector and continue
            print(f"  {query['sector']}: {exc}")
            continue
        entries = normalise_articles(articles, limit=args.limit)
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
