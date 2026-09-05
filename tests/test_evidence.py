"""Offline tests for the deterministic evidence resolver and mermaid builder."""

import json
from pathlib import Path

import pandas as pd
import pytest

from singhacks26.evidence import (
    mermaid_graph,
    resolve_sources,
    sources_frame,
)

ROOT = Path(__file__).parents[1]
DATA = ROOT / "data"
VAULT = ROOT / "obsidian_vault"


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


def _expected_line(table: str, column: str, value) -> int:
    """Physical CSV line: header row 1 + position of the matching data row."""
    frame = pd.read_csv(DATA / f"{table}.csv")
    return int(frame.index[frame[column].astype(str) == str(value)][0]) + 2


def test_resolves_client_row_line(data):
    sources = resolve_sources(data, "CL-0003", ["clients.csv:CL-0003"])
    assert sources[0].kind == "csv"
    assert sources[0].line_numbers == [_expected_line("clients", "client_id", "CL-0003")]


def test_resolves_event_row_line(data):
    sources = resolve_sources(data, "CL-0003", ["event_log.csv:2026-03-04"])
    assert sources[0].line_numbers == [_expected_line("event_log", "event_date", "2026-03-04")]


def test_resolves_cash_need_and_facility_lines(data):
    sources = resolve_sources(
        data, "CL-0003", ["planned_cash_needs.csv:CN-004", "credit_facilities.csv:CF-0005"]
    )
    by_id = {source.evidence_id: source for source in sources}
    assert by_id["planned_cash_needs.csv:CN-004"].line_numbers == [
        _expected_line("planned_cash_needs", "need_id", "CN-004")
    ]
    assert by_id["credit_facilities.csv:CF-0005"].line_numbers == [
        _expected_line("credit_facilities", "facility_id", "CF-0005")
    ]


def test_holdings_snapshot_resolves_to_client_position_lines(data):
    sources = resolve_sources(data, "CL-0003", ["holdings.csv:2026-08-26"])
    frame = pd.read_csv(DATA / "holdings.csv")
    mask = (frame.client_id == "CL-0003") & (frame.snapshot_date == "2026-08-26")
    expected = sorted(int(index) + 2 for index in frame.index[mask])
    assert sources[0].line_numbers == expected
    assert len(expected) > 1


def test_note_section_resolves_to_markdown_line(data):
    sources = resolve_sources(data, "CL-0003", ["note:Profile"], vault_dir=VAULT)
    source = sources[0]
    assert source.kind == "note"
    assert source.line_numbers
    assert source.file_name == "CL-0003.md"


def test_news_uuid_resolves_without_csv_line():
    payload = {
        "clients": {
            "CL-0003": {
                "sectors": [
                    {
                        "articles": [
                            {
                                "uuid": "abc-123",
                                "title": "Energy headline",
                                "source": "s",
                                "published_at": "t",
                            }
                        ]
                    }
                ]
            }
        }
    }
    sources = resolve_sources({}, "CL-0003", ["news:abc-123"], news_payload=payload)
    assert sources[0].kind == "news"
    assert sources[0].line_numbers == []
    assert "Energy headline" in sources[0].caption


def test_unknown_evidence_is_marked_not_crash(data):
    sources = resolve_sources(data, "CL-0003", ["invented:source"])
    assert sources[0].kind == "unknown"


def test_sources_frame_is_plain_table(data):
    sources = resolve_sources(data, "CL-0003", ["clients.csv:CL-0003"])
    frame = sources_frame(sources)
    assert "Line(s)" in frame.columns
    assert frame.iloc[0]["Line(s)"] == f"L{_expected_line('clients', 'client_id', 'CL-0003')}"


def test_mermaid_graph_renders_edges_with_line_labels(data):
    evidence_ids = ["clients.csv:CL-0003", "event_log.csv:2026-03-04"]
    sources = resolve_sources(data, "CL-0003", evidence_ids)
    graph = mermaid_graph(
        sources,
        [
            {
                "label": "High · event: controlled event review",
                "evidence_ids": evidence_ids,
            }
        ],
    )
    assert graph.startswith("flowchart LR")
    assert "-->|cites| T0" in graph
    assert "L" in graph


def test_mermaid_graph_empty_without_targets():
    assert mermaid_graph([], []) == ""
