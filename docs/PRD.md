# PRD — Portfolio–Interest Alignment, Event Conflict Surfacing & Live News-Driven RM Intelligence

Status: Draft for build
Source of truth: `docs/challenge.md` (takes precedence where this PRD conflicts)
Build split: Role 0 (`docs/roles_0.md`) and Role 1 (`docs/roles_1.md`)

---

## 1. Context

The repo is a SingHacks 2026 Julius Baer wealth-intelligence prototype. Today
the RM (Priscilla Ong) uses a local Streamlit workbench (`app.py`, "AURELIA")
over the 20-client synthetic dataset in `data/`. It already surfaces controlled
event → client relevance, mandate reviews, attention ordering, focus casework
for three clients, a deterministic "60-second brief" per client, and an
optional AI conversation draft (`src/singhacks26/ai_brief.py`, OpenAI via
`.env`, guardrailed, RM approves before use).

`obsidian_vault/Clients/CL-XXXX.md` are censored static client pages (facts
only: profile, objectives, AUM, mandates, holdings, exposures, cash needs,
transactions, RM notes, theme-matched events). `scripts/market_api.py` already
fetches live Marketaux news per client sector but is a CLI, not wired into the
app.

Two capability gaps drive this PRD:

1. Nobody explains how aligned each client's portfolio actually is with their
   stated interests (objectives, risk profile, mandate, life events), and
   nobody raises the conflicts between what the client/portfolio implies and
   what the controlled `event_log.csv` says is really happening.
2. Live news exists as a script but is not part of the RM workflow, so the RM
   cannot see "who in my book is most affected by what is in the news today"
   nor get a grounded, reviewable recommendation draft from the static +
   alignment + news picture.

This PRD defines those two features. It deliberately does **not** invent new
risk calculations, product claims, or client-contact behaviour beyond what the
challenge and the existing workbench architecture allow.

---

## 2. Goals & non-goals

### Goals

- Produce, per client, an **alignment analysis** (static portfolio vs stated
  interest) using the censored Obsidian note as the LLM input, grounded in
  deterministic numbers computed locally.
- Detect and **raise conflicts to the RM** across three dimensions:
  1. risk profile & mandate bands/exclusions vs actual allocation;
  2. stated objectives / life events / cash needs vs portfolio exposure;
  3. controlled `event_log.csv` reality vs the client's stated interest or the
     portfolio's implied view.
- Display static facts + alignment + conflicts in the dashboard.
- On app load, run a **live Marketaux news loop** across all 20 clients
  (per-client sectors), cache results, and surface the **most affected
  clients** to the RM using exposure-weighted news relevance.
- Provide a **"Get recommendation"** action (RM-initiated, per client) that
  passes static + alignment + conflicts + latest news into the LLM and returns
  a structured, guardrailed draft for RM review. The RM stays the decision
  maker and applies their own judgement/profile knowledge.

### Non-goals

- No autonomous client contact, no execution, no approval of trades.
- No offline/fallback when API keys are missing: features require real keys and
  fail loudly at the feature level (do not silently fake data).
- No new persistence model beyond the local JSON patterns already used
  (`WorkbenchStore`); no bank-grade storage claims.
- No changes to the fixed five-snapshot data model or the curated instrument
  theme map. `event_log.csv` remains the authoritative 2026 event source; live
  news is a separate, clearly-labelled feed.

---

## 3. Architecture map & ownership

Existing modules:

- `app.py` — Streamlit orchestrator (pages: Home, Focus casebook,
  Client deep dive, Notes library, Market/Upstream context, Action record,
  Methods & governance). Holds UI copy and page wiring only.
- `src/singhacks26/intelligence.py` — deterministic analytics / compatibility
  adapter (mandate review, attribution, attention queue).
- `src/singhacks26/workbench.py` — household analytics + `WorkbenchStore`
  (local JSON workflow state in `obsidian_vault/workbench_state.json`).
- `src/singhacks26/ai_brief.py` — OpenAI client conventions, guardrails,
  structured output. **The reference pattern for every new LLM call.**
- `scripts/market_api.py` — Marketaux CLI (sector → query mapping, fetching).
  **Role 1 factors this into an importable module** so the app can use it.

New module layout (contract-first; files below are owned as stated):

| File                                                 | Owner              | Purpose                                                                              |
| ---------------------------------------------------- | ------------------ | ------------------------------------------------------------------------------------ |
| `src/singhacks26/alignment.py`                       | Role 0             | Deterministic fact packet + LLM alignment/conflict analysis + `AlignmentStore` cache |
| `src/singhacks26/news.py`                            | Role 1             | Importable Marketaux loop (refactored from `scripts/market_api.py`) + `NewsCache`    |
| `src/singhacks26/recommendation.py`                  | Role 1             | "Get recommendation" fact packet + guardrailed LLM draft                             |
| `app.py` edits                                       | Role 0 then Role 1 | Page/panel wiring (sequenced, see §7)                                                |
| `tests/test_alignment.py`                            | Role 0             | Offline tests for deterministic parts                                                |
| `tests/test_news.py`, `tests/test_recommendation.py` | Role 1             | Offline tests (LLM calls stubbed)                                                    |

`scripts/market_api.py` stays runnable as a CLI (Role 1 refactors it to import
the shared logic from `src/singhacks26/news.py`).

Execution order: **Role 0 lands and merges to `main` first, then Role 1 rebases
onto `main` and integrates.** This avoids two agents editing the same `app.py`
regions against different bases.

---

## 4. Feature A — Static alignment analysis & conflict surfacing (Role 0)

### 4.1 Inputs

- Censored static note: `obsidian_vault/Clients/CL-XXXX.md` (never the
  uncensored name/age; the note is already censored — keep it that way).
- Deterministic numbers computed locally from `data/*.csv` (latest snapshot
  2026-08-26): allocation by asset class per governed portfolio, mandate bands
  and exclusions (`portfolio_mandate_review`), concentration vs single-position
  limits, look-through exposure, sector/region exposures, liquidity tiers,
  planned cash needs vs liquid assets, facility LTV headroom, curated theme
  exposure.
- Controlled events: `event_log.csv` rows matched to the client by the existing
  theme lexicon / curated theme map (the note already lists matched events).

### 4.2 What "interest" means

Derived from the censored note + deterministic rows: stated objectives,
risk profile & horizon, life stage, source of wealth, mandate (incl.
sustainability exclusions), planned cash needs, and RM-note statements that are
already inside the censored page.

### 4.3 Alignment dimensions (per client)

1. **Risk-profile alignment** — risk profile/horizon/liquidity vs actual
   allocation & drawdown behaviour.
2. **Mandate alignment** — bands and binding exclusions vs holdings; single
   position/concentration limits.
3. **Objectives / life-event alignment** — portfolio vs stated objectives and
   dated cash needs (e.g. "diversify away from energy" vs energy exposure; a
   known tax bill vs available cash/liquidity).
4. **Event-consistency** — the client's stated interest or the portfolio's
   implied view vs what `event_log.csv` actually records (e.g. waiting for
   long bonds to recover while the event log records the duration shock; an
   enlarged gold view vs gold consolidation; energy thesis vs de-escalation
   scenarios; gated private credit vs a near-term USD need; tech single-name
   concentration after the June drawdown and 29 July rates event).

### 4.4 Output contract — `AlignmentReport`

Structured (pydantic, `responses.parse`, mirroring `ai_brief.py`):

```json
{
  "client_id": "CL-0003",
  "as_of": "2026-08-26",
  "overall_band": "partially_aligned",
  "dimensions": {
    "risk_profile_alignment": "misaligned",
    "mandate_alignment": "review",
    "objectives_life_event_alignment": "review",
    "event_consistency": "conflict"
  },
  "strengths": ["... one line each, evidence-referenced ..."],
  "conflicts": [
    {
      "conflict_id": "CL-0003-C-1",
      "category": "risk_profile | mandate | objectives | event",
      "severity": "Urgent | High | Medium | Low",
      "headline": "Inherited portfolio is not what a Conservative client believes she holds",
      "detail": "1-3 sentences, no invented numbers",
      "evidence_ids": ["note:Portfolios and AUM by snapshot", "mandates.csv",
                       "holdings.csv:2026-08-26", "event_log.csv:2026-02-28"],
      "discussion_topic": "RM opening topic, not advice"
    }
  ],
  "uncertainties": ["..."]
}
```

Rules:

- Numbers may only come from the local fact packet (reuse the numeric
  validation pattern from `ai_brief.validate_ai_draft`). The LLM must not
  introduce figures.
- Every conflict carries evidence IDs and a category + severity so the RM can
  defend it.
- Output is a review lead for the RM, not proof of causation and not advice.

### 4.5 Caching & refresh

- Computing 20 LLM analyses on every app rerun is unacceptable. Persist reports
  in `obsidian_vault/alignment_state.json` via an `AlignmentStore` class that
  mirrors `WorkbenchStore` (load/save/refresh decision).
- Refresh when the vault note file content hash changes, when a source CSV hash
  changes, or on an explicit "Re-analyse with AI" button. Store
  `model`, `generated_at`, and source hashes with each report.
- If `OPENAI_API_KEY` is absent: feature-level error message, app continues.

---

## 5. Feature B — Live news loop & "Get recommendation" (Role 1)

### 5.1 On-load news loop

- Factor `scripts/market_api.py` logic into `src/singhacks26/news.py`
  (keep the CLI as a thin wrapper so nothing breaks).
- On app load, iterate the 20 clients; for each, derive queryable sectors from
  latest-snapshot holdings (reuse `held_sectors`/`queries_for`), fetch
  Marketaux news, respecting rate limits (`group_similar`, de-dupe by `uuid`,
  sleep between calls) and the existing `SECTOR_QUERY` taxonomy.
- Cache results in `obsidian_vault/news_cache.json` (`NewsCache`) with
  `fetched_utc`, per-client sector entries, article `uuid/title/url/source/
  published_at/snippet/entities`, and any per-sector errors. Add a TTL so a
  plain rerun does not re-hit the API; provide a manual "Refresh news" button.
- If `MARKETAUX_API_KEY` is absent: show an explicit error in the news panel;
  the rest of the app keeps working (fail loudly at feature level).

### 5.2 Most-affected ranking

- Compute an exposure-weighted relevance score per client from cached news:
  sector exposure share (from holdings) × article relevance/similarity, summed
  over the client's sectors and recency.
- Present the ranked "Most affected clients right now" list to the RM with the
  driving headlines and the client's exposed sectors. Clearly label this as
  **live news** (as-of fetch time) to keep it distinct from the controlled
  `event_log.csv` surface.

### 5.3 "Get recommendation" (RM-initiated, per client)

- Button lives in the client-facing deep-dive area (see §6).
- On click, build a recommendation fact packet containing:
  - censored static note (or its fact section),
  - the client's `AlignmentReport` (Role 0 output contract, §4.4),
  - surfaced conflicts,
  - the latest cached news items relevant to the client's sectors,
  - deterministic numbers needed to reason (no invented figures).
- Call the LLM (OpenAI, same conventions as `ai_brief.py`) and return a
  structured, guardrailed `RecommendationDraft` for **RM review**:

```json
{
  "client_id": "CL-0005",
  "summary": "...",
  "alignment_and_conflicts_to_discuss": ["..."],
  "news_drivers": ["headline + why it matters for this client"],
  "rm_recommendation_topics": ["topics for RM to review, not orders"],
  "questions_to_ask": ["..."],
  "risks_and_uncertainties": ["..."],
  "evidence_ids": ["..."],
  "guardrail_note": "Draft for RM review; not investment advice"
}
```

- Guardrails: no invented numbers, no direct-advice phrasing ("you should
  buy/sell", guarantees, "will recover"), evidence ID allow-list — reuse the
  `ai_brief.py` validation helpers/patterns.
- The RM applies their own profile knowledge and judgement; the LLM draft is an
  input. The final reviewed output can be saved via the existing note/workflow
  store.

---

## 6. Dashboard (display + RM workflow)

- **Static + alignment + conflicts** (Feature A) must be shown: a new
  top-level page "Alignment & conflicts" (client selector, static summary from
  the censored note, alignment metrics per dimension, conflict cards with
  severity + evidence) **and** a compact alignment/conflict panel inside the
  existing Client deep dive page (header metrics row / dedicated tab).
- Surfaced conflicts should also feed the RM's prioritised attention: add the
  client's worst conflict to the "Home" problem list where applicable.
- **News** (Feature B): extend the Market/Upstream context page with a "Live
  news" panel showing fetch time, the most-affected ranked list, per-client
  headlines; keep the controlled event surface separate.
- **"Get recommendation"**: button in the Client deep dive page (near the
  Conversation brief area) labelled clearly as an RM action; render the draft,
  show evidence + guardrail status, and allow saving a reviewed note.

UI copy should keep the existing dark-theme style and the "human in the loop"
wording conventions already in `app.py`.

---

## 7. Integration sequencing & merge notes

1. Role 0 implements + merges `alignment.py`, `AlignmentStore`,
   `tests/test_alignment.py`, and wires the alignment page/panels into `app.py`
   (its own regions only).
2. Role 1 rebases onto `main`, refactors `news.py` (updating
   `scripts/market_api.py` to import it), implements `recommendation.py` +
   tests, and wires the news panel + recommendation button into `app.py`.
3. Both roles may build against the JSON contracts in §4.4 / §5.3 before the
   counterpart lands; Role 1 should use a fixture/stub `AlignmentReport` until
   Role 0's real output exists.
4. Keep `app.py` edits scoped to distinct regions to minimise conflicts. If
   conflicts do arise, resolve them on `main` per AGENTS.md.

---

## 8. Governance & compliance (non-negotiable)

- Provider boundary: anything sent to a live LLM/news provider is **censored**
  (market themes, synthetic instrument/exposure IDs, censored static note,
  structured numbers). Never send names, actual ages, raw uncensored
  `rm_notes.json`, or account-level PII. (Existing `app.py` governance page
  already states this.)
- `event_log.csv` is authoritative for 2026 world events. Live news is a
  separate, dated feed and must be labelled as such.
- No invented numbers, no direct-advice language, no guarantees. RM approves
  anything client-facing. Audit trail = evidence IDs + snapshot/fetch dates.
- New LLM modules follow `ai_brief.py` conventions (structured `parse`,
  guardrail validation, allow-listed evidence, RM review UI).
- Determinism first: any figure shown must be computed locally; LLM only
  interprets and prioritises supplied facts.

---

## 9. Acceptance criteria

1. Running the app with keys set shows, for every client, an alignment band,
   per-dimension status, strengths and a conflict list with evidence IDs.
2. Conflicts are raised to the RM in the dashboard (new page + deep-dive panel;
   worst conflict also appears in the attention ordering where sensible).
3. Conflict detection uses only the three agreed dimensions and cites
   `event_log.csv` only for the event-consistency dimension.
4. App load fetches latest Marketaux news per client sector once, caches it,
   and shows the most-affected ranking with exposure weighting; a rerun within
   the TTL does not re-hit the API; refresh button forces a new fetch.
5. The "Get recommendation" button passes static + alignment + conflicts +
   cached news to the LLM and renders a structured draft with evidence and a
   clear "not approved / RM review" state; the RM can save a reviewed note.
6. Missing `OPENAI_API_KEY` or `MARKETAUX_API_KEY` produces a clear feature
   error and does not crash the rest of the dashboard.
7. `uv run pytest` and `uv run ruff check .` pass; existing tests still pass.
8. No PII crosses the provider boundary (checked in code review / role tests).

---

## 10. Constraints

- Use uv only (no pip/poetry/conda). Add deps via `uv add` and commit
  `pyproject.toml` + `uv.lock`.
- Keep `app.py` as UI orchestrator; put domain logic in `src/singhacks26/`.
- Reuse existing patterns (`WorkbenchStore`, `ai_brief`, curated theme map,
  `THEMES`/`CURATED_THEMES`) instead of re-deriving them.
- No architectural changes without documenting them (add to this PRD).
