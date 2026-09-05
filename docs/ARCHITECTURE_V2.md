# RM Workbench v2 architecture

## Objective

Turn team-supplied insight into client-ready action while keeping the Relationship Manager in
control. Aurum is the RM Intelligence Workbench (Block 3); it does not replace the portfolio
explanation or proactive risk engines in Blocks 1 and 2.

```text
Block 1 portfolio explanation ─┐
                               ├─→ versioned, read-only evidence contract
Block 2 risk/event/scenario ───┘
                                            ↓
RM Intelligence Workbench (Aurum)
  attention ordering · relationship context · choice framing · call preparation
  RM judgement · suitability/tax escalation · accountable follow-through
                                            ↓
local action and conversation history

Approved fact packet → optional AI language draft → guardrails → RM review
```

## Ownership boundary

- Blocks 1 and 2 own attribution, concentration, liquidity, currency, collateral and mandate-risk
  detection, event mapping, scenario analysis, severity and the supporting calculations.
- Aurum receives those outputs as immutable evidence. It owns what they mean for this client,
  who the RM should attend to first, which choices need discussion, and what happens next.
- `intelligence.py` is a compatibility adapter that reconstructs upstream payloads only when this
  isolated hackathon demo is run without the other blocks. It is not the Block 3 product claim.
- `workbench.py` owns household presentation and local workflow persistence.
- `ai_brief.py` may rewrite an approved synthetic fact packet. It cannot calculate or approve.
- `app.py` orchestrates the RM workflow and does not originate financial-risk rules.

## RM-owned controls

- Client voice, objectives, mandate, tax domicile and life events remain visibly distinct.
- Three deep cases use hypotheses to test, questions to ask, signals to listen for and phrases to
  avoid—not automated advice.
- Choice framing carries rationale, prerequisites, trade-offs and required suitability or tax
  escalation.
- RM decisions, call plans and post-call reflections preserve evidence date and accountability.
- AI drafts are checked for invented numbers and direct-advice language before RM review.
- No autonomous client contact, tax conclusion, recommendation approval or trade execution.

## Integration contract

Each upstream signal should provide a stable ID, client and portfolio IDs, as-of date, category,
severity, observed facts, evidence references, assumptions, uncertainty and calculation version.
Aurum may prioritise and annotate the signal but must not silently alter its calculation or
provenance.

## Deliberate prototype limits

- Local JSON demonstrates workflow storage; it is not bank-grade immutable retention.
- Identity is displayed rather than authenticated through bank SSO.
- Local upstream reconstruction keeps the standalone demo usable until team integration.
- Choice frames are comparisons for discussion, not forecasts or optimisation.
- The curated theme map would come from an approved instrument master in production.
