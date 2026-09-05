import pytest

from singhacks26.ai_brief import AICallBrief, validate_ai_draft


def draft(opening: str) -> AICallBrief:
    return AICallBrief(
        why_call_now="A confirmed USD 1m need is approaching.",
        empathetic_opening=opening,
        client_tension="Liquidity conflicts with the stated preference.",
        questions_to_ask=["Has the need changed?", "What should remain untouched?"],
        options_to_review=["Review a cash reserve."],
        uncertainties=["Tax treatment needs specialist confirmation."],
        evidence_ids=["CN-001"],
    )


FACTS = {
    "why_call_now": "A confirmed USD 1m need is approaching.",
    "allowed_evidence_ids": ["CN-001"],
}


def test_ai_guardrail_allows_only_existing_numbers():
    validate_ai_draft(draft("May we review the USD 1m need?"), FACTS)


def test_ai_guardrail_blocks_new_number():
    with pytest.raises(RuntimeError, match="unsupported numeric claims"):
        validate_ai_draft(draft("I suggest a USD 2m reserve."), FACTS)


def test_ai_guardrail_blocks_direct_advice():
    with pytest.raises(RuntimeError, match="prohibited-language"):
        validate_ai_draft(draft("You should sell the position."), FACTS)
