"""Generate censored client-context Obsidian notes from the structured data.

Each note is the RM/LLM-facing summary for one client. It deliberately
contains NO client name and NO actual age:

* profile fields come from ``clients_censored.csv`` (which carries ``age_range``
  and drops ``client_name``),
* identity (name/age -> name lookup) is handled separately by the dashboard
  from ``clients_uncensored.csv`` / ``clients.csv`` and never enters these notes.

``client_id`` is the only identifier in a note.

The dashboard does NOT read these markdown files for numbers. It reads the same
structured sources this generator consumes. These notes are a regenerable,
LLM-ready projection of that structured data -- a build output, not a separate,
independently-maintained source of truth.

Usage
-----
    python scripts/generate_client_notes.py            # write all clients
    python scripts/generate_client_notes.py CL-0001    # write one client
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
VAULT = ROOT / "obsidian_vault" / "Clients"

SNAPSHOT_COLS = ["aum_2025-12-31", "aum_2026-02-27", "aum_2026-03-31",
                 "aum_2026-06-30", "aum_2026-08-26"]

THEME_LEXICON = {
    "energy": ["energy", "oil", "lng", "shipping", "transport", "gulf", "coal", "gas", "bunker"],
    "gold": ["gold", "precious metal", "inflation hedge"],
    "technology": ["technology", "information technology", "growth equity"],
    "rates": ["duration", "fixed income", "bond", "yield", "rate"],
    "private credit": ["private credit", "semi-liquid", "redemption", "gate"],
}

# Generic/descriptive words that can appear in entity names or objective text but do
# not, on their own, identify a person. Never redacted so prose/entity text is not garbled.
COMMON_WORDS = {
    "family", "office", "enterprises", "enterprise", "group", "holdings", "holding",
    "foundation", "industries", "company", "companies", "limited", "ltd", "energy",
    "international", "capital", "partners", "association", "and", "of", "the",
    "global", "asia", "south", "east", "north", "west", "trading", "venture", "fund",
}

# Blank interpretation brief appended to every note. When the note is handed to a
# model together with the latest news/event, the model fills these fields for THIS
# client. The evidence gate in blank 2 is a hard guardrail: if the news touches
# nothing in the note the model must say so and stop rather than invent exposure.
INTERPRETATION_TEMPLATE = """\
---
analysis: interpretation-brief
status: blank
---

## Interpretation brief — <insert news snapshot / controlled event + date>

### 1. News (what changed)
_1-2 lines: the supplied news/event; note whether it is a controlled event_log row._

### 2. Does this touch the client? (evidence-gated)
_For each affected line name it and quote the note section that exposes it. If the
supplied news touches nothing in this note, write "No touch" and STOP - do not
invent client exposure._
- Affected holdings / exposures:
- Contact surface (price / collateral-LTV / currency / liquidity / income):

### 3. Direction & mechanism
_Per affected item: which way it moves and why, limited to the contact surface above._

### 4. Client lens
- Client's / RM-note stated view (fact): _cite the RM-note line_
- Observed tension versus this news (inference - label it): _where the news moves
  the portfolio away from objectives or deepens a single-name / concentration bet_

### 5. Committed money & facilities
_Effect on dated planned cash needs (amount/date) and facility headroom/LTV vs the
margin-call trigger - or "no dated impact identified"._

### 6. Severity & why now (for THIS client)
_Low / Medium / High / Urgent + a one-line "because" tied to items 2-5._

### 7. What we do not yet know / to verify
_Genuine gaps only; never fill with guesses._

### 8. Suggested RM opener (1-3 sentences)
_One question to open the conversation; a prompt to discuss, not a directive to buy_
_or sell. The RM remains accountable for any action._

### Evidence trail
_Note section + source ids (e.g. RM note N-001, holdings 2026-08-26, cash need
CN-001). List assumptions and flag "known vs estimated"._
"""


def identity_map(data_dir: Path) -> dict[str, tuple[str, float | None]]:
    """client_id -> (display name, age); read ONLY to redact identities out of free text.

    Never emitted into a note; used solely so neither the client's name/surname nor
    their actual age can leak back in through RM-note prose.
    """
    unc = pd.read_csv(data_dir / "clients_uncensored.csv")  # carries name + age
    return {row.client_id: (row.client_name, row.age) for row in unc.itertuples()}


def _ident_tokens(name: str) -> list[str]:
    toks = [t for t in re.split(r"[\s\-]+", name) if len(t) > 1]
    return [t for t in toks if t.lower() not in COMMON_WORDS]


def redact_identity(text: str, name: str, age: float | None = None) -> str:
    """Remove identifying name/surname and actual-age statements from free text.

    Name tokens that are not common English words are replaced with a neutral
    placeholder, so "Mrs Voss-Brenner" becomes "Mrs [redacted]-[redacted]".

    The actual age is redacted ONLY when it is phrased as the person's age (e.g.
    "Client is 78", "aged 71", "78 years old") -- never as a bare number -- so
    financial figures, percentages and event/transaction dates are left intact.
    """
    out = text
    for tok in sorted(_ident_tokens(name), key=len, reverse=True):
        out = re.sub(rf"\b{re.escape(tok)}\b", "[redacted]", out, flags=re.IGNORECASE)
    if age is not None and not pd.isna(age):
        a = int(age)
        out = re.sub(rf"(?i)\b(?:is|was|age(?:d)?\s+of|now|turning)\s+{a}\b",
                     "[redacted age]", out)
        out = re.sub(rf"(?i)\b{a}(?=\s+(?:years?\s+)?old\b)", "[redacted age]", out)
    return out


def load(data_dir: Path) -> dict[str, pd.DataFrame]:
    names = ["clients_censored", "portfolios", "holdings", "instruments",
             "mandates", "transactions", "credit_facilities", "commitments",
             "planned_cash_needs", "event_log"]
    tables = {n: pd.read_csv(data_dir / f"{n}.csv") for n in names}
    tables["rm_notes"] = json.loads((data_dir / "rm_notes.json").read_text(encoding="utf-8"))
    return tables


def fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, (float, int)):
        if isinstance(v, float) and pd.isna(v):
            return ""
        return f"{float(v):_.0f}".replace("_", ",")
    return str(v)


def latest_position_lines(hold: pd.DataFrame, pf_order: list[str],
                          pf_name_map: dict[str, str]) -> list[str]:
    """Human lines for the client's latest-snapshot positions by portfolio."""
    latest = hold[hold.snapshot_date == hold.snapshot_date.max()]
    lines: list[str] = []
    for pid in pf_order:
        block = latest[latest.portfolio_id == pid].sort_values("weight_pct", ascending=False)
        if block.empty:
            continue
        lines.append(f"- **{pid} — {pf_name_map[pid]}**")
        for _, r in block.iterrows():
            line = (f"  - {r['instrument_name']} — {r['weight_pct']:.1f}% · "
                    f"{r['liquidity_tier']}")
            if pd.notna(r.get("underlying_reference")) and str(r["underlying_reference"]).strip():
                line += f"  \u2192 underlying: {r['underlying_reference']}"
            lines.append(line)
    return lines


def build_note(tables: dict[str, pd.DataFrame], client_id: str, data_dir: Path,
               identity: tuple[str, float | None] | None = None) -> str:
    prof = tables["clients_censored"]
    prow = prof[prof.client_id == client_id]
    if prow.empty:
        raise ValueError(f"{client_id} not found in data/clients_censored.csv")
    p = prow.iloc[0]

    pf = tables["portfolios"]
    pfs = pf[pf.client_id == client_id].sort_values("portfolio_id")
    pf_order = pfs.portfolio_id.tolist()
    pf_name_map = dict(zip(pfs.portfolio_id, pfs.portfolio_name))

    hold = tables["holdings"][tables["holdings"].client_id == client_id].copy()
    # enrich holdings with instrument look-through where available
    instr = tables["instruments"]
    if not hold.empty and "instrument_id" in hold:
        hold = hold.merge(
            instr[["instrument_id", "underlying_reference"]], on="instrument_id", how="left"
        )

    cash = tables["planned_cash_needs"]
    cash_rows = cash[cash.client_id == client_id]
    fac = tables["credit_facilities"]
    fac_rows = fac[fac.client_id == client_id]
    commits = tables["commitments"]
    comm_rows = commits[commits.client_id == client_id]
    tx_all = tables["transactions"]
    tx_rows = tx_all[tx_all.client_id == client_id]
    notes = [n for n in tables["rm_notes"] if n["client_id"] == client_id]

    # allocation by asset class at latest snapshot (aggregated across portfolios)
    latest = hold[hold.snapshot_date == hold.snapshot_date.max()]
    alloc = (latest.groupby("asset_class", as_index=False).market_value_usd.sum()
             if not latest.empty else pd.DataFrame())

    # relevant events: theme overlap between event text and the client's exposure text
    exposure = " ".join(latest["instrument_name"].fillna("").astype(str)) + " " + p.objectives
    the_exposure = {t for t, ws in THEME_LEXICON.items() if any(w in exposure.lower() for w in ws)}
    events_rows = []
    for _, e in tables["event_log"].iterrows():
        et = f"{e.description} {e.primary_transmission}".lower()
        overlap = sorted(the_exposure & {t for t, ws in THEME_LEXICON.items() if any(w in et for w in ws)})
        if overlap:
            events_rows.append((e.event_date, e.severity, e.description, overlap))

    aum_usd = f"{p.total_aum_usd / 1e6:.1f}m"
    mandate_codes = pfs.mandate_code.unique()

    md = [
        "---",
        "type: client-context",
        f"client_id: {client_id}",
        f"age_range: {p.age_range}",
        "visibility: censored",
        "---",
        "",
        f"# {client_id}",
        "",
        "Censored RM/client context. Does **not** contain the client name or actual age. "
        "The dashboard resolves identity separately by `client_id`. Structured source of "
        "truth: `data/*.csv` and `data/rm_notes.json`.",
        "",
    ]

    md.append("## Profile (censored)")
    md.append(f"- **AUM:** USD {aum_usd} · **Base ccy:** {p.base_currency} · {p.wealth_band}")
    md.append(f"- **Risk:** {p.risk_profile} (score {p.risk_tolerance_score}/10) · "
              f"horizon {p.investment_horizon_years:.0f}y · liquidity {p.liquidity_needs}")
    md.append(f"- **Life stage:** {p.life_stage}")
    md.append(f"- **Source of wealth:** {p.source_of_wealth}")
    md.append(f"- **Tax domicile:** {p.tax_domicile} · residence {p.country_of_residence}")
    md.append(f"- **Objectives:** {p.objectives}")
    md.append("")

    md.append("## Portfolios and AUM by snapshot")
    for _, r in pfs.iterrows():
        aum_hist = ", ".join(f"{c.split('_')[-1]}: {fmt(r[c])}" for c in SNAPSHOT_COLS)
        md.append(
            f"- **{r.portfolio_id}** {r.portfolio_name} — {r.service_model} · {r.base_currency} · "
            f"mandate {r.mandate_code} · current USD {fmt(r.aum_usd_current)}"
        )
        md.append(f"  - AUM ({r.base_currency}): {aum_hist}")
    md.append("")

    md.append("## Mandates in scope")
    m = tables["mandates"]
    mb = m[m.mandate_code.isin(mandate_codes)]
    for code in mandate_codes:
        sub = mb[mb.mandate_code == code]
        if not sub.empty:
            notes_txt = sub.mandate_notes.dropna().unique()
            md.append(f"- **{code} — {sub.mandate_name.iloc[0]}**"
                      + (f": {notes_txt[0]}" if len(notes_txt) else ""))
    md.append("")

    if not latest.empty:
        md.append("## Latest holdings (by portfolio, weighted)")
        md.extend(latest_position_lines(hold, pf_order, pf_name_map))
        md.append("")
        md.append("### Allocation by asset class (latest, USD)")
        for _, r in alloc.sort_values("market_value_usd", ascending=False).iterrows():
            md.append(f"- {r.asset_class}: USD {fmt(r.market_value_usd)}")
        md.append("")

    # look-through concentration flag for structured notes referencing a single name
    sp = latest[latest.asset_class == "Structured Products"] if not latest.empty else latest
    if not sp.empty:
        md.append("### Look-through: structured-product underlyings")
        for _, r in sp.iterrows():
            if pd.notna(r.get("underlying_reference")):
                md.append(f"- {r.instrument_name} → `{r.underlying_reference}` "
                          f"(weight {r.weight_pct:.1f}%)")
        md.append("")

    if len(cash_rows):
        md.append("## Planned cash needs")
        for _, r in cash_rows.iterrows():
            md.append(f"- **{r.description}** — {fmt(r.amount)} {r.currency} · "
                      f"{r.due_from}→{r.due_to} · {r.recurrence} · {r.certainty}")
        md.append("")

    if len(comm_rows):
        md.append("## Private-market commitments")
        for _, r in comm_rows.iterrows():
            md.append(f"- {r.fund_name}: uncalled {fmt(r.uncalled)} {r.currency} "
                      f"({r.expected_call_window})")
        md.append("")

    if len(fac_rows):
        md.append("## Credit facilities")
        for _, r in fac_rows.iterrows():
            md.append(f"- **{r.facility_id}** {r.facility_type} ({r.facility_ccy}) — "
                      f"limit {fmt(r.credit_limit)}, margin-call LTV {r.margin_call_ltv_pct:.0f}%")
        md.append("")

    if len(tx_rows):
        md.append("## Transaction activity (censored)")
        md.append("### By type · count / net amount")
        summary = tx_rows.groupby(["transaction_type", "currency"], as_index=False).agg(
            n_txn=("amount", "size"), net_amt=("amount", "sum")
        ).sort_values(["transaction_type", "currency"])
        for _, r in summary.iterrows():
            md.append(f"- {r.transaction_type} ({r.currency}): "
                      f"{int(r.n_txn)} × net {fmt(r.net_amt)}")
        # client-directed / non-routine events worth surfacing (not routine dividends/fees)
        notable = set([
            "Structured Product Subscription", "Facility Drawdown", "Capital Call",
            "Withdrawal", "Redemption Request", "Buy", "Transfer In",
        ])
        sel = tx_rows[tx_rows.transaction_type.isin(notable)].sort_values(
            "trade_date", ascending=False
        )
        if len(sel):
            md.append("### Non-routine / client-directed activity")
            for _, r in sel.iterrows():
                inst = r.instrument_name if pd.notna(r.instrument_name) else r.portfolio_id
                n = r.narrative if pd.notna(r.narrative) else ""
                amt = f"{fmt(r.amount)} {r.currency}" if pd.notna(r.amount) else ""
                md.append(f"- *{r.trade_date}* **{r.transaction_type}** — {inst} · {amt}"
                          + (f" — {n}" if n else ""))
        md.append("")

    if notes:
        md.append("## RM notes")
        for n in sorted(notes, key=lambda x: x["note_date"]):
            identity_name, identity_age = identity if identity else ("", None)
            body = redact_identity(n["note"], identity_name, identity_age)
            md.append(f"- *{n['note_date']} · {n['channel']}*: {body}")
        md.append("")

    if events_rows:
        md.append("## Relevant controlled events (theme match)")
        for date_, sev, desc, themes in events_rows:
            md.append(f"- {date_} · {sev} · {desc}  `[{', '.join(themes)}]`")
        md.append("")

    md.append("---")
    md.append("*Generated from structured data. Update source files, then rerun: "
              f"`python scripts/generate_client_notes.py {client_id}`.*")
    md.append("")
    md.append(INTERPRETATION_TEMPLATE.rstrip())
    return "\n".join(md)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("client_id", nargs="?", default=None,
                        help="Client to write (default: all clients in clients_censored.csv)")
    args = parser.parse_args()

    tables = load(DATA)
    idents = identity_map(DATA)
    clients = tables["clients_censored"].client_id.tolist()
    targets = [args.client_id] if args.client_id else clients
    VAULT.mkdir(parents=True, exist_ok=True)

    for cid in targets:
        note = build_note(tables, cid, DATA, identity=idents.get(cid, ("", None)))
        out = VAULT / f"{cid}.md"
        out.write_text(note + "\n", encoding="utf-8")
        print(f"wrote {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
