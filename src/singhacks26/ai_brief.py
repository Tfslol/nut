"""Bounded AI rewriting for an evidence-backed RM call brief."""

import json
import os
import re

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

DEFAULT_MODEL = "gpt-5.6-luna"
DEFAULT_REASONING_EFFORT = "low"
SUPPORTED_REASONING_EFFORTS = {"none", "low", "medium", "high", "xhigh", "max"}
PROMPT_VERSION = "rm-call-brief/1.1"
NUMBER_PATTERN = re.compile(r"(?<![\w-])\d+(?:[.,]\d+)*(?:%|m|bn)?", re.IGNORECASE)
PROHIBITED_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\bguarantee(?:d|s)?\b",
        r"\byou should (?:buy|sell|invest)\b",
        r"\bwe recommend (?:buying|selling|investing)\b",
        r"\bwill recover\b",
        r"\bno risk\b",
    ]
]


class AICallBrief(BaseModel):
    """Strict output contract for an AI-prepared conversation draft."""

    why_call_now: str
    empathetic_opening: str
    client_tension: str
    questions_to_ask: list[str] = Field(min_length=2, max_length=4)
    options_to_review: list[str] = Field(min_length=1, max_length=3)
    uncertainties: list[str] = Field(min_length=1, max_length=4)
    evidence_ids: list[str] = Field(min_length=1)


def ai_is_configured() -> bool:
    """Return whether the local environment has an API key."""
    load_dotenv()
    return bool(os.getenv("OPENAI_API_KEY"))


def validate_ai_draft(draft: AICallBrief, fact_packet: dict) -> None:
    """Block new numeric claims and prohibited advisory language."""
    source = json.dumps(fact_packet, ensure_ascii=False)
    candidate = draft.model_dump_json()
    allowed_numbers = {token.lower() for token in NUMBER_PATTERN.findall(source)}
    candidate_numbers = {token.lower() for token in NUMBER_PATTERN.findall(candidate)}
    unsupported_numbers = candidate_numbers - allowed_numbers
    if unsupported_numbers:
        raise RuntimeError(
            f"AI draft introduced unsupported numeric claims: {sorted(unsupported_numbers)}"
        )
    for pattern in PROHIBITED_PATTERNS:
        if pattern.search(candidate):
            raise RuntimeError(
                f"AI draft failed the prohibited-language guardrail: {pattern.pattern}"
            )


def draft_ai_brief(fact_packet: dict) -> tuple[AICallBrief, str]:
    """Rewrite selected facts without granting tools or access to source files."""
    load_dotenv()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")

    model = os.getenv("OPENAI_MODEL", DEFAULT_MODEL)
    reasoning_effort = os.getenv("OPENAI_REASONING_EFFORT", DEFAULT_REASONING_EFFORT)
    if reasoning_effort not in SUPPORTED_REASONING_EFFORTS:
        supported = ", ".join(sorted(SUPPORTED_REASONING_EFFORTS))
        raise RuntimeError(
            f"Unsupported OPENAI_REASONING_EFFORT={reasoning_effort!r}. Use one of: {supported}."
        )
    allowed_evidence = set(fact_packet["allowed_evidence_ids"])
    client = OpenAI(api_key=api_key)
    response = client.responses.parse(
        model=model,
        store=False,
        max_output_tokens=900,
        text={"verbosity": "low"},
        reasoning={"effort": reasoning_effort, "context": "current_turn"},
        instructions=(
            "You prepare a private-bank relationship manager for a client call. "
            "Use only the supplied synthetic, pre-selected facts. Do not calculate, diagnose, "
            "predict markets, recommend a trade, promise an outcome, or add facts. Distinguish "
            "client beliefs from verified observations. Be empathetic, concise and suitable for "
            "a 60-second briefing. Options are topics for RM review, not advice. Explicitly name "
            "missing information. Cite only evidence IDs from allowed_evidence_ids."
        ),
        input=json.dumps(fact_packet, ensure_ascii=False),
        text_format=AICallBrief,
    )
    draft = response.output_parsed
    if draft is None:
        raise RuntimeError("The model did not return a structured brief.")
    unknown = set(draft.evidence_ids) - allowed_evidence
    if unknown:
        raise RuntimeError(f"AI returned unsupported evidence IDs: {sorted(unknown)}")
    validate_ai_draft(draft, fact_packet)
    return draft, model
