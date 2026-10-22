"""Builds the investigation LangGraph and exposes a single entry point,
`run_investigation`, for the rest of the app to call. One graph, four
well-defined nodes — no autonomous multi-agent behavior; that's only worth
adding later if evaluation shows it's needed.
"""

from __future__ import annotations

from langgraph.graph import END, StateGraph
from sqlalchemy.orm import Session

import models
from investigation.llm_client import OLLAMA_MODEL, generate_json
from investigation.nodes import (
    make_llm_node,
    make_persistence_node,
    make_retrieval_node,
    validation_node,
)
from investigation.state import InvestigationState


class InvestigationError(RuntimeError):
    """Raised when the investigation cannot even be attempted, e.g. the
    alert id doesn't exist. Nothing is persisted in this case.
    """


def _route_after_retrieval(state: InvestigationState) -> str:
    return "validation" if state.get("alert_exists") else END


def build_graph(db: Session, llm_generate, *, model_provider: str, model_name: str):
    graph = StateGraph(InvestigationState)
    graph.add_node("retrieval", make_retrieval_node(db))
    graph.add_node("validation", validation_node)
    graph.add_node(
        "llm",
        make_llm_node(llm_generate, model_provider=model_provider, model_name=model_name),
    )
    graph.add_node("persistence", make_persistence_node(db))

    graph.set_entry_point("retrieval")
    graph.add_conditional_edges(
        "retrieval",
        _route_after_retrieval,
        {"validation": "validation", END: END},
    )
    graph.add_edge("validation", "llm")
    graph.add_edge("llm", "persistence")
    graph.add_edge("persistence", END)

    return graph.compile()


def run_investigation(
    db: Session,
    alert_id: int,
    *,
    llm_generate=None,
    model_provider: str = "ollama",
    model_name: str | None = None,
) -> models.InvestigationReport:
    """Run the full investigation graph for `alert_id` and return the
    persisted report. Raises InvestigationError if the alert doesn't exist
    (nothing to investigate or persist). A model/validation failure does
    NOT raise — it produces a report with status FAILED, visible to a human
    reviewer, since the alert itself is real and still needs attention.
    """
    generate = llm_generate or generate_json
    resolved_model_name = model_name or OLLAMA_MODEL

    compiled = build_graph(
        db, generate, model_provider=model_provider, model_name=resolved_model_name
    )
    final_state = compiled.invoke({"alert_id": alert_id})

    report_id = final_state.get("report_id")
    if report_id is None:
        raise InvestigationError(
            final_state.get("error", f"Alert {alert_id} does not exist.")
        )
    return db.get(models.InvestigationReport, report_id)
