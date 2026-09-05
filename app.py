"""RM Intelligence Workbench — local-first Streamlit prototype."""

import json
import re
from calendar import month_name, monthcalendar
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

from singhacks26.ai_brief import ai_is_configured, draft_ai_brief
from singhacks26.intelligence import (
    AS_OF,
    attention_queue,
    attribute_change,
    integrity_report,
    portfolio_mandate_review,
)
from singhacks26.news import NewsCache, most_affected, refresh_news
from singhacks26.recommendation import build_recommendation_fact_packet, generate_recommendation
from singhacks26.workbench import (
    WorkbenchStore,
    liquidity_profile,
    lookthrough_exposure,
    snapshot_history,
    theme_exposure,
)

ROOT = Path(__file__).parent
DATA = ROOT / "data"
VAULT = ROOT / "obsidian_vault"
WORKFLOW = WorkbenchStore(VAULT / "workbench_state.json")
NEWS_CACHE = NewsCache(VAULT / "news_cache.json")
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
        "client_id": "CL-0003",
        "severity": "Urgent",
        "headline": "The inherited portfolio does not reflect the risk she believes she is taking",
        "context": (
            "Margarethe recently inherited the portfolio, describes herself as someone who has "
            "never taken investment risk, and has a Conservative profile."
        ),
        "client_view": (
            "She asked for something safe and boring and does not want changes while grieving. "
            "A confirmed EUR 3.4m inheritance-tax instalment is due before year end."
        ),
        "why_now": (
            "About 71% of the current portfolio is equity, above the Conservative mandate's 30% "
            "ceiling, while available cash is below the confirmed tax requirement."
        ),
        "action": (
            "First reserve the inheritance-tax liquidity, then explain the inherited exposures "
            "and agree a paced de-risking review that respects her request for time."
        ),
        "opener": (
            "We do not need to rush into decisions today. I would first like to make sure the tax "
            "payment is protected and that you understand which risks you already inherited."
        ),
        "uncertainty": "German tax consequences require specialist confirmation before any disposal.",
        "evidence": "clients.csv · RM notes N-005/N-006 · mandates.csv · holdings 2026-08-26 · cash need CN-004",
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
CASEWORK_OPTIONS = {
    "CL-0012": [
        (
            "Build a near-term spending reserve",
            "Separates immediate spending from the decision to retain bonds.",
            "Lower yield; requires updated spending and bond cash flows.",
        ),
        (
            "Review selected duration exposure",
            "Tests whether the longest holdings still fit retirement.",
            "May crystallise losses; requires suitability and tax review.",
        ),
        (
            "Retain with monitoring triggers",
            "Respects the reluctance to sell while defining review points.",
            "Liquidity and duration risk remain.",
        ),
    ],
    "CL-0003": [
        (
            "Ring-fence the tax payment",
            "Protects the confirmed liability before changing the inheritance.",
            "Requires tax advice and may conflict with her request for no change.",
        ),
        (
            "Agree a phased suitability transition",
            "Moves toward Conservative limits at a client-led pace.",
            "Interim risk remains and must be explicitly accepted.",
        ),
    ],
    "CL-0014": [
        (
            "Create a project-funding sleeve",
            "Separates the HKD 60m need from the property view.",
            "May reduce upside; requires a full liquidity map.",
        ),
        (
            "Reduce look-through property exposure",
            "Addresses one economic risk across several wrappers.",
            "May crystallise losses and conflict with conviction.",
        ),
        (
            "Keep exposure with stress triggers",
            "Preserves the view while monitoring funding capacity.",
            "A rapid decline could leave little time to act.",
        ),
    ],
}
OPTION_CONTROLS = {
    "CL-0012": {
        "Build a near-term spending reserve": {
            "mechanics": [
                "Confirm annual spending",
                "Map coupons and maturities",
                "Size the cash reserve",
            ],
            "requires": ["Updated medical-cost estimate", "Bond cash-flow schedule"],
        },
        "Review selected duration exposure": {
            "mechanics": [
                "Rank holdings by maturity and loss",
                "Compare hold-versus-sale funding paths",
            ],
            "requires": ["Suitability review", "Tax and transaction-cost review"],
        },
        "Retain with monitoring triggers": {
            "mechanics": ["Set cash-runway and yield review points", "Assign a review date"],
            "requires": ["Explicit acceptance of continuing duration and liquidity risk"],
        },
    },
    "CL-0003": {
        "Ring-fence the tax payment": {
            "mechanics": [
                "Confirm liability and date",
                "Reserve cash",
                "Identify funding shortfall",
            ],
            "requires": ["German tax specialist confirmation", "Client consent while grieving"],
        },
        "Agree a phased suitability transition": {
            "mechanics": [
                "Explain inherited exposure",
                "Agree pace",
                "Record temporary deviations",
            ],
            "requires": ["Updated suitability discussion", "Tax-aware disposal review"],
        },
    },
    "CL-0014": {
        "Create a project-funding sleeve": {
            "mechanics": [
                "Map sellability and pledges",
                "Separate project funding",
                "Recheck facility headroom",
            ],
            "requires": ["Confirmed project schedule", "Credit review of collateral releases"],
        },
        "Reduce look-through property exposure": {
            "mechanics": [
                "Aggregate all wrappers",
                "Compare reduction paths",
                "Stress remaining collateral",
            ],
            "requires": ["Product unwind terms", "Suitability and transaction-cost review"],
        },
        "Keep exposure with stress triggers": {
            "mechanics": ["Set LTV and funding triggers", "Assign monitoring owner and date"],
            "requires": ["Credit confirmation of drawn balance", "Explicit risk acceptance"],
        },
    },
}
RELATIONSHIP_CANVAS = {
    "CL-0012": {
        "voice": (
            "“I do not want to sell anything at a loss. I would rather wait for the bonds "
            "to come back.”"
        ),
        "voice_source": "RM note N-016 · Call · 2026-07-16",
        "human_read": (
            "RM hypothesis: the loss may feel like evidence that the ‘safe’ part of his wealth "
            "has failed him. Selling could feel less like portfolio maintenance and more like "
            "admitting a permanent mistake."
        ),
        "aspiration": (
            "Maintain dignity and financial security through retirement while leaving meaningful "
            "capital to his children."
        ),
        "call_purpose": (
            "Earn permission to map how living and medical costs will be funded while he waits—"
            "without beginning with a request to sell."
        ),
        "questions": [
            "What has changed most in your medical and living expenses?",
            "How much readily available cash would help you feel secure for the next two years?",
            "When you say you do not want to sell at a loss, which holdings feel most important to keep?",
            "If preserving lifestyle and preserving the inheritance conflict temporarily, how would you rank them?",
        ],
        "listen_for": [
            "Whether medical costs are temporary, recurring or still unknown",
            "Whether ‘safe’ means stable price, dependable income or no permanent loss",
            "Whether concern for his children is limiting spending he genuinely needs",
        ],
        "avoid": [
            "Do not tell him that waiting is irrational.",
            "Do not begin with a proposed bond sale.",
            "Do not imply that maturity guarantees recovery on his required timeline.",
        ],
        "branches": [
            (
                "If he refuses any sale",
                "Agree a cash-flow review and define the point at which liquidity must be revisited.",
            ),
            (
                "If he prioritises certainty",
                "Explore the size of a dedicated spending reserve before discussing securities.",
            ),
            (
                "If medical costs remain unclear",
                "Pause portfolio action and obtain an updated spending range first.",
            ),
        ],
    },
    "CL-0003": {
        "voice": "“I would prefer something safe and boring.”",
        "voice_source": "RM note N-006 · Email · 2026-05-29",
        "human_read": (
            "RM hypothesis: she may be processing grief, unfamiliar responsibility and fear of "
            "making an irreversible mistake at the same time. Inaction may currently feel safer "
            "than either keeping or changing the inheritance."
        ),
        "aspiration": (
            "Feel protected and in control of inherited wealth without being forced to become an "
            "investment expert while grieving."
        ),
        "call_purpose": (
            "Separate the immediate tax-liquidity decision from the longer portfolio transition, "
            "and let her choose a pace she can tolerate."
        ),
        "questions": [
            "Would it help if we dealt only with protecting the tax payment today?",
            "Are any inherited holdings personally significant or not to be changed without family discussion?",
            "When you say safe and boring, what outcome would make you feel most reassured?",
            "Who is confirming the German inheritance-tax amount and timing with you?",
        ],
        "listen_for": [
            "Permission to handle the tax need separately from investment decisions",
            "Emotional attachment to holdings selected by her late husband",
            "Whether simplicity, capital stability or low involvement defines safety for her",
        ],
        "avoid": [
            "Do not use the tax deadline to pressure a full rebalance.",
            "Do not describe inherited positions as mistakes.",
            "Do not calculate or imply a German tax outcome without specialist confirmation.",
        ],
        "branches": [
            (
                "If she wants no investment changes",
                "Seek permission only to reserve the confirmed tax amount and document the temporary risk.",
            ),
            (
                "If she feels overwhelmed",
                "Reduce the meeting to one decision and provide a plain-language holdings explanation later.",
            ),
            (
                "If she is ready to engage",
                "Agree a paced suitability review rather than presenting a finished allocation.",
            ),
        ],
    },
    "CL-0014": {
        "voice": "“That is why I am confident.”",
        "voice_source": "RM note N-018 · Call · 2026-03-05",
        "human_read": (
            "RM hypothesis: property conviction is part of his professional identity. A direct "
            "challenge may sound like a challenge to his competence, not merely to an allocation."
        ),
        "aspiration": (
            "Participate fully in a property recovery while retaining the freedom to complete the "
            "family redevelopment project."
        ),
        "call_purpose": (
            "Test whether the redevelopment remains fundable if his recovery view takes longer, "
            "without asking him to abandon that view."
        ),
        "questions": [
            "Which part of the HKD 60m contribution is fixed, and which part could move in timing?",
            "Which portfolio assets do you currently regard as available for the project?",
            "What would you want us to protect if the recovery is delayed by twelve months?",
            "At what collateral level would you want Priscilla to contact you immediately?",
        ],
        "listen_for": [
            "Flexibility in the project amount or timing",
            "A mismatch between perceived and genuinely withdrawable liquidity",
            "Whether he distinguishes confidence in property from capacity to fund further exposure",
        ],
        "avoid": [
            "Do not debate whether his property forecast is right.",
            "Do not describe all daily-liquid assets as withdrawable while they are pledged.",
            "Do not quote LTV externally until the unexplained facility balance is confirmed.",
        ],
        "branches": [
            (
                "If conviction remains unchanged",
                "Frame funding protection as what allows him to keep the view for longer.",
            ),
            (
                "If project timing is flexible",
                "Map staged funding dates before discussing exposure changes.",
            ),
            (
                "If funding is inflexible",
                "Prioritise credit confirmation and a protected project-funding amount.",
            ),
        ],
    },
}

st.set_page_config(page_title="Aurelia | RM Intelligence", page_icon="◈", layout="wide")


@st.cache_data
def load_data():
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


def client_notes(notes, client_id):
    return sorted(
        (note for note in notes if note["client_id"] == client_id),
        key=lambda note: note["note_date"],
        reverse=True,
    )


def detect_themes(text):
    clean = text.lower()
    return [theme for theme, words in THEMES.items() if any(word in clean for word in words)]


def client_exposure_text(data, client_id):
    latest = data["holdings"]["snapshot_date"].max()
    holdings = data["holdings"]
    positions = holdings[(holdings.client_id == client_id) & (holdings.snapshot_date == latest)]
    client = data["clients"].loc[data["clients"].client_id == client_id].iloc[0]
    notes = client_notes(data["rm_notes"], client_id)
    position_text = " ".join(
        positions[["instrument_name", "asset_class", "sub_asset_class", "sector", "region"]]
        .fillna("")
        .astype(str)
        .agg(" ".join, axis=1)
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
                rows.append(
                    {
                        "client_id": client.client_id,
                        "client": client.client_name,
                        "event_date": event.event_date,
                        "severity": event.severity,
                        "severity_rank": rank,
                        "description": event.description,
                        "transmission": event.primary_transmission,
                        "themes": overlap,
                        "relevance": min(100, 40 + 15 * len(overlap) + 8 * rank),
                    }
                )
    return pd.DataFrame(rows).sort_values(
        ["severity_rank", "relevance", "event_date"], ascending=[False, False, False]
    )


def rm_calendar_items(_data, workflow, event_impacts):
    """Build dated RM items without inventing client meetings."""
    clients_by_id = _data["clients"].set_index("client_id")["client_name"].to_dict()
    items = []
    for _, need in _data["planned_cash_needs"].iterrows():
        items.append(
            {
                "date": str(need.due_from),
                "client_id": need.client_id,
                "client": clients_by_id.get(need.client_id, need.client_id),
                "type": "Cash need",
                "title": need.description,
                "source": f"planned_cash_needs.csv · {need.need_id}",
            }
        )
    for _, client in _data["clients"].iterrows():
        items.append(
            {
                "date": str(client.kyc_review_due),
                "client_id": client.client_id,
                "client": client.client_name,
                "type": "KYC review",
                "title": "KYC review due",
                "source": f"clients.csv · {client.client_id}",
            }
        )
    for task in workflow.get("tasks", []):
        if task.get("status", "open") != "open" or not task.get("due_date"):
            continue
        client_id = task.get("client_id", "")
        items.append(
            {
                "date": str(task["due_date"]),
                "client_id": client_id,
                "client": clients_by_id.get(client_id, client_id or "Internal"),
                "type": "RM task",
                "title": task.get("title", "Follow-up"),
                "source": task.get("evidence_ref", "Local action record"),
            }
        )
    mapped_events = event_impacts.groupby(
        ["event_date", "description", "severity"], as_index=False
    ).agg(
        affected_clients=("client_id", "nunique"),
        client_names=("client", lambda values: list(dict.fromkeys(values))[:4]),
    )
    for _, event in mapped_events.iterrows():
        clients_label = ", ".join(event.client_names)
        items.append(
            {
                "date": str(event.event_date),
                "client_id": "MULTI",
                "client": f"{int(event.affected_clients)} affected clients",
                "type": f"Portfolio event · {event.severity}",
                "title": event.description,
                "source": f"event_log.csv · mapped to {clients_label}",
            }
        )
    return pd.DataFrame(items).sort_values(["date", "client", "type"])


def render_month_calendar(items, year, month):
    """Render a compact calendar, with detail listed separately below it."""
    days_with_items = set(
        pd.to_datetime(items["date"], errors="coerce")
        .loc[lambda values: (values.dt.year == year) & (values.dt.month == month)]
        .dt.day.dropna()
        .astype(int)
    )
    headers = "".join(
        f"<div class='cal-head'>{day}</div>" for day in ["M", "T", "W", "T", "F", "S", "S"]
    )
    cells = []
    for week in monthcalendar(year, month):
        for day in week:
            if day == 0:
                cells.append("<div class='cal-day cal-empty'></div>")
            else:
                marker = "<span class='cal-dot'></span>" if day in days_with_items else ""
                cells.append(f"<div class='cal-day'>{day}{marker}</div>")
    st.markdown(
        f"<div class='calendar-grid'>{headers}{''.join(cells)}</div>", unsafe_allow_html=True
    )


def vault_notes(client_id):
    path = VAULT / "Clients" / f"{client_id}.md"
    if not path.exists():
        return []
    entries = re.findall(
        r"<!-- RM-NOTE -->\s*### (.*?) · (.*?)\n\n(.*?)(?=\n<!-- RM-NOTE -->|\Z)",
        path.read_text(encoding="utf-8"),
        flags=re.DOTALL,
    )
    return [
        {"date": date, "category": category, "note": body.strip()}
        for date, category, body in entries
    ]


def save_vault_note(client_id, client_name, category, note):
    if client_id not in set(data["clients"].client_id) or not note.strip():
        return False
    path = VAULT / "Clients" / f"{client_id}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(
            f"---\ntype: client-context\nclient_id: {client_id}\nvisibility: restricted\n---\n\n"
            f"# {client_name}\n\n## RM working notes\n",
            encoding="utf-8",
        )
    timestamp = datetime.now().astimezone().isoformat(timespec="minutes")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"\n<!-- RM-NOTE -->\n### {timestamp} · {category}\n\n{note.strip()}\n")
    return True


def sentence(text, limit=220):
    """Return a compact first sentence without inventing a summary."""
    first = re.split(r"(?<=[.!?])\s+", str(text).strip())[0]
    return first if len(first) <= limit else f"{first[: limit - 1].rstrip()}…"


def call_brief(client_id):
    """Build a deterministic, traceable brief from controlled local sources."""
    client = data["clients"].loc[data["clients"].client_id == client_id].iloc[0]
    curated = next((item for item in DEEP_DIVE_INSIGHTS if item["client_id"] == client_id), None)
    if curated:
        relationship = RELATIONSHIP_CANVAS[client_id]
        return {
            "why": curated["headline"],
            "context": curated["context"],
            "tension": curated["client_view"],
            "changed": curated["why_now"],
            "opening": curated["opener"],
            "questions": relationship["questions"][:3],
            "client_voice": relationship["voice"],
            "rm_hypothesis": relationship["human_read"],
            "listen_for": relationship["listen_for"],
            "avoid_saying": relationship["avoid"],
            "actions": curated["action"],
            "check": curated["uncertainty"],
            "evidence": curated["evidence"],
            "confidence": "High for stated context; requires RM validation for proposed action.",
        }

    notes = client_notes(data["rm_notes"], client_id)
    latest_note = notes[0] if notes else None
    relevant = impacts[impacts.client_id == client_id].head(1)
    cash_needs = data["planned_cash_needs"].query("client_id == @client_id")
    event_text = (
        sentence(relevant.iloc[0].description)
        if not relevant.empty
        else "No directly mapped controlled event has been identified."
    )
    event_ref = (
        f"event_log.csv {relevant.iloc[0].event_date}" if not relevant.empty else "no mapped event"
    )
    need_text = (
        f" A recorded future need is {sentence(cash_needs.iloc[0].description).lower()}."
        if not cash_needs.empty
        else ""
    )
    note_text = sentence(latest_note["note"]) if latest_note else "No RM note is available."
    note_ref = latest_note["note_id"] if latest_note else "no RM note"
    return {
        "why": f"Review {client.client_name}'s latest context before the next contact.",
        "context": (
            f"{client.life_stage}; {client.risk_profile} risk profile. "
            f"The stated objective is: {client.objectives}"
        ),
        "tension": f"Latest recorded RM context: {note_text}{need_text}",
        "changed": event_text,
        "opening": (
            "Before we discuss the portfolio, I would like to confirm what has changed for you "
            "and which objective should take priority today."
        ),
        "questions": [
            "Has your outlook, liquidity need or time horizon changed since the last note?",
            "Which objective matters most before the next review?",
            "Is the current portfolio exposure intentional?",
        ],
        "actions": (
            "Confirm the latest client circumstances, then review suitability, liquidity and "
            "relevant exposure before discussing options."
        ),
        "check": (
            "This fallback brief has not established a specific aspiration clash. Review holdings, "
            "mandate, cash needs and the full source note before the call."
        ),
        "evidence": f"clients.csv · RM note {note_ref} · {event_ref}",
        "confidence": "Preliminary—structured fallback requiring RM review.",
    }


def brief_as_markdown(client_id, brief):
    client = data["clients"].loc[data["clients"].client_id == client_id].iloc[0]
    questions = "\n".join(f"- {question}" for question in brief["questions"])
    return f"""# 60-second call brief — {client.client_name}

## Why call now
{brief["why"]}

## Client context
{brief["context"]}

## Core tension
{brief["tension"]}

## Client voice
{brief.get("client_voice", "No direct client statement selected.")}

## RM hypothesis to test
{brief.get("rm_hypothesis", "No relationship hypothesis recorded.")}

## What changed
{brief["changed"]}

## How to open
“{brief["opening"]}”

## Questions to ask
{questions}

## Possible action to discuss
{brief["actions"]}

## Check before speaking
{brief["check"]}

## Evidence
{brief["evidence"]}

Confidence: {brief["confidence"]}
Human review required. Conversation support only; not investment advice.
"""


def ai_fact_packet(brief):
    """Create the only payload permitted to leave the local app."""
    evidence_ids = [item.strip() for item in brief["evidence"].split("·")]
    return {
        "synthetic_data": True,
        "why_call_now": brief["why"],
        "client_context": brief["context"],
        "core_tension": brief["tension"],
        "client_voice": brief.get("client_voice"),
        "rm_hypothesis_to_test": brief.get("rm_hypothesis"),
        "listen_for": brief.get("listen_for", []),
        "avoid_saying": brief.get("avoid_saying", []),
        "relevant_change": brief["changed"],
        "deterministic_action_for_rm_review": brief["actions"],
        "known_uncertainty": brief["check"],
        "allowed_evidence_ids": evidence_ids,
    }


def render_ai_draft(client_id, brief):
    st.markdown("#### AI-prepared conversation draft")
    st.caption(
        "AI rewrites only the redacted fact packet above. It cannot access files, tools or live data."
    )
    if not ai_is_configured():
        st.info("Add OPENAI_API_KEY to a local .env file to enable AI drafting.")
        return
    cache_key = f"ai_brief_{client_id}"
    if st.button("✨ Draft with AI", key=f"draft_{client_id}", type="primary"):
        try:
            with st.spinner("Drafting from verified facts…"):
                draft, model = draft_ai_brief(ai_fact_packet(brief))
            st.session_state[cache_key] = {"draft": draft.model_dump(), "model": model}
        except Exception as exc:  # API failures should not break deterministic briefing.
            st.error(f"AI drafting is unavailable: {exc}")
    saved = st.session_state.get(cache_key)
    if not saved:
        return
    draft = saved["draft"]
    st.success(f"Drafted with {saved['model']} · Not yet approved")
    st.markdown(f"**Why call now:** {draft['why_call_now']}")
    st.info(f"Suggested opening: “{draft['empathetic_opening']}”")
    st.markdown(f"**Client tension:** {draft['client_tension']}")
    st.markdown("**Questions to ask**")
    for question in draft["questions_to_ask"]:
        st.markdown(f"- {question}")
    st.markdown("**Options for Priscilla to review**")
    for option in draft["options_to_review"]:
        st.markdown(f"- {option}")
    st.markdown("**Uncertainties**")
    for uncertainty in draft["uncertainties"]:
        st.markdown(f"- {uncertainty}")
    st.caption(f"Evidence used: {' · '.join(draft['evidence_ids'])}")
    st.warning(
        "AI draft—not approved. Priscilla remains responsible for the conversation and advice."
    )


def ensure_news(data):
    """Refresh cached Marketaux news once per TTL; return (payload, ranking, error)."""
    cache = NewsCache(VAULT / "news_cache.json")
    try:
        payload = refresh_news(data, cache=cache)
    except RuntimeError as exc:
        stale = cache.load()
        return stale, most_affected(stale, data["holdings"]), str(exc)
    return payload, most_affected(payload, data["holdings"]), None


def alignment_report_for(client_id):
    """Return an AlignmentReport dict for a client (stub until Role 0 lands)."""
    # TODO(Role 1): replace with Role 0's AlignmentStore once it is on main.
    from ralph.stub_alignment import stub_alignment_report

    return stub_alignment_report(client_id)


def render_live_news(payload, ranking, error):
    """Live Marketaux news panel, kept distinct from the controlled event surface."""
    st.markdown("### Live news")
    st.caption(
        "Live Marketaux feed as of the fetch time below. This is a separate, dated feed "
        "and is not the controlled `event_log.csv` surface."
    )
    if error:
        st.error(f"Live news unavailable: {error}")
        return
    fetched = payload.get("fetched_utc")
    if fetched:
        st.caption(f"Fetched: {fetched}")
    if st.button("Refresh news", key="refresh_news_button"):
        with st.spinner("Fetching live Marketaux news across all clients…"):
            refresh_news(data, cache=NEWS_CACHE, force=True)
        st.rerun()
    if ranking.empty:
        st.info("No live news matched any client's held sectors in the current feed.")
        return
    st.markdown("**Most affected clients right now**")
    for _, row in ranking.iterrows():
        name = clients.loc[clients.client_id == row.client_id, "client_name"].iloc[0]
        with st.container(border=True):
            st.markdown(
                f"**{name}** · exposure-weighted score {row.exposure_weighted_score:.3f}"
            )
            st.caption("Exposed sectors: " + ", ".join(row.exposed_sectors))
            for headline in row.driving_headlines:
                st.markdown(f"- {headline}")


def render_recommendation(client_id):
    """RM-initiated, guardrailed recommendation draft with a reviewed-note save path."""
    st.markdown("#### Get recommendation")
    st.caption(
        "RM-initiated. Passes the censored static note, alignment report, surfaced "
        "conflicts and latest cached news to the AI for a guardrailed draft. "
        "Not approved until Priscilla reviews it."
    )
    if not ai_is_configured():
        st.info("Add OPENAI_API_KEY to a local .env file to enable recommendation drafting.")
        return
    if st.button("Get recommendation", key=f"recommend_{client_id}", type="primary"):
        try:
            with st.spinner("Preparing a recommendation draft from verified facts…"):
                note_path = VAULT / "Clients" / f"{client_id}.md"
                vault_text = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
                news_items = NEWS_CACHE.articles_for(news_payload, client_id) if news_payload else []
                packet = build_recommendation_fact_packet(
                    data, client_id, vault_text, alignment_report_for(client_id), news_items
                )
                draft, model = generate_recommendation(packet)
            st.session_state[f"recommendation_{client_id}"] = {
                "draft": draft.model_dump(),
                "model": model,
            }
        except Exception as exc:  # API failures should not break the rest of the deep dive.
            st.error(f"Recommendation drafting is unavailable: {exc}")
    saved = st.session_state.get(f"recommendation_{client_id}")
    if not saved:
        return
    draft = saved["draft"]
    client = clients.loc[clients.client_id == client_id].iloc[0]
    st.success(f"Drafted with {saved['model']} · Not approved")
    st.markdown(f"**Summary:** {draft['summary']}")
    st.markdown("**Alignment and conflicts to discuss**")
    for item in draft["alignment_and_conflicts_to_discuss"]:
        st.markdown(f"- {item}")
    if draft["news_drivers"]:
        st.markdown("**News drivers**")
        for item in draft["news_drivers"]:
            st.markdown(f"- {item}")
    st.markdown("**Topics for Priscilla to review**")
    for item in draft["rm_recommendation_topics"]:
        st.markdown(f"- {item}")
    st.markdown("**Questions to ask**")
    for item in draft["questions_to_ask"]:
        st.markdown(f"- {item}")
    st.markdown("**Risks and uncertainties**")
    for item in draft["risks_and_uncertainties"]:
        st.markdown(f"- {item}")
    st.caption(f"Evidence used: {' · '.join(draft['evidence_ids'])}")
    st.warning(f"{draft['guardrail_note']}. Priscilla remains responsible for the advice.")
    with st.expander("Save reviewed recommendation"):
        reviewed = st.text_area(
            "Reviewed note",
            value=f"Summary: {draft['summary']}\n\nTopics: {'; '.join(draft['rm_recommendation_topics'])}",
            key=f"reviewed_recommendation_{client_id}",
        )
        if st.button("Save reviewed note", key=f"save_recommendation_{client_id}"):
            if save_vault_note(client_id, client.client_name, "Recommendation review", reviewed):
                st.success("Reviewed recommendation saved to the local Obsidian vault.")


def render_call_brief(client_id):
    brief = call_brief(client_id)
    st.markdown(f"### {brief['why']}")
    st.caption(brief["confidence"])
    left, right = st.columns(2)
    with left:
        st.markdown("**Client context**")
        st.write(brief["context"])
        st.markdown("**Core tension**")
        st.write(brief["tension"])
        st.markdown("**What changed**")
        st.write(brief["changed"])
    with right:
        st.markdown("**How to open**")
        st.info(f"“{brief['opening']}”")
        st.markdown("**Questions to ask**")
        for question in brief["questions"]:
            st.markdown(f"- {question}")
        st.markdown("**Possible action to discuss**")
        st.write(brief["actions"])
    st.markdown("**Check before speaking**")
    st.warning(brief["check"])
    st.markdown("**Evidence trail**")
    st.code(brief["evidence"], language=None)
    st.caption("Human review required · Conversation support only · Not investment advice")
    render_ai_draft(client_id, brief)
    return brief_as_markdown(client_id, brief)


def case_facts(client_id):
    """Calculate review facts for a focus case from source rows."""
    latest_date = data["holdings"].snapshot_date.max()
    positions = (
        data["holdings"].query("client_id == @client_id and snapshot_date == @latest_date").copy()
    )
    portfolio = data["portfolios"].loc[data["portfolios"].client_id == client_id].iloc[0]
    total = positions.market_value_base.sum()
    allocation = positions.groupby("asset_class").market_value_base.sum().div(total).mul(100)
    rules = data["mandates"].loc[data["mandates"].mandate_code == portfolio.mandate_code]
    mandate_rows = []
    for _, rule in rules.iterrows():
        actual = float(allocation.get(rule.asset_class, 0))
        mandate_rows.append(
            {
                "Asset class": rule.asset_class,
                "Actual": round(actual, 1),
                "Range": f"{rule.min_pct:.0f}–{rule.max_pct:.0f}%",
                "Status": "Within" if rule.min_pct <= actual <= rule.max_pct else "Review",
            }
        )
    instruments = data["instruments"][["instrument_id", "concentration_limit_applies"]]
    concentration = positions.merge(instruments, on="instrument_id", how="left")
    limit = float(rules.max_single_position_pct.iloc[0])
    concentration = concentration[
        (concentration.concentration_limit_applies == "Y") & (concentration.weight_pct > limit)
    ][["instrument_name", "weight_pct"]]
    liquid = positions.loc[positions.liquidity_tier == "Daily", "market_value_base"].sum()
    cash = positions.loc[positions.asset_class == "Cash and Equivalents", "market_value_base"].sum()
    need = data["planned_cash_needs"].loc[data["planned_cash_needs"].client_id == client_id]
    facility = data["credit_facilities"].loc[data["credit_facilities"].client_id == client_id]
    facility_controls = None
    if not facility.empty:
        facility_row = facility.iloc[0]
        trigger = float(facility_row.margin_call_ltv_pct) / 100
        withdrawable_lending_value = max(
            float(facility_row["lending_value_2026-08-26"])
            - float(facility_row["drawn_2026-08-26"]) / trigger,
            0,
        )
        balance_change = float(facility_row["drawn_2026-03-31"]) - float(
            facility_row["drawn_2026-02-27"]
        )
        recorded_drawdowns = (
            data["transactions"]
            .loc[
                (data["transactions"].client_id == client_id)
                & (data["transactions"].transaction_type == "Facility Drawdown")
                & (data["transactions"].trade_date > "2026-02-27")
                & (data["transactions"].trade_date <= "2026-03-31"),
                "amount",
            ]
            .sum()
        )
        facility_controls = {
            "withdrawable_lending_value": withdrawable_lending_value,
            "balance_change": balance_change,
            "recorded_drawdowns": float(recorded_drawdowns),
            "unexplained_change": balance_change - float(recorded_drawdowns),
        }
    client = data["clients"].loc[data["clients"].client_id == client_id].iloc[0]
    return {
        "date": latest_date,
        "currency": portfolio.base_currency,
        "liquid": float(liquid),
        "cash": float(cash),
        "need": None if need.empty else need.iloc[0],
        "facility": None if facility.empty else facility.iloc[0],
        "facility_controls": facility_controls,
        "mandate": pd.DataFrame(mandate_rows),
        "concentration": concentration,
        "gains": float(positions.unrealised_pnl_base.clip(lower=0).sum()),
        "losses": float(positions.unrealised_pnl_base.clip(upper=0).sum()),
        "tax_domicile": client.tax_domicile,
    }


def decision_watchpoint(client_id, facts):
    """Return one bounded calculation that makes the case decision-ready."""
    if client_id == "CL-0012" and facts["need"] is not None:
        years = facts["cash"] / float(facts["need"].amount)
        return (
            "Cash coverage",
            f"{years:.1f} years",
            "Cash holdings divided by the recorded annual cash need; coupons and security sales are not included.",
        )
    if client_id == "CL-0003" and facts["need"] is not None:
        gap = max(float(facts["need"].amount) - facts["cash"], 0)
        return (
            "Cash shortfall to confirmed need",
            f"{facts['currency']} {gap / 1e6:,.1f}m",
            "Recorded need less cash holdings; sellable assets exist, but tax and disposal consequences are not modelled.",
        )
    if client_id == "CL-0014" and facts["facility"] is not None:
        facility = facts["facility"]
        current_ltv = float(facility["ltv_pct_2026-08-26"])
        trigger = float(facility.margin_call_ltv_pct)
        collateral_fall = (1 - current_ltv / trigger) * 100
        return (
            "Collateral fall to trigger",
            f"{collateral_fall:.1f}%",
            "Static calculation with debt unchanged; it is not a forecast or full stress test.",
        )
    return "Review watchpoint", "Not available", "The source data is insufficient."


def case_json_payload(client, insight, facts):
    """Build a portable, auditable contract without duplicating source datasets."""
    need = facts["need"]
    facility = facts["facility"]
    watchpoint_label, watchpoint_value, watchpoint_caveat = decision_watchpoint(
        client.client_id, facts
    )
    mandate_exceptions = facts["mandate"].loc[facts["mandate"].Status == "Review"]
    structured_evidence = [
        {
            "source_file": "clients.csv",
            "row_or_id": client.client_id,
            "field": "risk_profile, objectives, tax_domicile",
            "value": {
                "risk_profile": client.risk_profile,
                "objectives": client.objectives,
                "tax_domicile": client.tax_domicile,
            },
            "snapshot_date": None,
            "confidence": "source_record",
        },
        {
            "source_file": "holdings.csv",
            "row_or_id": client.client_id,
            "field": "latest household positions",
            "value": {"snapshot": facts["date"], "currency": facts["currency"]},
            "snapshot_date": str(facts["date"]),
            "confidence": "measured",
        },
    ]
    if need is not None:
        structured_evidence.append(
            {
                "source_file": "planned_cash_needs.csv",
                "row_or_id": need.need_id,
                "field": "amount, due_from, due_to, certainty",
                "value": {
                    "amount": float(need.amount),
                    "currency": need.currency,
                    "due_from": str(need.due_from),
                    "due_to": str(need.due_to),
                    "certainty": need.certainty,
                },
                "snapshot_date": None,
                "confidence": "source_record",
            }
        )
    if facility is not None:
        structured_evidence.append(
            {
                "source_file": "credit_facilities.csv",
                "row_or_id": facility.facility_id,
                "field": "drawn, lending_value, ltv, margin_call_ltv",
                "value": {
                    "drawn": float(facility["drawn_2026-08-26"]),
                    "lending_value": float(facility["lending_value_2026-08-26"]),
                    "ltv_pct": float(facility["ltv_pct_2026-08-26"]),
                    "trigger_pct": float(facility.margin_call_ltv_pct),
                },
                "snapshot_date": AS_OF,
                "confidence": "source_record",
            }
        )
    return {
        "schema_version": "rm-intelligence-case/1.0",
        "as_of": str(facts["date"]),
        "client": {
            "client_id": client.client_id,
            "client_name": client.client_name,
            "life_stage": client.life_stage,
            "risk_profile": client.risk_profile,
            "tax_domicile": client.tax_domicile,
        },
        "relationship_context": {
            "client_voice": RELATIONSHIP_CANVAS[client.client_id]["voice"],
            "voice_source": RELATIONSHIP_CANVAS[client.client_id]["voice_source"],
            "aspiration": RELATIONSHIP_CANVAS[client.client_id]["aspiration"],
            "rm_hypothesis_to_test": RELATIONSHIP_CANVAS[client.client_id]["human_read"],
            "call_purpose": RELATIONSHIP_CANVAS[client.client_id]["call_purpose"],
            "questions": RELATIONSHIP_CANVAS[client.client_id]["questions"],
            "listen_for": RELATIONSHIP_CANVAS[client.client_id]["listen_for"],
            "avoid_saying": RELATIONSHIP_CANVAS[client.client_id]["avoid"],
            "response_branches": [
                {"client_signal": signal, "rm_response": response}
                for signal, response in RELATIONSHIP_CANVAS[client.client_id]["branches"]
            ],
        },
        "upstream_signal": {
            "severity": insight["severity"],
            "headline": insight["headline"],
            "client_context": insight["context"],
            "client_view": insight["client_view"],
            "why_now": insight["why_now"],
            "suggested_next_step": insight["action"],
            "confidence_limit": insight["uncertainty"],
        },
        "observed_facts": {
            "portfolio_currency": facts["currency"],
            "daily_liquidity": round(facts["liquid"], 2),
            "cash": round(facts["cash"], 2),
            "planned_cash_need": None
            if need is None
            else {
                "need_id": need.need_id,
                "description": need.description,
                "currency": need.currency,
                "amount": float(need.amount),
                "due_from": str(need.due_from),
                "due_to": str(need.due_to),
                "certainty": need.certainty,
            },
            "credit_facility": None
            if facility is None
            else {
                "facility_id": facility.facility_id,
                "currency": facility.facility_ccy,
                "drawn": float(facility["drawn_2026-08-26"]),
                "ltv_pct": float(facility["ltv_pct_2026-08-26"]),
                "margin_call_ltv_pct": float(facility.margin_call_ltv_pct),
                "withdrawable_lending_value_before_trigger": round(
                    facts["facility_controls"]["withdrawable_lending_value"], 2
                ),
                "unexplained_drawn_balance_change": round(
                    facts["facility_controls"]["unexplained_change"], 2
                ),
            },
            "mandate_exceptions": mandate_exceptions.to_dict(orient="records"),
            "position_limit_exceptions": facts["concentration"].to_dict(orient="records"),
            "unrealised_gains": round(facts["gains"], 2),
            "unrealised_losses": round(facts["losses"], 2),
            "decision_watchpoint": {
                "label": watchpoint_label,
                "value": watchpoint_value,
                "method_limit": watchpoint_caveat,
            },
        },
        "action_options": [
            {
                "option_id": f"{client.client_id}-option-{index}",
                "label": label,
                "rationale": rationale,
                "mechanics": OPTION_CONTROLS[client.client_id][label]["mechanics"],
                "trade_off_or_prerequisite": tradeoff,
                "requires": OPTION_CONTROLS[client.client_id][label]["requires"],
                "suitability_checks": [
                    "Risk profile and mandate",
                    "Liquidity and dated needs",
                    "Client preference and product understanding",
                    "Tax/planning escalation where applicable",
                ],
                "status": "rm_review_required",
            }
            for index, (label, rationale, tradeoff) in enumerate(
                CASEWORK_OPTIONS[client.client_id], start=1
            )
        ],
        "evidence": {
            "source_trail": insight["evidence"],
            "records": structured_evidence,
            "data_boundary": "Local challenge data only; no live or external feed.",
            "signal_origin": "Block 2 contract; reconstructed locally only as a prototype fallback.",
        },
        "governance": {
            "aurelia_owns_risk_detection_or_stress_testing": False,
            "upstream_signal_is_read_only": True,
            "computed_facts_are_deterministic": True,
            "generated_narrative_requires_rm_review": True,
            "investment_or_tax_advice": False,
            "client_contact_or_trade_execution": False,
        },
    }


def render_choice_framing(client_id, facts):
    """Frame one bounded client choice without detecting or modelling risk."""
    st.markdown("### Client choice paths")
    st.caption(
        "These calculations change only the displayed inputs. They are not forecasts, "
        "optimisation or trade recommendations."
    )
    assumptions: list[str]
    if client_id == "CL-0012":
        reserve_years = st.slider("Target cash reserve (years)", 1.0, 3.0, 2.0, 0.25)
        annual_need = float(facts["need"].amount)
        required_cash = reserve_years * annual_need
        funding_gap = max(required_cash - facts["cash"], 0)
        name = "Retirement cash-reserve comparison"
        inputs = {"reserve_years": reserve_years, "annual_need": annual_need}
        outputs = {
            "current_cash": round(facts["cash"], 2),
            "required_cash": round(required_cash, 2),
            "funding_gap": round(funding_gap, 2),
        }
        assumptions = [
            "The recorded annual cash need remains constant.",
            "Coupons, inflation, tax and medical-cost changes are excluded.",
        ]
        columns = st.columns(3)
        columns[0].metric("Current cash", f"USD {facts['cash'] / 1e6:,.2f}m")
        columns[1].metric("Target reserve", f"USD {required_cash / 1e6:,.2f}m")
        columns[2].metric("Funding gap", f"USD {funding_gap / 1e6:,.2f}m")
    elif client_id == "CL-0003":
        positions = data["holdings"].query("client_id == @client_id and snapshot_date == @AS_OF")
        total = float(positions.market_value_base.sum())
        equity = float(positions.loc[positions.asset_class == "Equity", "market_value_base"].sum())
        tax_need = float(facts["need"].amount)
        sale_required = max(tax_need - facts["cash"], 0)
        remaining_equity = max(equity - sale_required, 0)
        remaining_total = max(total - tax_need, 1)
        current_weight = equity / total * 100
        post_weight = remaining_equity / remaining_total * 100
        name = "Inheritance-tax funding comparison"
        inputs = {"confirmed_tax_need": tax_need, "fund_from_cash_first": True}
        outputs = {
            "cash_shortfall": round(sale_required, 2),
            "current_equity_weight_pct": round(current_weight, 2),
            "illustrative_post_payment_equity_weight_pct": round(post_weight, 2),
        }
        assumptions = [
            "Cash is used first and the remaining amount is raised only from equity.",
            "Prices, FX, transaction costs and German tax consequences are unchanged or excluded.",
        ]
        columns = st.columns(3)
        columns[0].metric("Confirmed tax need", f"EUR {tax_need / 1e6:,.1f}m")
        columns[1].metric("Cash shortfall", f"EUR {sale_required / 1e6:,.1f}m")
        columns[2].metric(
            "Illustrative equity weight",
            f"{post_weight:.1f}%",
            f"{post_weight - current_weight:+.1f} pts",
        )
    else:
        project_amount = 60_000_000.0
        protected = (
            st.slider("Project amount to protect from the pledged portfolio (HKD m)", 0, 60, 60, 5)
            * 1_000_000.0
        )
        upstream_available = float(facts["facility_controls"]["withdrawable_lending_value"])
        alternate_funding = max(protected - upstream_available, 0)
        name = "Project-funding conversation frame"
        inputs = {"confirmed_project_amount": project_amount, "amount_to_protect": protected}
        outputs = {
            "upstream_withdrawable_before_trigger": round(upstream_available, 2),
            "amount_requiring_alternate_funding_review": round(alternate_funding, 2),
        }
        assumptions = [
            "The HKD 60m project contribution remains confirmed.",
            "The withdrawable figure is a read-only Block 2 input, not recalculated here.",
            "No lending, tax, suitability or transaction outcome is assumed.",
        ]
        columns = st.columns(3)
        columns[0].metric("Confirmed project need", "HKD 60.0m")
        columns[1].metric("Amount to protect", f"HKD {protected / 1e6:,.1f}m")
        columns[2].metric("Alternate funding review", f"HKD {alternate_funding / 1e6:,.1f}m")
    st.markdown("**Assumptions**")
    for assumption in assumptions:
        st.markdown(f"- {assumption}")
    if st.button("Save this comparison", key=f"save_comparison_{client_id}"):
        WORKFLOW.save_comparison(
            client_id=client_id,
            name=name,
            inputs=inputs,
            outputs=outputs,
            assumptions=assumptions,
            evidence_version=AS_OF,
        )
        st.success("Choice-framing inputs, outputs and evidence version saved locally.")


def market_panel(data):
    market = data["market_context"]
    dates = sorted(market.snapshot_date.unique())
    latest = market[market.snapshot_date == dates[-1]].set_index("series_id")
    previous = market[market.snapshot_date == dates[-2]].set_index("series_id")
    tiles = [
        ("SPX", "S&P 500", "pts"),
        ("NASDAQ_COMP", "Nasdaq", "pts"),
        ("GOLD_USD_OZ", "Gold", "USD/oz"),
        ("BRENT_USD_BBL", "Brent", "USD/bbl"),
        ("UST_10Y_PCT", "US 10Y", "%"),
        ("VIX", "VIX", ""),
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
        "Client",
        ids,
        index=ids.index(default_client_id) if default_client_id in ids else 0,
        format_func=lambda client_id: (
            data["clients"].loc[data["clients"].client_id == client_id, "client_name"].iloc[0]
        ),
        key="notes_client",
    )
    brief_tab, source_tab, working_tab, add_tab = st.tabs(
        ["60-second brief", "Source notes", "RM working notes", "Add note"]
    )
    with brief_tab:
        markdown = render_call_brief(selected_id)
        st.download_button(
            "Download reviewed brief",
            data=markdown,
            file_name=f"{selected_id}-call-brief.md",
            mime="text/markdown",
            width="stretch",
        )
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
            name = (
                data["clients"].loc[data["clients"].client_id == selected_id, "client_name"].iloc[0]
            )
            if save_vault_note(selected_id, name, category, note):
                st.success("Saved to the local Obsidian vault.")
                st.rerun()


st.markdown(
    """
<style>
.stApp {background:radial-gradient(circle at 85% 0%,#132c39 0,#071419 35%,#061014 100%)}
[data-testid="stSidebar"] {background:#081a20;border-right:1px solid #173641}
[data-testid="stMetric"] {background:linear-gradient(145deg,#102932,#0b1d24);border:1px solid #1d414d;padding:14px;border-radius:16px}
div[data-testid="stVerticalBlockBorderWrapper"] {background:#0b1d24;border-color:#1d414d;border-radius:18px}
h1,h2,h3 {letter-spacing:-.025em}.eyebrow{color:#78d6c6;text-transform:uppercase;letter-spacing:.16em;font-size:.72rem;font-weight:700}
.hero{font-size:2.35rem;line-height:1.05;font-weight:750;margin:.3rem 0 .6rem;color:#f4f7f5}.muted{color:#8faab2}
.event-card{padding:18px 20px;margin:10px 0;background:linear-gradient(135deg,#102831,#0a1b21);border:1px solid #1f414c;border-radius:18px}
.event-title{font-size:1.05rem;font-weight:700;color:#eef5f3}.pill{display:inline-block;padding:3px 9px;margin:6px 5px 0 0;border-radius:999px;background:#153641;color:#8ee3d2;font-size:.72rem}
.calendar-grid{display:grid;grid-template-columns:repeat(7,1fr);gap:5px;margin:8px 0 16px}.cal-head{text-align:center;color:#77939a;font-size:.72rem;font-weight:700}.cal-day{position:relative;min-height:42px;padding:8px;border:1px solid #1b3942;border-radius:9px;background:#0d2229;color:#dfecea;font-size:.82rem}.cal-empty{opacity:.28}.cal-dot{position:absolute;right:7px;bottom:7px;width:7px;height:7px;border-radius:50%;background:#59d7bd;box-shadow:0 0 8px #59d7bd}.dashboard-panel{padding:18px 20px;border:1px solid #1b3942;border-radius:18px;background:#0b1d23;margin-bottom:14px}
</style>""",
    unsafe_allow_html=True,
)

data = load_data()
clients = data["clients"]
impacts = build_event_impacts(data)
attention = attention_queue(data)
news_payload, news_ranking, news_error = ensure_news(data)
default_client = st.session_state.get("active_client", clients.client_id.iloc[0])

with st.sidebar:
    st.markdown("### ◈ AURELIA")
    st.caption("RM Intelligence Workbench")
    page = st.radio(
        "Navigation",
        [
            "Attention map",
            "Focus casebook",
            "Client deep dive",
            "Notes library",
            "Upstream context",
            "Action record",
            "Methods & governance",
        ],
        label_visibility="collapsed",
    )
    st.divider()
    st.markdown("**Data boundary**")
    st.caption("Client data remains local. External market/news feeds are not connected.")

header_left, header_right = st.columns([0.86, 0.14])
with header_left:
    st.markdown(
        '<div class="eyebrow">Asia desk · Singapore & Hong Kong</div>', unsafe_allow_html=True
    )
with header_right:
    if st.button("✦ Notes", width="stretch"):
        notes_bubble(default_client)

if page == "Attention map":
    st.markdown(
        '<div class="hero">Where should Priscilla focus her attention today?</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="muted">A morning view of portfolio-relevant developments, dated obligations and clients requiring judgement.</div>',
        unsafe_allow_html=True,
    )

    st.markdown("### Latest developments affecting Priscilla’s clients")
    st.caption(
        "Only controlled world events with a mapped client exposure, objective or approved "
        "RM-note connection appear here. Relevance is a review lead—not proof of causation."
    )
    latest_events = (
        impacts.sort_values(["event_date", "severity_rank", "relevance"], ascending=False)
        .groupby(["event_date", "description", "severity", "transmission"], as_index=False)
        .agg(
            affected_clients=("client_id", "nunique"),
            client_names=("client", lambda values: list(dict.fromkeys(values))[:5]),
            themes=(
                "themes",
                lambda values: sorted({theme for group in values for theme in group}),
            ),
        )
        .sort_values("event_date", ascending=False)
        .head(3)
    )
    for column, (_, event) in zip(st.columns(3), latest_events.iterrows(), strict=False):
        with column:
            with st.container(border=True):
                st.caption(
                    f"{severity_badge(event.severity)} {event.severity} · {event.event_date}"
                )
                st.markdown(f"**{event.description}**")
                st.caption(f"Transmission: {event.transmission}")
                st.write(f"**{event.affected_clients} affected clients**")
                st.caption(" · ".join(event.client_names))
                st.caption(f"Mapped themes: {', '.join(event.themes)}")

    calendar_items = rm_calendar_items(data, WORKFLOW.read(), impacts)
    as_of = pd.Timestamp(AS_OF)
    upcoming = calendar_items.loc[pd.to_datetime(calendar_items.date) >= as_of].copy()
    calendar_history = calendar_items.loc[
        pd.to_datetime(calendar_items.date, errors="coerce") >= pd.Timestamp("2025-01-01")
    ].copy()
    left_column, right_column = st.columns([0.43, 0.57], gap="large")

    with left_column:
        st.markdown("### Upcoming reminders")
        st.caption("Nearest confirmed obligations and local RM follow-ups.")
        for _, item in upcoming.head(6).iterrows():
            days = (pd.Timestamp(item.date) - as_of).days
            with st.container(border=True):
                st.caption(f"{item.type} · {item.date} · in {days} days")
                st.markdown(f"**{item.client}**")
                st.write(item.title)
                st.caption(item.source)
        if upcoming.empty:
            st.info("No upcoming dated item is present in the controlled records.")

    with right_column:
        st.markdown("### Calendar")
        month_options = sorted(
            {
                pd.Timestamp(value).strftime("%Y-%m")
                for value in calendar_history.date
                if pd.notna(pd.to_datetime(value, errors="coerce"))
            }
        )
        as_of_month = as_of.strftime("%Y-%m")
        default_index = month_options.index(as_of_month) if as_of_month in month_options else 0
        selected_month = st.selectbox(
            "Calendar month",
            month_options or [as_of_month],
            index=default_index,
            format_func=lambda value: f"{month_name[int(value[5:7])]} {value[:4]}",
            label_visibility="collapsed",
        )
        selected_year, selected_month_number = map(int, selected_month.split("-"))
        month_items = calendar_history.loc[
            pd.to_datetime(calendar_history.date).dt.strftime("%Y-%m") == selected_month
        ]
        render_month_calendar(month_items, selected_year, selected_month_number)
        for date_value, day_items in month_items.groupby("date", sort=True):
            labels = " · ".join(f"{row.client}: {row.title}" for _, row in day_items.iterrows())
            st.markdown(f"**{pd.Timestamp(date_value).strftime('%d %b')}** — {labels}")
        st.caption(
            "History begins in 2025 and includes mapped portfolio events alongside RM tasks, "
            "KYC reviews and client cash-need dates. No meeting-diary source is supplied, so "
            "the app does not fabricate meetups."
        )

        st.markdown("### Client problems requiring attention")
        st.caption(
            "Block 2 supplies severity; Aurelia orders the RM’s attention using client context."
        )
        ranked = attention.merge(clients[["client_id", "client_name"]], on="client_id", how="left")
        ranked["why"] = ranked.reasons.apply(lambda reasons: " · ".join(reasons[:2]))
        for _, problem in ranked.head(5).iterrows():
            with st.container(border=True):
                title, score = st.columns([0.78, 0.22])
                title.markdown(f"**{problem.client_name}** · {problem.attention_band}")
                score.metric("Priority", int(problem.attention_index))
                st.write(problem.why)

    with st.expander("View and defend the full client ordering"):
        display_ranked = ranked.rename(
            columns={
                "severity": "upstream_risk_pressure",
                "materiality": "household_reach",
                "urgency": "clock_pressure",
            }
        )
        st.dataframe(
            display_ranked[
                [
                    "client_id",
                    "client_name",
                    "attention_band",
                    "attention_index",
                    "upstream_risk_pressure",
                    "household_reach",
                    "clock_pressure",
                    "why",
                ]
            ],
            hide_index=True,
            width="stretch",
        )
        st.warning(
            "The ordering does not infer probability, profitability or relationship value. "
            "Priscilla remains responsible and may disagree."
        )

elif page == "Focus casebook":
    st.markdown(
        '<div class="hero">Three clients. Three decisions worth preparing well.</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="muted">A focused review workspace for the most complicated cases. '
        "Figures come from the controlled 2026-08-26 snapshot; proposed actions remain "
        "subject to Priscilla’s judgement.</div>",
        unsafe_allow_html=True,
    )
    case_ids = ["CL-0012", "CL-0014", "CL-0003"]
    selected_id = st.selectbox(
        "Case",
        case_ids,
        format_func=lambda client_id: (
            f"{clients.loc[clients.client_id == client_id, 'client_name'].iloc[0]} · {client_id}"
        ),
    )
    client = clients.loc[clients.client_id == selected_id].iloc[0]
    insight = next(item for item in DEEP_DIVE_INSIGHTS if item["client_id"] == selected_id)
    facts = case_facts(selected_id)
    watchpoint_label, watchpoint_value, watchpoint_caveat = decision_watchpoint(selected_id, facts)
    case_payload = case_json_payload(client, insight, facts)
    relationship = RELATIONSHIP_CANVAS[selected_id]

    st.markdown(f"## {client.client_name}")
    st.caption(f"{client.life_stage} · {client.risk_profile} profile")
    st.info(f"**Purpose of the next call:** {relationship['call_purpose']}")

    (
        relationship_tab,
        call_guide_tab,
        evidence_tab,
        decision_lens_tab,
        decision_tab,
        next_steps_tab,
        json_tab,
    ) = st.tabs(
        [
            "Relationship canvas",
            "Call guide",
            "Upstream signal",
            "Choice framing",
            "RM judgement",
            "Next steps",
            "Case JSON",
        ]
    )
    with relationship_tab:
        st.markdown("### Start with the person")
        st.info(relationship["voice"])
        st.caption(relationship["voice_source"])
        left, right = st.columns(2)
        with left:
            st.markdown("**What they are trying to protect**")
            st.write(relationship["aspiration"])
            st.markdown("**What we know**")
            st.write(insight["context"])
        with right:
            st.markdown("**What may be underneath it**")
            st.write(relationship["human_read"])
            st.caption("This is an RM hypothesis to test—not a fact about the client.")
            st.markdown("**The relationship tension**")
            st.write(insight["client_view"])

    with evidence_tab:
        st.markdown("### Signal supplied to Aurelia")
        st.caption(
            "Risk detection and stress testing belong to Block 2. Aurelia treats this as "
            "read-only evidence, then adds client meaning, conversation preparation and "
            "follow-through. The standalone prototype reconstructs the input locally when no "
            "team payload is available."
        )
        metrics = st.columns(4)
        metrics[0].metric("AUM", f"USD {client.total_aum_usd / 1e6:,.1f}m")
        metrics[1].metric("Daily liquidity", f"{facts['currency']} {facts['liquid'] / 1e6:,.1f}m")
        if facts["need"] is not None:
            need = facts["need"]
            metrics[2].metric("Planned need", f"{need.currency} {need.amount / 1e6:,.1f}m")
            metrics[3].metric("Due", str(need.due_to))
        elif facts["facility"] is not None:
            facility = facts["facility"]
            metrics[2].metric("Current LTV", f"{facility['ltv_pct_2026-08-26']:.1f}%")
            metrics[3].metric("Margin-call level", f"{facility.margin_call_ltv_pct:.1f}%")
        else:
            metrics[2].metric(
                "Mandate exceptions",
                int((facts["mandate"].Status == "Review").sum()),
            )
            metrics[3].metric("Snapshot", facts["date"])
        st.info(
            f"Decision watchpoint — **{watchpoint_label}: {watchpoint_value}**. {watchpoint_caveat}"
        )
        st.markdown("### Mandate alignment")
        st.dataframe(facts["mandate"], hide_index=True, width="stretch")
        left, right = st.columns(2)
        with left:
            st.markdown("**Liquidity and liabilities**")
            st.write(f"Daily-liquid holdings: **{facts['currency']} {facts['liquid']:,.0f}**")
            if facts["need"] is not None:
                need = facts["need"]
                st.write(
                    f"{need.description}: **{need.currency} {need.amount:,.0f}**, "
                    f"due by {need.due_to} ({need.certainty})."
                )
            if facts["facility"] is not None:
                facility = facts["facility"]
                st.write(
                    f"Facility LTV is **{facility['ltv_pct_2026-08-26']:.1f}%** versus a "
                    f"**{facility.margin_call_ltv_pct:.1f}%** margin-call level."
                )
                controls = facts["facility_controls"]
                st.write(
                    f"Maximum lending value removable before the trigger: "
                    f"**{facts['currency']} {controls['withdrawable_lending_value']:,.0f}**."
                )
                if abs(controls["unexplained_change"]) > 1:
                    st.error(
                        f"Data-quality gate: the facility balance increased by "
                        f"{facts['currency']} {controls['balance_change']:,.0f}, but recorded "
                        f"drawdowns explain only {facts['currency']} "
                        f"{controls['recorded_drawdowns']:,.0f}. Confirm the "
                        f"{facts['currency']} {controls['unexplained_change']:,.0f} difference "
                        "before quoting LTV to the client."
                    )
        with right:
            st.markdown("**Position-level concentration checks**")
            if facts["concentration"].empty:
                st.caption("No flagged position exceeds the applicable single-position limit.")
            else:
                st.dataframe(facts["concentration"], hide_index=True, width="stretch")
            st.write(
                f"Unrealised gains: **{facts['currency']} {facts['gains']:,.0f}** · "
                f"losses: **{facts['currency']} {facts['losses']:,.0f}**"
            )
            st.caption(
                f"Tax domicile: {facts['tax_domicile']}. This is a specialist-review flag, "
                "not a tax conclusion."
            )
        st.markdown("### Household liquidity tiers")
        liquidity = liquidity_profile(data["holdings"], selected_id, facts["date"])
        st.dataframe(liquidity, hide_index=True, width="stretch")
        st.markdown("### Wrapper look-through")
        lookthrough = lookthrough_exposure(
            data["holdings"], data["instruments"], selected_id, facts["date"]
        )
        wrappers = lookthrough.loc[
            lookthrough.economic_reference != lookthrough.instrument_name,
            [
                "instrument_name",
                "economic_reference",
                "household_weight_pct",
                "liquidity_tier",
            ],
        ]
        if wrappers.empty:
            st.caption("No source-described wrapper references for this client.")
        else:
            st.dataframe(wrappers, hide_index=True, width="stretch")
        if selected_id == "CL-0014":
            golden_harbour = lookthrough.loc[
                lookthrough.instrument_name.str.contains("Golden Harbour", case=False),
                "household_weight_pct",
            ].sum()
            st.warning(
                f"Golden Harbour appears through shares, a perpetual and an accumulator: "
                f"**{golden_harbour:.1f}% of household value** before broader property exposure."
            )

    with decision_lens_tab:
        render_choice_framing(selected_id, facts)

    with decision_lens_tab:
        st.markdown("### Paths that depend on the client’s response")
        st.caption("These are review paths, not automated recommendations or trade instructions.")
        for label, reason, tradeoff in CASEWORK_OPTIONS[selected_id]:
            with st.container(border=True):
                st.markdown(f"**{label}**")
                st.write(reason)
                controls = OPTION_CONTROLS[selected_id][label]
                st.markdown("**How it would be reviewed**")
                for mechanic in controls["mechanics"]:
                    st.markdown(f"- {mechanic}")
                st.caption(f"Trade-off / prerequisite: {tradeoff}")
                st.caption(f"Required before action: {' · '.join(controls['requires'])}")
                st.caption(f"Source trail: {insight['evidence']}")

    with decision_tab:
        st.markdown("### Record the RM’s judgement")
        decision = st.radio(
            "Review status",
            ["Needs review", "Proceed to client discussion", "Dismiss for now"],
            horizontal=True,
            key=f"case_status_{selected_id}",
        )
        rationale = st.text_area(
            "Rationale and next step",
            placeholder="What Priscilla accepted, changed or rejected—and what must be checked next…",
            key=f"case_rationale_{selected_id}",
        )
        st.markdown("**Conversation readiness review**")
        evidence_checked = st.checkbox(
            "I checked the cited source rows and snapshot date",
            key=f"evidence_check_{selected_id}",
        )
        suitability_checked = st.checkbox(
            "I considered mandate, suitability and the client’s stated preference",
            key=f"suitability_check_{selected_id}",
        )
        specialist_checked = st.checkbox(
            "Required tax, legal or planning questions are identified for referral",
            key=f"specialist_check_{selected_id}",
        )
        if st.button("Save decision locally", type="primary", key=f"save_{selected_id}"):
            note = f"Focus casebook — {decision}. {rationale.strip()}"
            if not rationale.strip():
                st.warning("Add a rationale before saving the decision.")
            elif decision == "Proceed to client discussion" and not all(
                [evidence_checked, suitability_checked, specialist_checked]
            ):
                st.warning("Complete every readiness check before preparing client-facing wording.")
            elif save_vault_note(selected_id, client.client_name, "Risk observation", note):
                WORKFLOW.record_decision(
                    client_id=selected_id,
                    decision=decision,
                    rationale=rationale,
                    evidence_version=str(facts["date"]),
                    original_next_step=insight["action"],
                    gates={
                        "evidence": evidence_checked,
                        "suitability": suitability_checked,
                        "tax_planning": specialist_checked,
                        "human_rationale": bool(rationale.strip()),
                    },
                )
                st.success("Decision saved to the local Obsidian-compatible notes vault.")

    with call_guide_tab:
        st.markdown("### Enter with curiosity, not a conclusion")
        st.markdown("**A respectful opening**")
        st.info(f"“{insight['opener']}”")
        ask_column, listen_column = st.columns(2)
        with ask_column:
            st.markdown("**Ask**")
            for question in relationship["questions"]:
                st.markdown(f"- {question}")
        with listen_column:
            st.markdown("**Listen for**")
            for signal in relationship["listen_for"]:
                st.markdown(f"- {signal}")
        st.markdown("**Avoid saying**")
        for warning in relationship["avoid"]:
            st.markdown(f"- {warning}")
        st.markdown("**Let their answer determine the path**")
        for signal, response in relationship["branches"]:
            with st.container(border=True):
                st.markdown(f"**{signal}**")
                st.write(response)
        with st.expander("Open the 60-second evidence-backed brief"):
            brief_markdown = render_call_brief(selected_id)
        with st.expander("Call plan, readiness review and version history"):
            workflow = WORKFLOW.read()
            decisions = [item for item in workflow["decisions"] if item["client_id"] == selected_id]
            latest_decision = decisions[-1] if decisions else None
            decision_ready = bool(
                latest_decision
                and latest_decision["decision"] == "Proceed to client discussion"
                and all(latest_decision.get("gates", {}).values())
            )
            unresolved_data = bool(
                selected_id == "CL-0014"
                and abs(facts["facility_controls"]["unexplained_change"]) > 1
            )
            checks = pd.DataFrame(
                [
                    {
                        "Check": "RM decision and rationale",
                        "Status": "Pass" if decision_ready else "Block",
                    },
                    {
                        "Check": "Evidence snapshot attached",
                        "Status": "Pass" if facts["date"] == AS_OF else "Block",
                    },
                    {
                        "Check": "Facility data reconciled",
                        "Status": "Block" if unresolved_data else "Pass",
                    },
                    {
                        "Check": "Reporting language reviewed",
                        "Status": "Attention" if client.reporting_language != "English" else "Pass",
                    },
                ]
            )
            st.dataframe(checks, hide_index=True, width="stretch")
            st.markdown("**Do not say**")
            st.markdown("- Do not present a tax observation as a calculated tax outcome.")
            st.markdown("- Do not present an RM note or client belief as independently verified.")
            if unresolved_data:
                st.markdown(
                    "- Do not quote the facility LTV externally until Operations confirms the "
                    "HKD 2m balance discrepancy."
                )
            if client.reporting_language != "English":
                st.markdown(
                    f"- Client reporting language is {client.reporting_language}; route final "
                    "wording through the approved translation process."
                )
            edited_package = st.text_area(
                "Editable internal call plan",
                value=brief_markdown,
                height=300,
                key=f"call_plan_{selected_id}",
            )
            version_reason = st.text_input(
                "Reason for this version",
                placeholder="Initial RM review, revised opening, added specialist question…",
                key=f"meeting_reason_{selected_id}",
            )
            if st.button("Save internal package version", key=f"save_meeting_{selected_id}"):
                if not version_reason.strip():
                    st.warning("Record why this version is being saved.")
                else:
                    version = WORKFLOW.save_call_plan_version(
                        client_id=selected_id,
                        content=edited_package,
                        evidence_version=AS_OF,
                        reason=version_reason,
                    )
                    st.success(
                        f"Saved call-plan version {version['version']} with its source date."
                    )
            versions = [
                item
                for item in WORKFLOW.read()["call_plan_versions"]
                if item["client_id"] == selected_id
            ]
            if versions:
                st.caption(
                    " · ".join(
                        f"v{item['version']} {item['timestamp']} — {item['reason']}"
                        for item in reversed(versions)
                    )
                )

    with next_steps_tab:
        st.markdown("### Make the next step accountable")
        st.caption("Tasks and referrals stay local and retain their evidence reference.")
        task_type = st.selectbox(
            "Type",
            ["Follow-up task", "Specialist referral", "Evidence request"],
            key=f"task_type_{selected_id}",
        )
        title = st.text_input("Task", key=f"task_title_{selected_id}")
        owner = st.text_input("Owner", value="Priscilla Ong", key=f"task_owner_{selected_id}")
        due_date = st.date_input("Due date", key=f"task_due_{selected_id}")
        if st.button("Create accountable next step", key=f"create_task_{selected_id}"):
            if not title.strip() or not owner.strip():
                st.warning("Add both a task and an owner.")
            else:
                WORKFLOW.add_task(
                    client_id=selected_id,
                    title=title,
                    owner=owner,
                    due_date=due_date.isoformat(),
                    task_type=task_type,
                    evidence_ref=insight["evidence"],
                )
                st.success("Next step recorded locally with an audit event.")
        client_tasks = [
            task for task in WORKFLOW.read()["tasks"] if task["client_id"] == selected_id
        ]
        if client_tasks:
            st.dataframe(client_tasks, hide_index=True, width="stretch")
        else:
            st.caption("No accountable next steps recorded for this client yet.")
        st.divider()
        st.markdown("### After the conversation")
        st.caption(
            "Record what the client actually said separately from Priscilla’s interpretation."
        )
        disposition = st.selectbox(
            "What changed?",
            [
                "Preference confirmed",
                "Understanding changed",
                "More information required",
                "Client deferred the decision",
                "No material change",
            ],
            key=f"outcome_disposition_{selected_id}",
        )
        client_statement = st.text_area(
            "Client’s words",
            placeholder="Record the client’s statement as closely as possible…",
            key=f"outcome_statement_{selected_id}",
        )
        rm_interpretation = st.text_area(
            "Priscilla’s interpretation",
            placeholder="What might this change about the case, and what still needs testing?",
            key=f"outcome_interpretation_{selected_id}",
        )
        documents = st.text_input(
            "Documents or confirmations requested",
            placeholder="Separate multiple items with commas",
            key=f"outcome_documents_{selected_id}",
        )
        if st.button("Save conversation reflection", key=f"save_outcome_{selected_id}"):
            if not client_statement.strip() or not rm_interpretation.strip():
                st.warning("Record both the client’s words and Priscilla’s interpretation.")
            else:
                requested_documents = [
                    item.strip() for item in documents.split(",") if item.strip()
                ]
                WORKFLOW.record_conversation_outcome(
                    client_id=selected_id,
                    disposition=disposition,
                    client_statement=client_statement,
                    rm_interpretation=rm_interpretation,
                    requested_documents=requested_documents,
                )
                save_vault_note(
                    selected_id,
                    client.client_name,
                    "Conversation outcome",
                    f"Client said: {client_statement.strip()}\n\n"
                    f"RM interpretation: {rm_interpretation.strip()}",
                )
                st.success(
                    "Reflection saved locally with client words kept distinct from RM interpretation."
                )
        outcomes = [
            item
            for item in WORKFLOW.read()["conversation_outcomes"]
            if item["client_id"] == selected_id
        ]
        if outcomes:
            st.caption(f"{len(outcomes)} conversation reflection(s) recorded for this client.")

    with json_tab:
        st.markdown("### Structured intelligence contract")
        st.caption(
            "A versioned case payload derived from source data. Computed facts, narrative, "
            "options, evidence and governance remain separate for auditability."
        )
        st.download_button(
            "Download case JSON",
            data=json.dumps(case_payload, indent=2, ensure_ascii=False, default=str),
            file_name=f"{selected_id.lower()}-intelligence.json",
            mime="application/json",
        )
        st.json(case_payload, expanded=2)

elif page == "Upstream context":
    st.markdown(
        '<div class="hero">What changed—and who needs to know?</div>', unsafe_allow_html=True
    )
    st.markdown(
        '<div class="muted">Every signal is linked to a client exposure, objective or RM note.</div>',
        unsafe_allow_html=True,
    )
    st.markdown("### Market pulse")
    market_panel(data)
    st.markdown("### Exposure-linked intelligence")
    filter_left, filter_right = st.columns([0.35, 0.65])
    with filter_left:
        severity_filter = st.multiselect(
            "Severity", ["Severe", "High", "Medium", "Low"], default=["Severe", "High"]
        )
    with filter_right:
        theme_filter = st.multiselect("Theme", sorted(THEMES))
    filtered = impacts[impacts.severity.isin(severity_filter)] if severity_filter else impacts
    if theme_filter:
        filtered = filtered[
            filtered.themes.apply(lambda values: bool(set(values) & set(theme_filter)))
        ]
    for event_date, group in filtered.groupby("event_date", sort=False):
        event = group.iloc[0]
        affected = group.client_id.nunique()
        names = ", ".join(group.client.head(4)) + (f" +{affected - 4}" if affected > 4 else "")
        pills = "".join(f'<span class="pill">{theme}</span>' for theme in event.themes)
        st.markdown(
            f'<div class="event-card"><div class="eyebrow">{severity_badge(event.severity)} {event.severity} · {event_date} · {affected} clients</div>'
            f'<div class="event-title">{event.description}</div>{pills}'
            f'<div class="muted" style="margin-top:9px">Most exposed: {names}</div></div>',
            unsafe_allow_html=True,
        )
        with st.expander("View client relevance and evidence"):
            st.caption(f"Transmission: {event.transmission}")
            st.dataframe(
                group[["client_id", "client", "relevance", "themes"]],
                hide_index=True,
                width="stretch",
            )
            st.caption("Skill: event-to-exposure mapping · RM review required")

    render_live_news(news_payload, news_ranking, news_error)

elif page == "Action record":
    st.markdown(
        '<div class="hero">From insight to accountable next step.</div>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div class="muted">A local record of RM decisions, evidence requests and specialist referrals. Source files remain unchanged.</div>',
        unsafe_allow_html=True,
    )
    workflow = WORKFLOW.read()
    task_tab, reflection_tab, audit_tab = st.tabs(
        ["Open work", "Conversation reflections", "Decision audit"]
    )
    with task_tab:
        if workflow["tasks"]:
            tasks = pd.DataFrame(workflow["tasks"])
            client_filter = st.multiselect(
                "Clients", sorted(tasks.client_id.unique()), key="workflow_client_filter"
            )
            if client_filter:
                tasks = tasks.loc[tasks.client_id.isin(client_filter)]
            st.dataframe(tasks, hide_index=True, width="stretch")
            if not tasks.empty:
                st.markdown("**Update accountable work**")
                task_id = st.selectbox(
                    "Task",
                    tasks.task_id.tolist(),
                    format_func=lambda value: tasks.loc[tasks.task_id == value, "title"].iloc[0],
                )
                task_status = st.selectbox(
                    "New status", ["open", "in_progress", "complete", "cancelled"]
                )
                task_rationale = st.text_input(
                    "Update rationale", placeholder="What changed or was completed?"
                )
                if st.button("Record task update"):
                    if not task_rationale.strip():
                        st.warning("Add a rationale for the status change.")
                    else:
                        WORKFLOW.update_task(
                            task_id=task_id,
                            status=task_status,
                            rationale=task_rationale,
                        )
                        st.success("Task status and prior state recorded in the audit trail.")
        else:
            st.info("No tasks yet. Create one from a case’s Next steps tab.")
    with reflection_tab:
        if workflow["conversation_outcomes"]:
            reflections = pd.DataFrame(workflow["conversation_outcomes"]).sort_values(
                "recorded_at", ascending=False
            )
            st.dataframe(reflections, hide_index=True, width="stretch")
            st.caption(
                "Client statements and RM interpretations remain separate fields throughout."
            )
        else:
            st.info("No post-conversation reflections have been recorded yet.")
    with audit_tab:
        if workflow["audit"]:
            audit = pd.DataFrame(workflow["audit"]).sort_values("timestamp", ascending=False)
            st.dataframe(audit, hide_index=True, width="stretch")
        else:
            st.info("No RM workflow decisions have been recorded yet.")
        st.download_button(
            "Export local workflow JSON",
            data=json.dumps(workflow, indent=2, ensure_ascii=False, default=str),
            file_name="rm-workflow-audit.json",
            mime="application/json",
        )
        st.caption(
            "This prototype audit covers local user workflow actions; it does not claim bank-grade authentication or immutable storage."
        )

elif page == "Client deep dive":
    selected_id = st.selectbox(
        "Client",
        clients.client_id.tolist(),
        format_func=lambda client_id: clients.loc[
            clients.client_id == client_id, "client_name"
        ].iloc[0],
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
    holdings_tab, history_tab, events_tab, conversation_tab = st.tabs(
        ["Portfolio exposure", "Snapshot history", "Events & outlook", "Conversation brief"]
    )
    latest_date = data["holdings"].snapshot_date.max()
    positions = data["holdings"].query(
        "client_id == @selected_id and snapshot_date == @latest_date"
    )
    with holdings_tab:
        left, right = st.columns(2)
        with left:
            allocation = positions.groupby("asset_class").market_value_usd.sum().sort_values()
            st.markdown("**Allocation by asset class**")
            st.bar_chart(allocation, horizontal=True)
        with right:
            st.markdown("**Largest positions**")
            top = positions.nlargest(8, "market_value_usd")[
                ["instrument_name", "asset_class", "weight_pct", "liquidity_tier"]
            ]
            st.dataframe(top, hide_index=True, width="stretch")
        st.markdown("**Mandate review by portfolio**")
        mandate_review = portfolio_mandate_review(data, selected_id)
        st.dataframe(mandate_review, hide_index=True, width="stretch")
        st.caption(
            "Mandates are tested per governed portfolio. Custody portfolios remain in the "
            "household view but are explicitly excluded from mandate compliance."
        )
        st.markdown("**Curated household themes**")
        themes = theme_exposure(data["holdings"], selected_id, latest_date)
        st.dataframe(themes, hide_index=True, width="stretch")
        st.caption(
            "Theme membership is a published, hand-checked instrument-ID map. It is not "
            "inferred by AI or name similarity."
        )
    with history_tab:
        history = snapshot_history(data["holdings"], selected_id)
        st.markdown("**Household value across all five supplied snapshots**")
        st.line_chart(history.set_index("snapshot_date")["household_value_usd"])
        display_history = history.copy()
        display_history["change_usd"] = display_history.change_usd.round(2)
        display_history["change_pct"] = display_history.change_pct.round(2)
        st.dataframe(display_history, hide_index=True, width="stretch")
        start_snapshot = st.selectbox(
            "Explain change from",
            history.snapshot_date.iloc[:-1].tolist(),
            key=f"attribution_start_{selected_id}",
        )
        attribution = attribute_change(data, selected_id, start_snapshot, AS_OF)
        st.markdown("**Upstream portfolio explanation**")
        st.caption(
            "Presented as read-only evidence. Portfolio attribution is not claimed as an "
            "RM Intelligence Workbench capability."
        )
        bridge = st.columns(4)
        bridge[0].metric("Total change", f"USD {attribution['change_usd'] / 1e6:,.2f}m")
        bridge[1].metric("Price effect", f"USD {attribution['price_effect_usd'] / 1e6:,.2f}m")
        bridge[2].metric("FX effect", f"USD {attribution['fx_effect_usd'] / 1e6:,.2f}m")
        bridge[3].metric("Position flows", f"USD {attribution['flow_effect_usd'] / 1e6:,.2f}m")
        contributions = pd.DataFrame(attribution["contributions"])
        contributions["market_effect_usd"] = (
            contributions.price_effect_usd + contributions.fx_effect_usd
        )
        movers = contributions.reindex(
            contributions.market_effect_usd.abs().sort_values(ascending=False).index
        ).head(8)
        st.dataframe(
            movers[
                [
                    "instrument_name",
                    "price_effect_usd",
                    "fx_effect_usd",
                    "flow_effect_usd",
                    "total_change_usd",
                ]
            ],
            hide_index=True,
            width="stretch",
        )
        difference = attribution["reconciliation_difference_usd"]
        st.caption(
            f"Bridge reconciliation difference: USD {difference:,.2f}. New positions use "
            "closing-snapshot USD cost basis; source rounding residuals sit in price effect."
        )
        with st.expander("Attribution evidence and method"):
            st.json(attribution["evidence"])
            st.warning(
                "Attribution explains the arithmetic bridge. Event causality is shown separately "
                "and only where supported by event_log.csv."
            )
    with events_tab:
        relevant = impacts[impacts.client_id == selected_id].head(10)
        st.dataframe(
            relevant[["event_date", "severity", "description", "themes", "relevance"]],
            hide_index=True,
            width="stretch",
        )
    with conversation_tab:
        markdown = render_call_brief(selected_id)
        st.download_button(
            "Download reviewed brief",
            data=markdown,
            file_name=f"{selected_id}-call-brief.md",
            mime="text/markdown",
        )
        render_recommendation(selected_id)

elif page == "Notes library":
    st.markdown('<div class="hero">Notes, without the noise.</div>', unsafe_allow_html=True)
    query = st.text_input(
        "Search all source notes", placeholder="Try: retirement, gold, liquidity, technology…"
    )
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
    st.write(
        "The workbench uses bounded analysis skills. Every insight must identify its evidence and require human review."
    )
    skills_path = ROOT / "skills.md"
    if skills_path.exists():
        st.markdown(skills_path.read_text(encoding="utf-8"))
    st.info(
        "Live-provider adapters receive market themes or synthetic exposure IDs only—never names, raw RM notes, tax data or account-level holdings."
    )
    st.markdown("### Team scope boundary")
    st.markdown(
        "- **Upstream Blocks 1 and 2:** portfolio explanation, risk detection, event mapping, "
        "stress testing and their evidence.\n"
        "- **RM Intelligence Workbench:** prioritise the RM's attention, connect signals to "
        "client circumstances, frame choices, prepare the conversation, record RM judgement "
        "and manage follow-through.\n"
        "- Upstream signals are read-only. Local calculations exist only so this isolated demo "
        "still runs before team integration."
    )
    st.markdown("### Data integrity register")
    issues = integrity_report(data)
    if issues:
        st.dataframe(pd.DataFrame(issues), hide_index=True, width="stretch")
    else:
        st.success("No configured integrity check raised an issue.")
    st.caption(
        "Issues remain visible and block affected claims; the application does not silently "
        "repair source records."
    )
    st.markdown("### Calculation conventions")
    st.markdown(
        "- Dataset date is fixed at **2026-08-26**, independent of the machine clock.\n"
        "- Household exposure includes every portfolio; mandate checks run per governed portfolio.\n"
        "- LTV uses source lending value rather than gross market value.\n"
        "- Only `event_log.csv` supports claims about 2026 events.\n"
        "- Tax domicile is surfaced, but no tax outcome is calculated.\n"
        "- AI drafts language from bounded facts; it does not calculate, rank or approve."
    )

st.divider()
st.caption(
    "Controlled sources: repository data and local Obsidian vault · No external client-data transfer · Not investment advice"
)
