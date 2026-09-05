# Role 1 — News Loop & "Get recommendation" (ralph checklist)

Identity: Role 1 / Coder B.
Branch: `role/1-news-recommendation` from `main`.
Scope: PRD §5 (Feature B), §6 news/recommendation display, §7 step 2.
Do NOT implement PRD §4 (alignment/conflict engine) — that is Role 0.

Execution order: Role 0 merges to `main` first. Rebase onto `main` after Role 0
lands so both `app.py` integrations share one base. You may develop the
recommendation flow against a fixture/stub `AlignmentReport` (PRD §4.4) before
Role 0's real output exists — the JSON contract is the interface.

Work top to bottom. Tick (`- [x]`) an item only when it is genuinely complete
and verified. When done, integrate back to `main` yourself (no PR).

---

## Phase 0 — Understand & align

- [x] Read `docs/PRD.md`, `docs/challenge.md`, `docs/ARCHITECTURE_V2.md`, and
      `docs/DATA_DICTIONARY.md`.
- [x] Read `scripts/market_api.py` end to end (sector query map, fetching,
      rate limiting, CLI), `src/singhacks26/ai_brief.py` (LLM conventions +
      guardrails), the censored vault note `obsidian_vault/Clients/CL-0005.md`,
      and the `app.py` deep-dive page + sidebar page list.
- [x] Confirm Role 0's `AlignmentReport` contract (PRD §4.4) is available on
      `main` after rebase; if not, keep building against a local stub fixture
      placed under `ralph/`.

## Phase 1 — Importable news module

- [x] Create `src/singhacks26/news.py` by refactoring `scripts/market_api.py`
      into importable functions: `held_sectors`, `queries_for`, `fetch_news`,
      the `SECTOR_QUERY` taxonomy, plus a `refresh_news(data) -> dict` that
      loops all 20 clients and returns per-client sector articles.
- [x] Refactor `scripts/market_api.py` to import from `news.py` so the CLI
      still works unchanged.
- [x] Respect rate limits: `group_similar`, de-dupe by `uuid`, sleep between
      calls; cap articles per sector as today.

## Phase 2 — NewsCache

- [x] Add a `NewsCache` class (JSON in `obsidian_vault/news_cache.json`):
      per-client sector entries with `uuid/title/url/source/published_at/
      snippet/entities`, per-sector errors, and a top-level `fetched_utc`.
- [x] Add a TTL (e.g. 1 hour) so plain app reruns within the TTL do not re-hit
      the API; expose `load()`, `save()`, `needs_refresh()`, and a manual
      force-refresh flag.
- [x] If `MARKETAUX_API_KEY` is missing: raise a clear feature-level error
      (do not fake data, do not crash the rest of the app).

## Phase 3 — Most-affected ranking

- [x] Add `most_affected(cache, holdings) -> DataFrame/records` computing an
      exposure-weighted relevance score per client (sector exposure share from
      latest-snapshot holdings × article relevance/recency, summed over the
      client's sectors).
- [x] Label output as **live news** with fetch time, distinct from the
      controlled `event_log.csv` surface.

## Phase 4 — Recommendation flow

- [x] Create `src/singhacks26/recommendation.py` with
      `build_recommendation_fact_packet(data, client_id, vault_text,
      alignment_report, news_items) -> dict`: censored static facts, the
      `AlignmentReport`, surfaced conflicts, latest cached news, deterministic
      numbers, and `allowed_evidence_ids`; mark `synthetic_data: True`.
- [x] Add `generate_recommendation(...) -> RecommendationDraft` calling OpenAI
      exactly as `ai_brief.draft_ai_brief` does (`responses.parse`, pydantic,
      `.env`).
- [x] pydantic `RecommendationDraft` must match PRD §5.3 (summary, topics for
      RM review not orders, questions, risks, evidence, guardrail note).
- [x] Reuse `ai_brief` guardrails: no invented numbers, no direct-advice
      phrasing, evidence allow-list. Fail loudly if `OPENAI_API_KEY` is
      missing.

## Phase 5 — Dashboard wiring

- [x] On app load, trigger the cached news refresh (`refresh_news` honouring
      the cache TTL) and compute the most-affected ranking.
- [x] Extend the Market/Upstream context page with a "Live news" panel:
      fetch time, ranked most-affected clients with driving headlines and
      exposed sectors; keep the controlled-event surface separate.
- [x] Add a clearly-labelled RM-initiated **"Get recommendation"** button in
      the Client deep dive page (near the Conversation brief area) that builds
      the fact packet, calls `generate_recommendation`, and renders the draft
      with evidence + an explicit "not approved / RM review" state.
- [x] Allow the RM to save a reviewed recommendation to the existing
      note/workflow store (reuse `save_vault_note`/`WorkbenchStore` patterns).
- [x] Keep rendering in `app.py`; domain logic stays in `news.py` /
      `recommendation.py`.

## Phase 6 — Tests

- [x] `tests/test_news.py`: sector-query mapping, exposure-weighted ranking,
      cache load/save/TTL — offline (no live API calls).
- [x] `tests/test_recommendation.py`: fact-packet assembly + guardrail
      validation against a stub `AlignmentReport` and stub news items (LLM
      call mocked/stubbed).
- [x] `uv run pytest` passes (new + existing tests).
- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass.

## Phase 7 — Verify & land

- [ ] Run the app with keys set: confirm one news fetch per session caches and
      reruns within TTL do not re-fetch; "Refresh news" forces a fetch; the
      recommendation button renders a guardrailed draft and saves a reviewed
      note.
- [x] Remove `MARKETAUX_API_KEY` and confirm the news panel errors clearly
      without crashing the dashboard; same check for `OPENAI_API_KEY` on the
      recommendation button.
- [x] Confirm no PII crosses the provider boundary (censored only).
- [x] Commit on `role/1-news-recommendation`, then integrate to `main` and tick
      the remaining items.
