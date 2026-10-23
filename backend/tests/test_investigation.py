"""Tests for the investigation graph: missing evidence, invalid alerts,
model failures, repeated runs, and database rollback behavior. These run
against the in-memory SQLite fixture with fake LLM callables, never a real
Ollama server.
"""

import re
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

import models
from investigation.graph import InvestigationError, run_investigation
from investigation.llm_client import LLMError


def _make_transaction(
    db,
    *,
    transaction_ref,
    amount=Decimal("300000.00"),
    from_account="ACC-X",
    to_account="ACC-Y",
):
    txn = models.Transaction(
        transaction_ref=transaction_ref,
        from_account=from_account,
        to_account=to_account,
        amount=amount,
        currency="INR",
        status="RECEIVED",
        created_at=datetime.now(timezone.utc),
    )
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


def _make_alert(db, transaction, *, rule_code="TXN_HIGH_VALUE", evidence=None):
    alert = models.Alert(
        transaction_id=transaction.id,
        rule_code=rule_code,
        severity="HIGH",
        status="OPEN",
        description="Test alert",
        evidence=evidence or {},
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


def _good_llm(prompt: str) -> dict:
    """A fake LLM that always grounds its citations in whatever the
    *actual* primary transaction in the prompt is, so it succeeds
    regardless of which test fixture transaction it's investigating.
    """
    ref_match = re.search(r'"transaction_ref":\s*"([^"]+)"', prompt)
    from_match = re.search(r'"from_account":\s*"([^"]+)"', prompt)
    to_match = re.search(r'"to_account":\s*"([^"]+)"', prompt)
    cited_accounts = [m.group(1) for m in (from_match, to_match) if m]
    return {
        "summary": "Test summary.",
        "confirmed_facts": ["fact"],
        "hypotheses": [],
        "uncertainties": [],
        "recommended_checks": [],
        "cited_transaction_refs": [ref_match.group(1)] if ref_match else [],
        "cited_accounts": cited_accounts,
    }


class TestInvalidAlert:
    def test_nonexistent_alert_raises_and_persists_nothing(self, db_session):
        with pytest.raises(InvestigationError):
            run_investigation(db_session, 9999, llm_generate=_good_llm)
        assert db_session.query(models.InvestigationReport).count() == 0


class TestMissingEvidence:
    def test_dangling_evidence_reference_is_surfaced_not_fatal(self, db_session):
        txn = _make_transaction(db_session, transaction_ref="TXN-1")
        alert = _make_alert(
            db_session,
            txn,
            rule_code="TXN_VELOCITY",
            evidence={"transaction_refs": ["TXN-1", "TXN-GHOST"]},
        )

        captured = {}

        def llm(prompt):
            captured["prompt"] = prompt
            return _good_llm(prompt)

        report = run_investigation(db_session, alert.id, llm_generate=llm)

        assert report.status == "PENDING_REVIEW"
        assert "TXN-GHOST" in captured["prompt"]
        assert "not found in the database" in captured["prompt"]

    def test_unregistered_account_is_surfaced_not_fatal(self, db_session):
        # Neither ACC-X nor ACC-Y has an accounts-table entry in this test,
        # which is the normal case today (transactions use free-text
        # accounts, not a required FK) -- this must not block a report.
        txn = _make_transaction(db_session, transaction_ref="TXN-1B")
        alert = _make_alert(db_session, txn)

        report = run_investigation(db_session, alert.id, llm_generate=_good_llm)
        assert report.status == "PENDING_REVIEW"
        assert any(
            "account registry" in item
            for item in report.evidence_snapshot.get("missing_evidence", [])
        )


class TestModelFailures:
    def test_llm_connection_failure_produces_failed_report(self, db_session):
        txn = _make_transaction(db_session, transaction_ref="TXN-2")
        alert = _make_alert(db_session, txn)

        def broken_llm(prompt):
            raise LLMError("connection refused")

        report = run_investigation(db_session, alert.id, llm_generate=broken_llm)
        assert report.status == "FAILED"
        assert "connection refused" in report.summary

    def test_malformed_output_produces_failed_report(self, db_session):
        txn = _make_transaction(db_session, transaction_ref="TXN-3")
        alert = _make_alert(db_session, txn)

        def malformed_llm(prompt):
            return {"not_the_right_shape": True}

        report = run_investigation(db_session, alert.id, llm_generate=malformed_llm)
        assert report.status == "FAILED"

    def test_hallucinated_citation_produces_failed_report(self, db_session):
        txn = _make_transaction(db_session, transaction_ref="TXN-4")
        alert = _make_alert(db_session, txn)

        def hallucinating_llm(prompt):
            return {
                "summary": "x",
                "cited_transaction_refs": ["TXN-DOES-NOT-EXIST"],
                "cited_accounts": [],
            }

        report = run_investigation(db_session, alert.id, llm_generate=hallucinating_llm)
        assert report.status == "FAILED"
        assert "hallucination" in report.summary.lower()


class TestRepeatedRuns:
    def test_rerunning_creates_a_new_report_each_time(self, db_session):
        txn = _make_transaction(db_session, transaction_ref="TXN-5")
        alert = _make_alert(db_session, txn)

        report1 = run_investigation(db_session, alert.id, llm_generate=_good_llm)
        report2 = run_investigation(db_session, alert.id, llm_generate=_good_llm)

        assert report1.id != report2.id
        count = (
            db_session.query(models.InvestigationReport)
            .filter_by(alert_id=alert.id)
            .count()
        )
        assert count == 2

    def test_rerun_after_failure_can_succeed(self, db_session):
        txn = _make_transaction(db_session, transaction_ref="TXN-6")
        alert = _make_alert(db_session, txn)

        def broken_llm(prompt):
            raise LLMError("timeout")

        failed = run_investigation(db_session, alert.id, llm_generate=broken_llm)
        assert failed.status == "FAILED"

        succeeded = run_investigation(db_session, alert.id, llm_generate=_good_llm)
        assert succeeded.status == "PENDING_REVIEW"
        assert succeeded.id != failed.id


class TestRollbackBehavior:
    def test_invalid_report_status_is_rejected_and_session_stays_usable(
        self, db_session
    ):
        txn = _make_transaction(db_session, transaction_ref="TXN-7")
        alert = _make_alert(db_session, txn)

        bad_report = models.InvestigationReport(
            alert_id=alert.id,
            status="NOT_A_REAL_STATUS",
            model_provider="test",
            model_name="test",
            summary="bad",
            findings={},
            evidence_snapshot={},
        )
        db_session.add(bad_report)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()

        assert db_session.query(models.InvestigationReport).count() == 0

        # The session must still be usable after the rollback.
        report = run_investigation(db_session, alert.id, llm_generate=_good_llm)
        assert report.status == "PENDING_REVIEW"
