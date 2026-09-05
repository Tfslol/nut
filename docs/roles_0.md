# Role 0 — Alignment & Conflict Engine (ralph checklist)

Identity: Role 0 / Coder A.
Branch: `role/0-alignment-engine` from `main`.
Scope: PRD §4 (Feature A) and §6 dashboard display for alignment, §7 step 1.
Do NOT implement PRD §5 (news loop / recommendation) — that is Role 1.

Work top to bottom. Tick (`- [x]`) an item only when it is genuinely complete
and verified. When done, integrate back to `main` yourself (no PR).

---

## Phase 0 — Understand & align

- [ ] Read `docs/PRD.md`, `docs/challenge.md`, `docs/ARCHITECTURE_V2.md`, and
      `docs/DATA_DICTIONARY.md` before coding.
- [ ] Read `app.py` (`load_data`, `build_event_impacts`, `case_facts`,
      `render_call_brief`, deep-dive page, sidebar page list), the censored
      vault notes (`obsidian_vault/Clients/CL-0001.md` and `CL-0003.md`), and
      `src/singhacks26/ai_brief.py` (LLM conventions + guardrails).
- [ ] Confirm the `AlignmentReport` JSON contract in PRD §4.4 is sufficient;
      if not, propose a change to the PRD before diverging.

## Phase 1 — Deterministic fact packet

- [ ] Create `src/singhacks26/alignment.py` with a
      `build_alignment_fact_packet(data, client_id, vault_text) -> dict` that
      computes locally (never trusts the LLM for numbers):
      allocation by asset class per governed portfolio, mandate bands +
      binding exclusions (reuse `portfolio_mandate_review`),
      concentration vs single-position limits, look-through exposure,
      sector/region exposures (latest snapshot 2026-08-26), liquidity tiers,
      planned cash needs vs liquid assets, facility LTV headroom, curated
      theme exposure, and the `event_log.csv` rows matched to this client
      (theme lexicon as used by `app.build_event_impacts`).
- [ ] Include `allowed_evidence_ids` in the packet (note section names, data
      file names, event ids/dates) and mark `synthetic_data: True`.
- [ ] Add unit tests for the fact packet builder against real `data/` rows
      (`tests/test_alignment.py`); assert no uncensored name/actual age leaks
      into the packet.

## Phase 2 — LLM alignment analysis

- [ ] In `alignment.py`, add `analyze_alignment(data, client_id, vault_text)`
      that calls the OpenAI API the same way as `ai_brief.draft_ai_brief`
      (`responses.parse`, pydantic output, reads `.env`).
- [ ] Use pydantic models for `AlignmentReport`, `Conflict`, and dimensions
      matching PRD §4.4 exactly (fields, severities, categories).
- [ ] Reuse `ai_brief` validation patterns: reject any number the model
      introduced that is not in the fact packet; reject direct-advice /
      guarantee phrasing; reject evidence IDs outside the allow-list.
- [ ] Treat `event_log.csv` as authoritative ground truth: the
      event-consistency dimension may only cite events present in the file.
- [ ] Fail loudly if `OPENAI_API_KEY` is missing (feature-level error), per
      PRD §2 / §8.

## Phase 3 — AlignmentStore cache

- [ ] Add an `AlignmentStore` class in `alignment.py` mirroring
      `WorkbenchStore` (JSON in `obsidian_vault/alignment_state.json`):
      per-client report + `model`, `generated_at`, vault-note content hash,
      and source-CSV hash for refresh decisions.
- [ ] Skip re-analysis on rerun when hashes are unchanged; expose a
      force/refresh path and a `list_reports()` for the UI.

## Phase 4 — Conflict surfacing to the RM

- [ ] Build a deterministic `conflict_inbox(reports) -> DataFrame/records`
      ranking conflicts across clients by severity/category so the UI can show
      which clients to look at first.
- [ ] Ensure each surfaced conflict carries evidence IDs and a discussion
      topic (PRD §4.4) and is labelled as a review lead, not causation.

## Phase 5 — Dashboard display

- [ ] Wire a new top-level "Alignment & conflicts" page into `app.py`'s
      sidebar page list: client selector, static summary from the censored
      note, alignment metrics per dimension, and conflict cards with severity
      badges + evidence + download of the report JSON.
- [ ] Add a compact alignment/conflict panel or tab inside the Client deep
      dive page (PRD §6): band metric, dimension statuses, top conflicts.
- [ ] Where applicable, add the client's worst conflict to the "Attention
      map" problem list so conflicts reach the RM's prioritised attention.
- [ ] Keep UI copy in the existing style/voice and all rendering in `app.py`
      (no UI logic in `alignment.py`).

## Phase 6 — Verify & land

- [ ] `uv run pytest` passes (new + existing tests).
- [ ] `uv run ruff check .` and `uv run ruff format --check .` pass.
- [ ] Run the app (`uv run streamlit run app.py` is the dev flow; if not
      already a task, run `python -m streamlit run app.py` from repo root) with
      keys set and confirm reports generate and render; confirm the
      feature-level error message appears when the key is removed.
- [ ] Confirm no PII crosses the provider boundary (censored only).
- [ ] Commit on `role/0-alignment-engine`, then integrate to `main` and tick
      the remaining items. Leave PRD §5 untouched for Role 1.
