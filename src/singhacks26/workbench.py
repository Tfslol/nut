"""Deterministic analytics and local workflow state for the RM workbench."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pandas as pd

CURATED_THEMES = {
    "Energy and shipping": {
        "SYN-EQ-0008",
        "SYN-CM-0403",
        "SYN-ST-0101",
        "SYN-ST-0104",
        "SYN-EQ-0025",
        "SYN-SP-0501",
        "SYN-SP-0505",
    },
    "US technology and AI": {
        "SYN-EQ-0003",
        "SYN-ST-0102",
        "SYN-ST-0103",
        "SYN-SP-0501",
        "SYN-SP-0502",
        "SYN-AL-0308",
    },
    "Gold": {"SYN-CM-0401", "SYN-CM-0402", "SYN-SP-0504"},
    "Interest-rate duration": {
        "SYN-FI-0201",
        "SYN-FI-0203",
        "SYN-FI-0206",
        "SYN-FI-0207",
        "SYN-FI-0209",
        "SYN-FI-0210",
        "SYN-FI-0211",
        "SYN-FI-0212",
    },
    "Hong Kong property": {
        "SYN-ST-0106",
        "SYN-FI-0207",
        "SYN-SP-0503",
        "SYN-AL-0307",
    },
    "Private markets and gated vehicles": {
        "SYN-AL-0301",
        "SYN-AL-0302",
        "SYN-AL-0305",
        "SYN-AL-0306",
        "SYN-AL-0307",
        "SYN-AL-0308",
        "SYN-AL-0309",
    },
}


def snapshot_history(holdings: pd.DataFrame, client_id: str) -> pd.DataFrame:
    """Return household value and change across every supplied snapshot."""
    rows = holdings.loc[holdings.client_id == client_id]
    history = (
        rows.groupby("snapshot_date", as_index=False)
        .market_value_usd.sum()
        .sort_values("snapshot_date")
        .rename(columns={"market_value_usd": "household_value_usd"})
    )
    history["change_usd"] = history.household_value_usd.diff()
    history["change_pct"] = history.household_value_usd.pct_change().mul(100)
    return history


def liquidity_profile(holdings: pd.DataFrame, client_id: str, snapshot: str) -> pd.DataFrame:
    """Aggregate the household by the source-defined liquidity tiers."""
    rows = holdings.loc[(holdings.client_id == client_id) & (holdings.snapshot_date == snapshot)]
    total = rows.market_value_usd.sum()
    profile = (
        rows.groupby("liquidity_tier", as_index=False)
        .market_value_usd.sum()
        .sort_values("market_value_usd", ascending=False)
    )
    profile["weight_pct"] = profile.market_value_usd.div(total).mul(100).round(1)
    return profile


def lookthrough_exposure(
    holdings: pd.DataFrame,
    instruments: pd.DataFrame,
    client_id: str,
    snapshot: str,
) -> pd.DataFrame:
    """Expose wrapper references while retaining direct holdings as separate rows."""
    rows = holdings.loc[
        (holdings.client_id == client_id) & (holdings.snapshot_date == snapshot)
    ].merge(
        instruments[["instrument_id", "underlying_reference"]],
        on="instrument_id",
        how="left",
    )
    rows["economic_reference"] = rows.underlying_reference.fillna("").str.strip()
    rows.loc[rows.economic_reference == "", "economic_reference"] = rows.loc[
        rows.economic_reference == "", "instrument_name"
    ]
    total = rows.market_value_usd.sum()
    result = rows[
        [
            "instrument_id",
            "instrument_name",
            "asset_class",
            "sector",
            "liquidity_tier",
            "economic_reference",
            "market_value_usd",
        ]
    ].copy()
    result["household_weight_pct"] = result.market_value_usd.div(total).mul(100).round(2)
    return result.sort_values("market_value_usd", ascending=False)


def theme_exposure(holdings: pd.DataFrame, client_id: str, snapshot: str) -> pd.DataFrame:
    """Apply a published, hand-checked theme map to household holdings."""
    rows = holdings.loc[(holdings.client_id == client_id) & (holdings.snapshot_date == snapshot)]
    total = float(rows.market_value_usd.sum())
    results = []
    for theme, instrument_ids in CURATED_THEMES.items():
        members = rows.loc[rows.instrument_id.isin(instrument_ids)]
        value = float(members.market_value_usd.sum())
        if value:
            results.append(
                {
                    "theme": theme,
                    "market_value_usd": value,
                    "household_weight_pct": round(value / total * 100, 2),
                    "instruments": int(members.instrument_id.nunique()),
                    "source": "Published instrument-id mapping",
                }
            )
    return pd.DataFrame(results).sort_values("market_value_usd", ascending=False)


class WorkbenchStore:
    """Small append-only JSON store for tasks, referrals and audit events."""

    def __init__(self, path: Path):
        self.path = path

    def read(self) -> dict:
        if not self.path.exists():
            return {
                "schema_version": "rm-workflow/1.1",
                "tasks": [],
                "comparisons": [],
                "decisions": [],
                "conversation_outcomes": [],
                "call_plan_versions": [],
                "audit": [],
            }
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {
                "schema_version": "rm-workflow/1.1",
                "tasks": [],
                "comparisons": [],
                "decisions": [],
                "conversation_outcomes": [],
                "call_plan_versions": [],
                "audit": [],
            }
        payload.setdefault("tasks", [])
        payload.setdefault("comparisons", payload.pop("scenarios", []))
        payload.setdefault("decisions", [])
        payload.setdefault("conversation_outcomes", [])
        payload.setdefault("call_plan_versions", payload.pop("meeting_versions", []))
        payload.setdefault("audit", [])
        return payload

    def save_comparison(
        self,
        *,
        client_id: str,
        name: str,
        inputs: dict,
        outputs: dict,
        assumptions: list[str],
        evidence_version: str,
        actor: str = "Priscilla Ong",
    ) -> dict:
        payload = self.read()
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        comparison = {
            "comparison_id": f"comparison-{uuid4().hex[:10]}",
            "client_id": client_id,
            "name": name,
            "inputs": inputs,
            "outputs": outputs,
            "assumptions": assumptions,
            "calculation_version": "decision-lens/1.0",
            "evidence_version": evidence_version,
            "created_at": timestamp,
            "created_by": actor,
        }
        payload["comparisons"].append(comparison)
        payload["audit"].append(
            {
                "event_id": f"audit-{uuid4().hex[:10]}",
                "timestamp": timestamp,
                "origin": "user_decision",
                "actor": actor,
                "action": "decision_comparison_saved",
                "client_id": client_id,
                "object_id": comparison["comparison_id"],
                "detail": {
                    "name": name,
                    "calculation_version": comparison["calculation_version"],
                },
            }
        )
        self._write(payload)
        return comparison

    def add_task(
        self,
        *,
        client_id: str,
        title: str,
        owner: str,
        due_date: str,
        task_type: str,
        evidence_ref: str,
        actor: str = "Priscilla Ong",
    ) -> dict:
        payload = self.read()
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        task = {
            "task_id": f"task-{uuid4().hex[:10]}",
            "client_id": client_id,
            "type": task_type,
            "title": title.strip(),
            "owner": owner.strip(),
            "due_date": due_date,
            "status": "open",
            "evidence_ref": evidence_ref,
            "created_at": timestamp,
            "created_by": actor,
        }
        payload["tasks"].append(task)
        payload["audit"].append(
            {
                "event_id": f"audit-{uuid4().hex[:10]}",
                "timestamp": timestamp,
                "origin": "user_decision",
                "actor": actor,
                "action": "task_created",
                "client_id": client_id,
                "object_id": task["task_id"],
                "detail": {"title": task["title"], "owner": task["owner"]},
            }
        )
        self._write(payload)
        return task

    def update_task(
        self,
        *,
        task_id: str,
        status: str,
        rationale: str,
        actor: str = "Priscilla Ong",
    ) -> dict:
        if status not in {"open", "in_progress", "complete", "cancelled"}:
            raise ValueError(f"Unsupported task status: {status}")
        payload = self.read()
        task = next((item for item in payload["tasks"] if item["task_id"] == task_id), None)
        if task is None:
            raise ValueError(f"Unknown task_id: {task_id}")
        prior_state = task["status"]
        task["status"] = status
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        payload["audit"].append(
            {
                "event_id": f"audit-{uuid4().hex[:10]}",
                "timestamp": timestamp,
                "origin": "user_decision",
                "actor": actor,
                "action": "task_status_updated",
                "client_id": task["client_id"],
                "object_id": task_id,
                "detail": {
                    "prior_state": prior_state,
                    "new_state": status,
                    "rationale": rationale.strip(),
                },
            }
        )
        self._write(payload)
        return task

    def record_conversation_outcome(
        self,
        *,
        client_id: str,
        disposition: str,
        client_statement: str,
        rm_interpretation: str,
        requested_documents: list[str],
        actor: str = "Priscilla Ong",
    ) -> dict:
        payload = self.read()
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        outcome = {
            "outcome_id": f"outcome-{uuid4().hex[:10]}",
            "client_id": client_id,
            "disposition": disposition,
            "client_statement": client_statement.strip(),
            "rm_interpretation": rm_interpretation.strip(),
            "requested_documents": requested_documents,
            "recorded_at": timestamp,
            "recorded_by": actor,
        }
        payload["conversation_outcomes"].append(outcome)
        payload["audit"].append(
            {
                "event_id": f"audit-{uuid4().hex[:10]}",
                "timestamp": timestamp,
                "origin": "user_decision",
                "actor": actor,
                "action": "conversation_outcome_recorded",
                "client_id": client_id,
                "object_id": outcome["outcome_id"],
                "detail": {
                    "disposition": disposition,
                    "requested_documents": requested_documents,
                },
            }
        )
        self._write(payload)
        return outcome

    def record_decision(
        self,
        *,
        client_id: str,
        decision: str,
        rationale: str,
        evidence_version: str,
        original_next_step: str = "",
        gates: dict[str, bool] | None = None,
        actor: str = "Priscilla Ong",
    ) -> dict:
        payload = self.read()
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        previous = next(
            (
                item["decision"]
                for item in reversed(payload["decisions"])
                if item["client_id"] == client_id
            ),
            "new",
        )
        record = {
            "decision_id": f"decision-{uuid4().hex[:10]}",
            "client_id": client_id,
            "decision": decision,
            "prior_state": previous,
            "rationale": rationale.strip(),
            "original_next_step": original_next_step,
            "gates": gates or {},
            "evidence_version": evidence_version,
            "actor": actor,
            "timestamp": timestamp,
        }
        payload["decisions"].append(record)
        payload["audit"].append(
            {
                "event_id": f"audit-{uuid4().hex[:10]}",
                "timestamp": timestamp,
                "origin": "user_decision",
                "actor": actor,
                "action": "rm_decision_recorded",
                "client_id": client_id,
                "object_id": f"{client_id}-primary-insight",
                "detail": {
                    "prior_state": previous,
                    "decision": decision,
                    "rationale": rationale.strip(),
                    "evidence_version": evidence_version,
                },
            }
        )
        self._write(payload)
        return record

    def save_call_plan_version(
        self,
        *,
        client_id: str,
        content: str,
        evidence_version: str,
        reason: str,
        actor: str = "Priscilla Ong",
    ) -> dict:
        payload = self.read()
        client_versions = [
            item for item in payload["call_plan_versions"] if item["client_id"] == client_id
        ]
        timestamp = datetime.now(UTC).isoformat(timespec="seconds")
        version = {
            "call_plan_version_id": f"callplan-{uuid4().hex[:10]}",
            "client_id": client_id,
            "version": len(client_versions) + 1,
            "content": content.strip(),
            "evidence_version": evidence_version,
            "reason": reason.strip(),
            "actor": actor,
            "timestamp": timestamp,
        }
        payload["call_plan_versions"].append(version)
        payload["audit"].append(
            {
                "event_id": f"audit-{uuid4().hex[:10]}",
                "timestamp": timestamp,
                "origin": "user_decision",
                "actor": actor,
                "action": "call_plan_version_saved",
                "client_id": client_id,
                "object_id": version["call_plan_version_id"],
                "detail": {"version": version["version"], "reason": reason.strip()},
            }
        )
        self._write(payload)
        return version

    def _write(self, payload: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temporary.replace(self.path)
