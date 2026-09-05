# Workbench analysis skills

These are application-level analytical capabilities, not autonomous agents.
Every skill returns evidence, confidence, assumptions, and a human-review flag.
Skills never place trades or contact clients.

The unit of analysis is always the client—not the news item. External market
data may update the body of an RM insight by explaining a change, challenging
an assumption or introducing a scenario. It must not create a client narrative
without support from the client's background, portfolio and approved notes.

## Event-to-exposure mapping

- Connect a controlled event or reviewed news item to relevant holdings,
  sectors, currencies and structured-product underlyings.
- Return affected clients, relevance, transmission path and evidence.
- Lexical matches are leads, not proof of causation.

## Aspiration-clash detection

- Compare client objectives and approved notes with observed portfolio exposure.
- Return the client statement, observed evidence, tension and open question.
- Never infer intent; label unstated conclusions as inference.

## Liquidity runway

- Compare cash needs and commitments with assets available by liquidity tier.
- Return dated funding gaps, available liquidity and uncertain valuations.
- Never treat gated or stale-valued assets as cash.

## Mandate and concentration review

- Detect allocation drift, concentration, sustainability exclusions and
  look-through exposure.
- Return the threshold, exposure, evidence and waiver status.
- Custody portfolios provide context but are not mandate breaches.

## Collateral watch

- Monitor lending value, LTV, headroom and market-sensitive collateral.
- Return current state, trend, trigger distance and stress observation.
- Never recommend borrowing or liquidation automatically.

## Conversation brief

- Synthesize deterministic risk, aspiration clashes and controlled event impacts
  into a brief consumable in approximately 60 seconds.
- Return why to call, client context, core tension, what changed, a suggested
  opening, questions, options to discuss, checks and an evidence trail.
- Use only reviewed outputs and source notes; disclose when the generic fallback
  has not established a specific clash.
- Conversation support only; the RM remains accountable for advice.

### Optional AI drafting

- Use `gpt-5.6-luna` through the Responses API with low reasoning effort,
  low verbosity and current-turn-only reasoning context for this bounded,
  latency-sensitive drafting workload.
- AI receives only the deterministic fact packet selected by the application,
  not direct file, database, MCP or web access.
- It may improve empathy, clarity and question framing but may not add facts,
  calculate risk, predict markets or recommend a trade.
- Structured output is required and evidence identifiers are validated against
  the supplied allow-list before display.
- API responses are requested with storage disabled. Every draft is visibly
  unapproved until reviewed by Priscilla.

## Client narrative synthesis

- Begin with life stage, source of wealth, objectives, risk tolerance and the
  client's own words in approved RM notes.
- Add portfolio evidence and market context only where they change what matters.
- Return a defensible narrative: background, belief, observed tension, why it matters today,
  suggested conversation, evidence and uncertainty.
- Prefer three deeply supported client narratives over twenty generic summaries.

## Data boundary

Raw client names, identifiers, holdings, tax details and RM notes remain local.
External providers receive only public instrument identifiers, market themes or
anonymous aggregate exposure requests. External results must be timestamped,
sourced and reviewed before they affect the RM attention order.
