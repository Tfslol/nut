"""Deterministic evidence resolution for RM review leads.

The alignment and recommendation features cite evidence as compact IDs such as
``clients.csv:CL-0003``, ``holdings.csv:2026-08-26``, ``event_log.csv:2026-03-04``
or ``note:Profile``. This module resolves those IDs back to the physical source
rows -- the actual 1-based line number in the CSV file -- so the dashboard can
show an RM exactly which line supports a conflict or a draft.

CSV line convention
-------------------
Every CSV under ``data/`` has a single header row on line 1, so a data row that
pandas reads at index ``i`` lives on physical file line ``i + 2``. The lookup
functions below always run against the original loaded frame, never a filtered
copy, so the computed line numbers match the file on disk.

Nothing here calls a model, the network or ``event_log.csv`` writers. It is a
pure, display-side mapping used to render the mermaid evidence trail.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

CSV_HEADER_LINES = 1  # data rows begin on line 2


@dataclass
class Source:
    """One resolved piece of evidence (a CSV row, a note section, or a news item)."""

    evidence_id: str
    kind: str  # csv | note | news | json | unknown
    file_name: str
    key: str = ""
    line_numbers: list[int] = field(default_factory=list)
    caption: str = ""

    def lines_text(self) -> str:
        if self.line_numbers:
            return "L" + ", L".join(str(number) for number in self.line_numbers)
        return ""


def _physical_lines(frame: pd.DataFrame, mask: pd.Series) -> list[int]:
    """Return 1-based CSV file lines for the rows matching ``mask``.

    ``frame`` must be the original loaded table (RangeIndex aligned to file rows)
    so that ``index + 2`` equals the physical line on disk.
    """
    return sorted({int(index) + CSV_HEADER_LINES + 1 for index in frame.index[mask]})


def _split(evidence_id: str) -> tuple[str, str]:
    """Split ``file:key`` keeping the whole id for prefix forms (note:, news:)."""
    if evidence_id.startswith(("note:", "news:")):
        prefix, _, rest = evidence_id.partition(":")
        return prefix, rest
    if ":" in evidence_id:
        file_name, _, key = evidence_id.partition(":")
        return file_name, key
    return evidence_id, ""


def _frame(data: dict[str, Any], key: str) -> pd.DataFrame:
    data_key = key[:-4] if key.endswith(".csv") else key
    frame = data.get(data_key)
    return frame if isinstance(frame, pd.DataFrame) else pd.DataFrame()


def _client_frame(data: dict[str, Any], client_id: str, file_name: str) -> pd.DataFrame:
    frame = _frame(data, file_name)
    if frame.empty or "client_id" not in frame:
        return frame
    return frame.loc[frame["client_id"].astype(str) == str(client_id)]


def _latest_snapshot(frame: pd.DataFrame) -> str:
    if frame.empty or "snapshot_date" not in frame:
        return ""
    return str(frame["snapshot_date"].astype(str).max())


def _events_for_client(
    data: dict[str, Any], client_id: str, vault_text: str | None = None
) -> list[int]:
    """Physical lines of the controlled event_log rows matched to this client.

    Uses the same theme lexicon and text sources as the alignment engine so the
    resolved line numbers agree with what the LLM was allowed to cite.
    """
    from singhacks26.alignment import THEME_LEXICON

    event_log = _frame(data, "event_log")
    if event_log.empty:
        return []
    holdings = _frame(data, "holdings")
    positions = holdings.loc[holdings["client_id"].astype(str) == str(client_id)]
    position_text = " ".join(
        positions[
            [
                column
                for column in ["asset_class", "sub_asset_class", "sector", "region"]
                if column in positions
            ]
        ]
        .fillna("")
        .astype(str)
        .agg(" ".join, axis=1)
    )
    client = _client_frame(data, client_id, "clients")
    client_row = client.iloc[0] if not client.empty else pd.Series(dtype=object)
    notes = data.get("rm_notes", []) if isinstance(data.get("rm_notes"), list) else []
    note_text = " ".join(
        str(note.get("note", "")) for note in notes if note.get("client_id") == client_id
    )
    themes_of = lambda text: {  # noqa: E731 - local helper matching alignment.py
        theme
        for theme, words in THEME_LEXICON.items()
        if any(word in str(text).lower() for word in words)
    }
    client_themes = themes_of(
        " ".join(
            [
                position_text,
                str(client_row.get("objectives", "")),
                str(client_row.get("source_of_wealth", "")),
                note_text,
            ]
        )
    )
    mask = event_log.apply(
        lambda event: bool(
            client_themes
            & themes_of(f"{event.get('primary_transmission', '')} {event.get('description', '')}")
        ),
        axis=1,
    )
    return _physical_lines(event_log, mask)


def _resolve_csv(data: dict[str, Any], client_id: str, file_name: str, key: str) -> Source:
    frame = _frame(data, file_name)
    if frame.empty:
        return Source(
            f"{file_name}:{key}" if key else file_name, "unknown", file_name, caption="Unavailable"
        )

    if file_name == "clients.csv":
        mask = (
            frame["client_id"].astype(str) == (key or client_id)
            if "client_id" in frame
            else pd.Series(False, index=frame.index)
        )
        return Source(
            f"{file_name}:{key}",
            "csv",
            file_name,
            key=key or client_id,
            line_numbers=_physical_lines(frame, mask),
        )

    if file_name == "portfolios.csv":
        if key:
            mask = frame["portfolio_id"].astype(str) == key
        else:
            mask = frame["client_id"].astype(str) == str(client_id)
        return Source(
            f"{file_name}:{key}" if key else file_name,
            "csv",
            file_name,
            key=key,
            line_numbers=_physical_lines(frame, mask),
        )

    if file_name == "holdings.csv":
        snapshot = key or _latest_snapshot(_client_frame(data, client_id, "holdings"))
        mask = (frame["client_id"].astype(str) == str(client_id)) & (
            frame["snapshot_date"].astype(str) == snapshot
        )
        return Source(
            f"holdings.csv:{snapshot}",
            "csv",
            "holdings.csv",
            key=snapshot,
            line_numbers=_physical_lines(frame, mask),
        )

    if file_name == "instruments.csv":
        if key:
            mask = frame["instrument_id"].astype(str) == key
        else:
            holdings = _client_frame(data, client_id, "holdings")
            latest = _latest_snapshot(holdings)
            held = (
                holdings.loc[holdings["snapshot_date"].astype(str) == latest, "instrument_id"]
                .astype(str)
                .unique()
                .tolist()
            )
            mask = frame["instrument_id"].astype(str).isin(held)
        return Source(
            f"{file_name}:{key}" if key else file_name,
            "csv",
            file_name,
            key=key,
            line_numbers=_physical_lines(frame, mask),
        )

    if file_name == "mandates.csv":
        if key:
            mask = frame["mandate_code"].astype(str) == key
        else:
            portfolios = _client_frame(data, client_id, "portfolios")
            codes = (
                portfolios.loc[portfolios["service_model"] != "Custody", "mandate_code"]
                .astype(str)
                .unique()
                .tolist()
            )
            mask = frame["mandate_code"].astype(str).isin(codes)
        return Source(
            f"{file_name}:{key}" if key else file_name,
            "csv",
            file_name,
            key=key,
            line_numbers=_physical_lines(frame, mask),
        )

    if file_name == "planned_cash_needs.csv":
        mask = (
            frame["need_id"].astype(str) == key
            if key and "need_id" in frame
            else frame["client_id"].astype(str) == str(client_id)
        )
        return Source(
            f"{file_name}:{key}" if key else file_name,
            "csv",
            file_name,
            key=key,
            line_numbers=_physical_lines(frame, mask),
        )

    if file_name == "credit_facilities.csv":
        mask = (
            frame["facility_id"].astype(str) == key
            if key and "facility_id" in frame
            else frame["client_id"].astype(str) == str(client_id)
        )
        return Source(
            f"{file_name}:{key}" if key else file_name,
            "csv",
            file_name,
            key=key,
            line_numbers=_physical_lines(frame, mask),
        )

    if file_name == "commitments.csv":
        mask = (
            frame["commitment_id"].astype(str) == key
            if key and "commitment_id" in frame
            else frame["client_id"].astype(str) == str(client_id)
        )
        return Source(
            f"{file_name}:{key}" if key else file_name,
            "csv",
            file_name,
            key=key,
            line_numbers=_physical_lines(frame, mask),
        )

    if file_name == "transactions.csv":
        mask = (
            frame["client_id"].astype(str) == str(client_id)
            if "client_id" in frame
            else pd.Series(False, index=frame.index)
        )
        return Source(
            f"{file_name}:{key}" if key else file_name,
            "csv",
            file_name,
            key=key,
            line_numbers=_physical_lines(frame, mask),
        )

    if file_name == "event_log.csv":
        if key:
            mask = frame["event_date"].astype(str) == key
            return Source(
                f"event_log.csv:{key}",
                "csv",
                "event_log.csv",
                key=key,
                line_numbers=_physical_lines(frame, mask),
            )
        lines = _events_for_client(data, client_id)
        return Source(
            "event_log.csv",
            "csv",
            "event_log.csv",
            line_numbers=lines,
            caption="Matched controlled events",
        )

    return Source(
        f"{file_name}:{key}" if key else file_name,
        "unknown",
        file_name,
        key=key,
        caption="No row mapping for this file.",
    )


def _resolve_note(
    evidence_id: str,
    heading: str,
    client_id: str,
    vault_dir: Any = None,
) -> Source:
    """Locate a note section's physical line inside the censored vault page."""
    if vault_dir is None:
        return Source(
            evidence_id, "note", "obsidian note", key=heading, caption="Censored Obsidian page"
        )
    path = Path(vault_dir) / "Clients" / f"{client_id}.md"
    if not path.exists():
        return Source(
            evidence_id,
            "note",
            "obsidian note",
            key=heading,
            caption="Censored Obsidian page (missing)",
        )
    lines = path.read_text(encoding="utf-8").splitlines()
    needle = heading.lower()
    matches = []
    for number, line in enumerate(lines, start=1):
        stripped = line.strip().lstrip("#").strip().lower()
        if stripped and (stripped == needle or stripped.startswith(needle)):
            matches.append(number)
    if not matches:
        # the client-id form points at the whole censored note
        matches = [
            number
            for number, line in enumerate(lines, start=1)
            if line.strip().startswith(f"# {client_id}")
        ]
    return Source(evidence_id, "note", path.name, key=heading, line_numbers=matches)


def _resolve_news(evidence_id: str, uuid: str, news_payload: Any) -> Source:
    """Locate a live Marketaux article in the cached news payload (no CSV row)."""
    payload = news_payload or {}
    for entry in payload.get("clients", {}).values():
        for sector in entry.get("sectors", []):
            for article in sector.get("articles", []):
                if article.get("uuid") == uuid:
                    title = article.get("title", "")
                    caption = f"{title} · {article.get('source', '')}"
                    caption += f" · {article.get('published_at', '')}"
                    return Source(
                        evidence_id,
                        "news",
                        "Marketaux live feed",
                        key=uuid,
                        caption=caption.strip(" ·"),
                    )
    return Source(
        evidence_id, "news", "Marketaux live feed", key=uuid, caption="Cached article not found"
    )


def resolve_sources(
    data: dict[str, Any],
    client_id: str,
    evidence_ids: list[str],
    *,
    vault_dir: Any = None,
    news_payload: Any = None,
) -> list[Source]:
    """Resolve each evidence ID to its physical source row(s), de-duplicated."""
    resolved: dict[str, Source] = {}
    for evidence_id in dict.fromkeys(evidence_ids or []):
        evidence_id = str(evidence_id).strip()
        if not evidence_id:
            continue
        file_name, key = _split(evidence_id)
        if file_name == "note":
            source = _resolve_note(evidence_id, key, client_id, vault_dir)
        elif file_name == "news":
            source = _resolve_news(evidence_id, key, news_payload)
        elif file_name.endswith(".csv"):
            source = _resolve_csv(data, client_id, file_name, key)
        else:
            source = Source(
                evidence_id, "unknown", file_name, key=key, caption="No source mapping."
            )
        resolved[evidence_id] = source
    return list(resolved.values())


def sources_frame(sources: list[Source]) -> pd.DataFrame:
    """A plain table of evidence -> file:line(s) for accessibility."""
    rows = [
        {
            "Evidence ID": source.evidence_id,
            "Source file": source.file_name,
            "Row key": source.key or "",
            "Line(s)": source.lines_text(),
            "Note": source.caption,
        }
        for source in sources
    ]
    return pd.DataFrame(rows)


def _mermaid_safe(text: str) -> str:
    """Strip characters that can break a quoted mermaid label."""
    cleaned = re.sub(r'[`"\[\]{}()|]', " ", str(text))
    return re.sub(r"\s+", " ", cleaned).strip()


def mermaid_graph(
    sources: list[Source],
    targets: list[dict[str, Any]],
) -> str:
    """Build a ``flowchart LR`` string mapping evidence rows to RM review leads.

    ``targets`` is a list of ``{"label": ..., "evidence_ids": [...]}``. Evidence
    node labels carry the physical CSV line numbers; an edge is drawn to each
    target that cites that evidence.
    """
    if not targets:
        return ""
    node_by_evidence: dict[str, str] = {}
    for index, source in enumerate(sources):
        node_by_evidence[source.evidence_id] = f"E{index}"

    def source_label(source: Source) -> str:
        label = source.file_name
        if source.key and source.key.lower() not in {source.file_name.lower(), "cl-0000"}:
            label = f"{label} · {source.key}"
        lines = source.lines_text()
        if lines:
            label = f"{label}<br/>{lines}"
        elif source.kind == "news":
            title = _mermaid_safe(source.caption).split(" · ")[0]
            label = f"{label}<br/>{title[:60]}"
        elif source.caption:
            label = f"{label}<br/>{_mermaid_safe(source.caption)[:60]}"
        return _mermaid_safe(label)

    lines = ["flowchart LR"]
    for index, source in enumerate(sources):
        lines.append(f'  E{index}["{source_label(source)}"]')
    for target_index, target in enumerate(targets):
        label = _mermaid_safe(target.get("label", "RM review lead"))
        lines.append(f'  T{target_index}["{label}"]')
    for target_index, target in enumerate(targets):
        for evidence_id in target.get("evidence_ids", []):
            evidence_node = node_by_evidence.get(str(evidence_id))
            if evidence_node:
                lines.append(f"  {evidence_node} -->|cites| T{target_index}")
    return "\n".join(lines)
