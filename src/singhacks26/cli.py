"""Terminal fallback for the governed RM workbench."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .intelligence import (
    AS_OF,
    attention_queue,
    attribute_change,
    integrity_report,
    portfolio_mandate_review,
)

ROOT = Path(__file__).parents[2]
DATA = ROOT / "data"


def load_data() -> dict[str, Any]:
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
    data = {name: pd.read_csv(DATA / f"{name}.csv") for name in names}
    data["rm_notes"] = json.loads((DATA / "rm_notes.json").read_text(encoding="utf-8"))
    return data


def client_payload(data: dict[str, Any], client_id: str) -> dict[str, Any]:
    clients = data["clients"].loc[data["clients"].client_id == client_id]
    if clients.empty:
        raise ValueError(f"Unknown client_id: {client_id}")
    client = clients.iloc[0]
    attention = attention_queue(data).loc[lambda frame: frame.client_id == client_id].iloc[0]
    return {
        "schema_version": "aurum-casefile/1.0",
        "as_of": AS_OF,
        "client": {
            "client_id": client.client_id,
            "client_name": client.client_name,
            "life_stage": client.life_stage,
            "risk_profile": client.risk_profile,
            "objectives": client.objectives,
            "tax_domicile": client.tax_domicile,
        },
        "attention": attention.to_dict(),
        "attribution": attribute_change(data, client_id),
        "mandate_review": portfolio_mandate_review(data, client_id).to_dict(orient="records"),
        "rm_notes": [note for note in data["rm_notes"] if note.get("client_id") == client_id],
        "integrity_issues": [
            issue
            for issue in integrity_report(data)
            if client_id in issue.get("affected_clients", [])
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="RM Workbench terminal fallback")
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("book", help="Print the transparent 20-client ranking")
    client_command = subcommands.add_parser("client", help="Print one governed casefile")
    client_command.add_argument("client_id")
    subcommands.add_parser("verify", help="Print configured source-integrity findings")
    fixtures = subcommands.add_parser("fixtures", help="Freeze the three focus casefiles")
    fixtures.add_argument("--output", type=Path, default=ROOT / "fixtures")
    args = parser.parse_args()
    data = load_data()

    if args.command == "book":
        print(attention_queue(data).to_json(orient="records", indent=2))
    elif args.command == "client":
        print(json.dumps(client_payload(data, args.client_id), indent=2, default=str))
    elif args.command == "verify":
        print(json.dumps(integrity_report(data), indent=2, default=str))
    else:
        args.output.mkdir(parents=True, exist_ok=True)
        for client_id in ["CL-0012", "CL-0014", "CL-0003"]:
            target = args.output / f"client_{client_id}.json"
            target.write_text(
                json.dumps(client_payload(data, client_id), indent=2, default=str),
                encoding="utf-8",
            )
            print(target)


if __name__ == "__main__":
    main()
