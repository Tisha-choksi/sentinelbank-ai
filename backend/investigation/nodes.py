"""The four investigation graph nodes: retrieve verified evidence, validate
it, run the LLM and ground its citations, then persist the result. Each
node is a small factory that closes over whatever it needs (a DB session,
the LLM callable) and returns the actual node function LangGraph calls.
"""

from __future__ import annotations

import json
from dataclasses import asdict

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

import models
from investigation.contracts import (
    AccountEvidence,
    EvidenceBundle,
    InvestigationFindings,
    TransactionEvidence,
)
from investigation.llm_client import LLMError
from investigation.state import InvestigationState


def _to_txn_evidence(t: models.Transaction) -> TransactionEvidence:
    return TransactionEvidence(
        transaction_ref=t.transaction_ref,
        from_account=t.from_account,
        to_account=t.to_account,
        amount=str(t.amount),
        currency=t.currency,
        status=t.status,
        created_at=t.created_at.isoformat(),
    )


def _to_account_evidence(a: models.Account) -> AccountEvidence:
    return AccountEvidence(
        account_number=a.account_number,
        owner_name=a.owner_name,
        account_type=a.account_type,
        status=a.status,
    )


def make_retrieval_node(db: Session):
    """Node 1 — fetch the alert's transaction, any related transfers named
    in the alert's own evidence (e.g. velocity/circular-flow transaction
    refs), and whatever account registry records exist for the accounts
    involved. Anything referenced but not found is recorded, not silently
    dropped.
    """

    def retrieval_node(state: InvestigationState) -> dict:
        alert = db.get(models.Alert, state["alert_id"])
        if alert is None:
            return {
                "alert_exists": False,
                "error": f"Alert {state['alert_id']} does not exist.",
            }

        transaction = alert.transaction
        related_refs = set(alert.evidence.get("transaction_refs") or [])
        related_refs.discard(transaction.transaction_ref)

        related_transactions: list[TransactionEvidence] = []
        missing_evidence: list[str] = []
        if related_refs:
            found = (
                db.execute(
                    select(models.Transaction).where(
                        models.Transaction.transaction_ref.in_(related_refs)
                    )
                )
                .scalars()
                .all()
            )
            found_refs = {t.transaction_ref for t in found}
            related_transactions = [_to_txn_evidence(t) for t in found]
            for ref in sorted(related_refs - found_refs):
                missing_evidence.append(
                    f"Transaction '{ref}' referenced by the alert's evidence "
                    "was not found in the database."
                )

        account_numbers = {transaction.from_account, transaction.to_account}
        for t in related_transactions:
            account_numbers.add(t.from_account)
            account_numbers.add(t.to_account)

        known_account_rows = (
            db.execute(
                select(models.Account).where(
                    models.Account.account_number.in_(account_numbers)
                )
            )
            .scalars()
            .all()
        )
        known_accounts = [_to_account_evidence(a) for a in known_account_rows]
        registered_numbers = {a.account_number for a in known_account_rows}
        for number in sorted(account_numbers - registered_numbers):
            missing_evidence.append(
                f"Account '{number}' has no entry in the account registry "
                "(unregistered or simulated account)."
            )

        bundle = EvidenceBundle(
            alert_id=alert.id,
            rule_code=alert.rule_code,
            severity=alert.severity,
            alert_description=alert.description,
            alert_evidence=alert.evidence,
            primary_transaction=_to_txn_evidence(transaction),
            related_transactions=related_transactions,
            known_accounts=known_accounts,
            missing_evidence=missing_evidence,
        )
        return {"alert_exists": True, "evidence": bundle}

    return retrieval_node


def validation_node(state: InvestigationState) -> dict:
    """Node 2 — surface gaps in the retrieved evidence. This never hard-fails
    the investigation; missing evidence becomes an explicit uncertainty the
    model (and the human reviewer) is told about, rather than something the
    model has to guess around.
    """
    if state.get("error"):
        return {}
    evidence = state["evidence"]
    return {"validation_errors": list(evidence.missing_evidence)}


PROMPT_VERSION = "v2-strict-citation-rules"

_STRICT_RULES = """\
STRICT EVIDENCE AND CITATION RULES

1. You may cite a transaction or account only if it appears
   in the VERIFIED EVIDENCE section.

2. The KNOWN GAPS / NOT FOUND section is a list of unavailable
   evidence. It is NOT evidence that may be cited.

3. NEVER copy a transaction reference or account identifier
   from the KNOWN GAPS / NOT FOUND section into a citation list.

4. If a reference is missing, say that the record could not be
   retrieved. Do not claim that the underlying transaction
   did not occur.

5. If evidence is conflicting or incomplete, explicitly state:
   - What is confirmed
   - What is uncertain or conflicting
   - What additional information is needed

6. Do not infer fraud, intent, account ownership, or transaction
   status without supporting evidence.

7. If the available evidence is insufficient to reach a
   conclusion, state that the investigation is inconclusive.

8. Output only the required structured JSON.

These instructions do not override the application's independent
citation validation. Invalid citations must still be rejected."""


def _build_prompt(evidence: EvidenceBundle, validation_errors: list[str]) -> str:
    schema_example = {
        "summary": "one paragraph, plain language",
        "confirmed_facts": ["fact grounded in the evidence below"],
        "hypotheses": ["plausible but unconfirmed explanation"],
        "uncertainties": ["gap in the available evidence"],
        "recommended_checks": ["concrete next step for a human investigator"],
        "cited_transaction_refs": ["must be a transaction_ref listed below"],
        "cited_accounts": ["must be an account number listed below"],
    }
    lines = [
        "You are a banking fraud investigation assistant.",
        "",
        _STRICT_RULES,
        "",
        f"Alert rule: {evidence.rule_code} (severity: {evidence.severity})",
        f"Alert description: {evidence.alert_description}",
        f"Alert evidence: {json.dumps(evidence.alert_evidence)}",
        "",
        "VERIFIED EVIDENCE",
        "",
        "Primary transaction:",
        json.dumps(asdict(evidence.primary_transaction)),
        "",
        "Related transactions:",
        json.dumps([asdict(t) for t in evidence.related_transactions]),
        "",
        "Known accounts (registry records, may be incomplete):",
        json.dumps([asdict(a) for a in evidence.known_accounts]),
    ]
    if validation_errors:
        lines += [
            "",
            "KNOWN GAPS / NOT FOUND",
            "",
            "These references were expected but could not be retrieved. "
            "Treat each as an uncertainty to report, never as a citable "
            "transaction or account:",
            json.dumps(validation_errors),
        ]
    lines += [
        "",
        "Respond with ONLY a JSON object matching this exact schema "
        "(no markdown, no commentary):",
        json.dumps(schema_example),
    ]
    return "\n".join(lines)


def make_llm_node(llm_generate, *, model_provider: str, model_name: str):
    """Node 3 — draft the report, then ground every citation against the
    evidence bundle. A model failure (unreachable, bad JSON, wrong shape, or
    a citation that doesn't exist in the evidence) sets `error` rather than
    raising, so the persistence node can still record what happened.
    """

    def llm_node(state: InvestigationState) -> dict:
        if state.get("error"):
            return {}
        evidence = state["evidence"]
        prompt = _build_prompt(evidence, state.get("validation_errors", []))

        try:
            raw = llm_generate(prompt)
        except LLMError as exc:
            return {"error": f"Model generation failed: {exc}"}

        try:
            findings = InvestigationFindings.model_validate(raw)
        except ValidationError as exc:
            return {"error": f"Model returned a malformed report: {exc}"}

        known_refs = evidence.known_transaction_refs()
        known_accounts = evidence.known_account_numbers()
        ungrounded = [r for r in findings.cited_transaction_refs if r not in known_refs]
        ungrounded += [a for a in findings.cited_accounts if a not in known_accounts]
        if ungrounded:
            return {
                "error": (
                    "Model cited evidence that was not actually retrieved "
                    f"(possible hallucination): {ungrounded}"
                )
            }

        return {
            "findings": findings,
            "model_provider": model_provider,
            "model_name": model_name,
        }

    return llm_node


def make_persistence_node(db: Session):
    """Node 4 — persist the report (success or failure) and record an audit
    event. If the alert itself doesn't exist, there's nothing to attach a
    report to, so this is skipped entirely by the graph's routing.
    """

    def persistence_node(state: InvestigationState) -> dict:
        alert_id = state["alert_id"]
        alert = db.get(models.Alert, alert_id)
        evidence = state.get("evidence")
        evidence_snapshot = asdict(evidence) if evidence is not None else {}

        if state.get("error"):
            report = models.InvestigationReport(
                alert_id=alert_id,
                case_id=alert.case_id if alert else None,
                status="FAILED",
                model_provider=state.get("model_provider", "none"),
                model_name=state.get("model_name", "none"),
                prompt_version=PROMPT_VERSION,
                summary=f"Investigation did not complete: {state['error']}",
                findings={"error": state["error"]},
                evidence_snapshot=evidence_snapshot,
            )
            action = "AI_INVESTIGATION_FAILED"
        else:
            findings = state["findings"]
            report = models.InvestigationReport(
                alert_id=alert_id,
                case_id=alert.case_id if alert else None,
                status="PENDING_REVIEW",
                model_provider=state["model_provider"],
                model_name=state["model_name"],
                prompt_version=PROMPT_VERSION,
                summary=findings.summary,
                findings=findings.model_dump(),
                evidence_snapshot=evidence_snapshot,
            )
            action = "AI_INVESTIGATION_COMPLETED"

        db.add(report)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise
        db.refresh(report)

        audit = models.AuditLog(
            entity_type="investigation_report",
            entity_id=report.id,
            action=action,
            actor="system:ai-investigator",
            details=state.get("error") or f"Report #{report.id} generated",
        )
        db.add(audit)
        try:
            db.commit()
        except Exception:
            db.rollback()
            raise

        return {"report_id": report.id}

    return persistence_node
