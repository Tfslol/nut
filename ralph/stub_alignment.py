"""Placeholder AlignmentReport for Role 1 until Role 0's alignment engine lands.

Role 0 owns ``src/singhacks26/alignment.py`` and the real ``AlignmentReport``
contract (PRD §4.4). Until it merges, Role 1 builds against this stub so the
recommendation flow and its tests can run against a stable, contract-shaped
payload. Replace imports of this module with Role 0's module when it lands.

The shape matches PRD §4.4 exactly. Values are synthetic and intentionally
minimal; they exist only to exercise the fact packet + guardrails.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

SEVERITIES = ("Urgent", "High", "Medium", "Low")
CATEGORIES = ("risk_profile", "mandate", "objectives", "event")


class Conflict(BaseModel):
    conflict_id: str
    category: str
    severity: str
    headline: str
    detail: str
    evidence_ids: list[str] = Field(min_length=1)
    discussion_topic: str


class AlignmentReport(BaseModel):
    client_id: str
    as_of: str
    overall_band: str
    dimensions: dict[str, str]
    strengths: list[str]
    conflicts: list[Conflict] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)


def stub_alignment_report(client_id: str, as_of: str = "2026-08-26") -> dict:
    """Return a contract-shaped stub report for one client (no live analysis)."""
    report = AlignmentReport(
        client_id=client_id,
        as_of=as_of,
        overall_band="partially_aligned",
        dimensions={
            "risk_profile_alignment": "review",
            "mandate_alignment": "review",
            "objectives_life_event_alignment": "review",
            "event_consistency": "review",
        },
        strengths=["The portfolio is diversified across asset classes within the stated bands."],
        conflicts=[
            Conflict(
                conflict_id=f"{client_id}-C-1",
                category="mandate",
                severity="High",
                headline="Stub conflict pending Role 0's alignment engine",
                detail=(
                    "This placeholder conflict carries no invented numbers and will be "
                    "replaced by Role 0's real analysis."
                ),
                evidence_ids=["note:Mandates in scope", "mandates.csv"],
                discussion_topic="Confirm the client's mandate and any binding exclusions.",
            )
        ],
        uncertainties=["Real alignment analysis is not yet available on main."],
    )
    return report.model_dump()
