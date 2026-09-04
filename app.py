"""RM Intelligence Workbench — local-first Streamlit prototype."""

import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).parent
DATA = ROOT / "data"
VAULT = ROOT / "obsidian_vault"
SEVERITY = {"Severe": 4, "High": 3, "Medium": 2, "Low": 1}
THEMES = {
    "gold": ["gold", "precious metals", "inflation hedge"],
    "energy": ["energy", "oil", "lng", "shipping", "transport", "gulf"],
    "technology": ["technology", "information technology", "growth equity"],
    "rates": ["duration", "fixed income", "bond", "credit", "yield", "rate"],
    "private credit": ["private credit", "semi-liquid", "redemption", "gate"],
    "real estate": ["real estate", "property"],
}
DEEP_DIVE_INSIGHTS = [
    {
        "client_id": "CL-0012",
        "severity": "Urgent",
        "headline": "Waiting for the bonds to recover is not yet an income plan",
        "context": (
            "Cheung is 71, retired, and now drawing more than USD 1.1m a year as medical "
            "costs rise. He wants to preserve capital for his children."
        ),
        "client_view": (
            "He believes selling now would lock in a loss and would rather wait for the bonds "
            "to come back. His longest bond does not mature until 2045."
        ),
        "why_now": (
            "The event log records delayed Fed easing and a rise in the US 10-year yield to "
            "about 4.71%. That helps explain the loss, but not whether future withdrawals are covered."
        ),
        "action": (
            "Prepare a maturity-and-coupon cash-flow map against living and medical spending. "
            "Discuss liquidity and duration before discussing any sale."
        ),
        "opener": (
            "You are right that selling a bond today can crystallise a loss. The question I want "
            "us to answer is different: which assets will fund your spending while we wait?"
        ),
        "uncertainty": "We still need bond-level cash flows and the latest medical-cost estimate.",
        "evidence": "clients.csv · RM note N-016 · holdings snapshots · events 2026-06-17 and 2026-07-29",
    },
    {
        "client_id": "CL-0002",
        "severity": "High",
        "headline": "A future founder-share sale is carrying today’s collateral risk",
        "context": (
            "Ravi is awaiting a possible Q4 2026 liquidity event, remains strongly bullish on "
            "technology, and wants to diversify only after the sale."
        ),
        "client_view": (
            "He does not want to sell listed technology positions and drew another USD 1.7m "
            "for a pre-IPO investment despite volatile collateral."
        ),
        "why_now": (
            "Technology briefly lost about USD 2tn on 5 June. His facility crossed its 75% "
            "margin-call trigger at the June snapshot before recovering below it by August."
        ),
        "action": (
            "Show the bridge-liquidity dependency, facility headroom and a technology stress case. "
            "Agree monitoring thresholds before considering further borrowing."
        ),
        "opener": (
            "Your long-term technology view has not changed. Let’s make sure the financing can "
            "survive another short-term drawdown without forcing the timing of your decisions."
        ),
        "uncertainty": "The founder-share sale timing and proceeds remain prospective, not committed liquidity.",
        "evidence": "clients.csv · RM notes N-003/N-004 · credit_facilities.csv · event 2026-06-05",
    },
    {
        "client_id": "CL-0014",
        "severity": "High",
        "headline": "The portfolio, borrowing and family business express the same property view",
        "context": (
            "Lau wants exposure to a Hong Kong property recovery and needs HKD 60m for a "
            "Mid-Levels redevelopment by mid-2027."
        ),
        "client_view": (
            "He is confident in the recovery, but was surprised by how little of the portfolio "
            "is genuinely liquid after accumulator settlements and additional borrowing."
        ),
        "why_now": (
            "The urgent issue is not whether the market view is correct. It is that the perpetual, "
            "shares, accumulator, development business and funding need may all depend on it."
        ),
        "action": (
            "Aggregate look-through property exposure, facility headroom and assets sellable by "
            "the funding date. Identify the gap before proposing another yield product."
        ),
        "opener": (
            "Your conviction may prove right. Our job today is to make sure the redevelopment can "
            "still be funded if the recovery takes longer than expected."
        ),
        "uncertainty": "The event log does not contain evidence validating a Hong Kong property recovery.",
        "evidence": "clients.csv · RM notes N-018/N-019 · holdings, instruments, facilities and cash needs",
    },
]

st.set_page_config(page_title="Aurelia | RM Intelligence", page_icon="◈", layout="wide")


@st.cache_data
def load_data():
    names = [
        "clients", "portfolios", "holdings", "instruments", "mandates",
        "transactions", "credit_facilities", "commitments", "planned_cash_needs",
        "market_context", "event_log",
    ]
    result = {name: pd.read_csv(DATA / f"{name}.csv") for name in names}
    result["rm_notes"] = json.loads((DATA / "rm_notes.json").read_text(encoding="utf-8"))
    return result


def client_notes(notes, client_id):
    return sorted(
        (note for note in notes if note["client_id"] == client_id),
        key=lambda note: note["note_date"], reverse=True,
    )


def detect_themes(text):
    clean = text.lower()
    return [theme for theme, words in THEMES.items() if any(word in clean for word in words)]


def client_exposure_text(data, client_id):
    latest = data["holdings"]["snapshot_date"].max()
    positions = data["holdings"].query("client_id == @client_id and snapshot_date == @latest")
    client = data["clients"].loc[data["clients"].client_id == client_id].iloc[0]
    notes = client_notes(data["rm_notes"], client_id)
    position_text = " ".join(
        positions[["instrument_name", "asset_class", "sub_asset_class", "sector", "region"]]
        .fillna("").astype(str).agg(" ".join, axis=1)
    )
    note_text = " ".join(note["note"] for note in notes)
    return f"{position_text} {client.objectives} {client.source_of_wealth} {note_text}"


@st.cache_data
def build_event_impacts(_data):
    rows = []
    for _, event in _data["event_log"].iterrows():
        event_themes = detect_themes(f"{event.primary_transmission} {event.description}")
        for _, client in _data["clients"].iterrows():
            client_themes = detect_themes(client_exposure_text(_data, client.client_id))
            overlap = sorted(set(event_themes) & set(client_themes))
            if overlap:
                rank = SEVERITY.get(event.severity, 0)
                rows.append({
                    "client_id": client.client_id, "client": client.client_name,
                    "event_date": event.event_date, "severity": event.severity,
                    "severity_rank": rank, "description": event.description,
                    "transmission": event.primary_transmission, "themes": overlap,
                    "relevance": min(100, 40 + 15 * len(overlap) + 8 * rank),
                })
    return pd.DataFrame(rows).sort_values(
        ["severity_rank", "relevance", "event_date"], ascending=[False, False, False]
    )


def vault_notes(client_id):
    path = VAULT / "Clients" / f"{client_id}.md"
    if not path.exists():
        return []
    entries = re.findall(
        r"<!-- RM-NOTE -->\s*### (.*?) · (.*?)\n\n(.*?)(?=\n<!-- RM-NOTE -->|\Z)",
        path.read_text(encoding="utf-8"), flags=re.DOTALL,
    )
    return [{"date": date, "category": category, "note": body.strip()} for date, category, body in entries]


def save_vault_note(client_id, client_name, category, note):
    if client_id not in set(data["clients"].client_id) or not note.strip():
        return False
    path = VAULT / "Clients" / f"{client_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            f"---\ntype: client-context\nclient_id: {client_id}\nvisibility: restricted\n---\n\n"
            f"# {client_name}\n\n## RM working notes\n", encoding="utf-8",
        )
    timestamp = datetime.now().astimezone().isoformat(timespec="minutes")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n<!-- RM-NOTE -->\n### {timestamp} · {category}\n\n{note.strip()}\n")
    return True


def market_panel(data):
    market = data["market_context"]
    dates = sorted(market.snapshot_date.unique())
    latest = market[market.snapshot_date == dates[-1]].set_index("series_id")
    previous = market[market.snapshot_date == dates[-2]].set_index("series_id")
    tiles = [
        ("SPX", "S&P 500", "pts"), ("NASDAQ_COMP", "Nasdaq", "pts"),
        ("GOLD_USD_OZ", "Gold", "USD/oz"), ("BRENT_USD_BBL", "Brent", "USD/bbl"),
        ("UST_10Y_PCT", "US 10Y", "%"), ("VIX", "VIX", ""),
    ]
    for column, (series_id, label, unit) in zip(st.columns(6), tiles, strict=True):
        value = latest.loc[series_id, "value"]
        delta = value - previous.loc[series_id, "value"]
        column.metric(label, f"{value:,.2f} {unit}".strip(), f"{delta:+,.2f}")
    st.caption(f"Latest controlled snapshot: {dates[-1]} · change versus {dates[-2]}")


def severity_badge(severity):
    return {"Severe": "🔴", "High": "🟠", "Medium": "🟡", "Low": "🟢"}.get(severity, "⚪")


@st.dialog("RM Notes", width="large")
def notes_bubble(default_client_id):
    ids = data["clients"].client_id.tolist()
    selected_id = st.selectbox(
        "Client", ids, index=ids.index(default_client_id) if default_client_id in ids else 0,
        format_func=lambda client_id: data["clients"].loc[
            data["clients"].client_id == client_id, "client_name"
        ].iloc[0], key="notes_client",
    )
    source_tab, working_tab, add_tab = st.tabs(["Source notes", "RM working notes", "Add note"])
    with source_tab:
        for note in client_notes(data["rm_notes"], selected_id):
            st.markdown(f"**{note['note_date']} · {note['channel']}**")
            st.write(note["note"])
    with working_tab:
        entries = vault_notes(selected_id)
        if not entries:
            st.caption("No working notes saved yet.")
        for entry in reversed(entries):
            st.markdown(f"**{entry['date']} · {entry['category']}**")
            st.write(entry["note"])
    with add_tab:
        category = st.selectbox(
            "Category", ["Meeting preparation", "Client outlook", "Follow-up", "Risk observation"]
        )
        note = st.text_area("Note", height=160, placeholder="Stored locally in the Obsidian vault…")
        if st.button("Save locally", type="primary", width="stretch"):
            name = data["clients"].loc[data["clients"].client_id == selected_id, "client_name"].iloc[0]
            if save_vault_note(selected_id, name, category, note):
                st.success("Saved to the local Obsidian vault.")
                st.rerun()


st.markdown("""
<style>
.stApp {background:radial-gradient(circle at 85% 0%,#132c39 0,#071419 35%,#061014 100%)}
[data-testid="stSidebar"] {background:#081a20;border-right:1px solid #173641}
[data-testid="stMetric"] {background:linear-gradient(145deg,#102932,#0b1d24);border:1px solid #1d414d;padding:14px;border-radius:16px}
div[data-testid="stVerticalBlockBorderWrapper"] {background:#0b1d24;border-color:#1d414d;border-radius:18px}
h1,h2,h3 {letter-spacing:-.025em}.eyebrow{color:#78d6c6;text-transform:uppercase;letter-spacing:.16em;font-size:.72rem;font-weight:700}
.hero{font-size:2.35rem;line-height:1.05;font-weight:750;margin:.3rem 0 .6rem;color:#f4f7f5}.muted{color:#8faab2}
.event-card{padding:18px 20px;margin:10px 0;background:linear-gradient(135deg,#102831,#0a1b21);border:1px solid #1f414c;border-radius:18px}
.event-title{font-size:1.05rem;font-weight:700;color:#eef5f3}.pill{display:inline-block;padding:3px 9px;margin:6px 5px 0 0;border-radius:999px;background:#153641;color:#8ee3d2;font-size:.72rem}
</style>""", unsafe_allow_html=True)

data = load_data()
clients = data["clients"]
impacts = build_event_impacts(data)
default_client = st.session_state.get("active_client", clients.client_id.iloc[0])

with st.sidebar:
    st.markdown("### ◈ AURELIA")
    st.caption("RM Intelligence Workbench")
    page = st.radio(
        "Navigation",
        ["RM priorities", "Client deep dive", "Notes library", "Market context", "Methods & governance"],
        label_visibility="collapsed",
    )
    st.divider()
    st.markdown("**Data boundary**")
    st.caption("Client data remains local. External market/news feeds are not connected.")

header_left, header_right = st.columns([0.86, 0.14])
with header_left:
    st.markdown('<div class="eyebrow">Asia desk · Singapore & Hong Kong</div>', unsafe_allow_html=True)
with header_right:
    if st.button("✦ Notes", width="stretch"):
        notes_bubble(default_client)

if page == "RM priorities":
    st.markdown('<div class="hero">Who should Priscilla call—and why?</div>', unsafe_allow_html=True)
    st.markdown(
        '<div class="muted">Prioritised from client circumstances, stated beliefs, portfolio reality and time-sensitive needs. Market events appear only where they change the conversation.</div>',
        unsafe_allow_html=True,
    )
    st.markdown("### Three conversations that matter now")
    for insight in DEEP_DIVE_INSIGHTS:
        client = clients.loc[clients.client_id == insight["client_id"]].iloc[0]
        with st.container(border=True):
            top_left, top_right = st.columns([0.82, 0.18])
            with top_left:
                st.markdown(f'<div class="eyebrow">{insight["severity"]} · {client.client_name} · {insight["client_id"]}</div>', unsafe_allow_html=True)
                st.markdown(f"### {insight['headline']}")
            with top_right:
                st.metric("AUM", f"USD {client.total_aum_usd / 1e6:,.1f}m")
            context_tab, reasoning_tab, conversation_tab, evidence_tab = st.tabs(
                ["Client context", "Why it matters", "Conversation", "Evidence & uncertainty"]
            )
            with context_tab:
                st.markdown("**Background and aspiration**")
                st.write(insight["context"])
                st.markdown("**What the client believes**")
                st.write(insight["client_view"])
            with reasoning_tab:
                st.markdown("**What changed and why it matters now**")
                st.write(insight["why_now"])
                st.markdown("**RM-ready action**")
                st.write(insight["action"])
            with conversation_tab:
                st.markdown("**Suggested opening**")
                st.info(f'“{insight["opener"]}”')
                st.caption("Conversation support only—the RM decides how to frame and act on it.")
            with evidence_tab:
                st.markdown("**Evidence trail**")
                st.code(insight["evidence"], language=None)
                st.markdown("**What we do not yet know**")
                st.warning(insight["uncertainty"])
    st.markdown("### Rest of the book")
    st.caption("All 20 clients remain searchable; deep reasoning is deliberately focused on the three cases above.")
    book = clients[["client_id", "client_name", "life_stage", "risk_profile", "liquidity_needs"]].copy()
    st.dataframe(book, hide_index=True, width="stretch")

elif page == "Market context":
    st.markdown('<div class="hero">What changed—and who needs to know?</div>', unsafe_allow_html=True)
    st.markdown('<div class="muted">Every signal is linked to a client exposure, objective or RM note.</div>', unsafe_allow_html=True)
    st.markdown("### Market pulse")
    market_panel(data)
    st.markdown("### Exposure-linked intelligence")
    filter_left, filter_right = st.columns([0.35, 0.65])
    with filter_left:
        severity_filter = st.multiselect("Severity", ["Severe", "High", "Medium", "Low"], default=["Severe", "High"])
    with filter_right:
        theme_filter = st.multiselect("Theme", sorted(THEMES))
    filtered = impacts[impacts.severity.isin(severity_filter)] if severity_filter else impacts
    if theme_filter:
        filtered = filtered[filtered.themes.apply(lambda values: bool(set(values) & set(theme_filter)))]
    for event_date, group in filtered.groupby("event_date", sort=False):
        event = group.iloc[0]
        affected = group.client_id.nunique()
        names = ", ".join(group.client.head(4)) + (f" +{affected - 4}" if affected > 4 else "")
        pills = "".join(f'<span class="pill">{theme}</span>' for theme in event.themes)
        st.markdown(
            f'<div class="event-card"><div class="eyebrow">{severity_badge(event.severity)} {event.severity} · {event_date} · {affected} clients</div>'
            f'<div class="event-title">{event.description}</div>{pills}'
            f'<div class="muted" style="margin-top:9px">Most exposed: {names}</div></div>', unsafe_allow_html=True,
        )
        with st.expander("View client relevance and evidence"):
            st.caption(f"Transmission: {event.transmission}")
            st.dataframe(group[["client_id", "client", "relevance", "themes"]], hide_index=True, width="stretch")
            st.caption("Skill: event-to-exposure mapping · RM review required")

elif page == "Client deep dive":
    selected_id = st.selectbox(
        "Client", clients.client_id.tolist(),
        format_func=lambda client_id: clients.loc[clients.client_id == client_id, "client_name"].iloc[0],
    )
    st.session_state.active_client = selected_id
    client = clients.loc[clients.client_id == selected_id].iloc[0]
    st.markdown(f'<div class="hero">{client.client_name}</div>', unsafe_allow_html=True)
    metrics = st.columns(5)
    metrics[0].metric("AUM", f"USD {client.total_aum_usd / 1e6:,.1f}m")
    metrics[1].metric("Risk", client.risk_profile)
    metrics[2].metric("Liquidity", client.liquidity_needs)
    metrics[3].metric("Horizon", f"{client.investment_horizon_years:g}y")
    metrics[4].metric("Relevant events", len(impacts[impacts.client_id == selected_id]))
    st.markdown("### Client intent")
    st.write(client.objectives)
    holdings_tab, events_tab, conversation_tab = st.tabs(["Portfolio exposure", "Events & outlook", "Conversation brief"])
    latest_date = data["holdings"].snapshot_date.max()
    positions = data["holdings"].query("client_id == @selected_id and snapshot_date == @latest_date")
    with holdings_tab:
        left, right = st.columns(2)
        with left:
            allocation = positions.groupby("asset_class").market_value_usd.sum().sort_values()
            st.markdown("**Allocation by asset class**")
            st.bar_chart(allocation, horizontal=True)
        with right:
            st.markdown("**Largest positions**")
            top = positions.nlargest(8, "market_value_usd")[["instrument_name", "asset_class", "weight_pct", "liquidity_tier"]]
            st.dataframe(top, hide_index=True, width="stretch")
    with events_tab:
        relevant = impacts[impacts.client_id == selected_id].head(10)
        st.dataframe(relevant[["event_date", "severity", "description", "themes", "relevance"]], hide_index=True, width="stretch")
    with conversation_tab:
        notes = client_notes(data["rm_notes"], selected_id)
        st.markdown("**What the client/RM has said**")
        st.write(notes[0]["note"] if notes else "No RM note available.")
        st.markdown("**Questions for the next conversation**")
        st.markdown("- Has the client's outlook or cash requirement changed?\n- Is the exposure intentional and within mandate?\n- What downside would cause the client to reconsider?\n- Which assumptions need specialist validation?")
        st.warning("Conversation support only. Any action requires suitability and RM review.")

elif page == "Notes library":
    st.markdown('<div class="hero">Notes, without the noise.</div>', unsafe_allow_html=True)
    query = st.text_input("Search all source notes", placeholder="Try: retirement, gold, liquidity, technology…")
    matches = []
    for note in data["rm_notes"]:
        name = clients.loc[clients.client_id == note["client_id"], "client_name"].iloc[0]
        if not query or query.lower() in f"{name} {note['note']}".lower():
            matches.append((note, name))
    st.caption(f"{len(matches)} source notes found")
    for note, name in matches:
        with st.container(border=True):
            st.markdown(f"**{name}** · {note['note_date']} · {note['channel']}")
            st.write(note["note"])

else:
    st.markdown('<div class="hero">Methods & governance</div>', unsafe_allow_html=True)
    st.write("The workbench uses bounded analysis skills. Every insight must identify its evidence and require human review.")
    skills_path = ROOT / "skills.md"
    if skills_path.exists():
        st.markdown(skills_path.read_text(encoding="utf-8"))
    st.info("Live-provider adapters receive market themes or synthetic exposure IDs only—never names, raw RM notes, tax data or account-level holdings.")

st.divider()
st.caption("Controlled sources: repository data and local Obsidian vault · No external client-data transfer · Not investment advice")
