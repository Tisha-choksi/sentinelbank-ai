"""The typed state threaded through the investigation graph. Each node
receives the current state and returns a partial update; LangGraph merges
updates into the running state between nodes.
"""

from __future__ import annotations

from typing import TypedDict

from investigation.contracts import EvidenceBundle, InvestigationFindings


class InvestigationState(TypedDict, total=False):
    alert_id: int
    alert_exists: bool
    evidence: EvidenceBundle | None
    validation_errors: list[str]
    findings: InvestigationFindings | None
    model_provider: str
    model_name: str
    error: str | None
    report_id: int | None
