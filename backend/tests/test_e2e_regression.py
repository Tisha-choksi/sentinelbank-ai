"""Formal end-to-end regression test (Item 6): the critical user journey
from login through detection, AI investigation, and human review, run
against the hermetic `api_client` fixture's own isolated SQLite database --
never a live server, and never the real demo database's alert IDs.

The LLM call is monkeypatched to a fast, deterministic fake (grounded in
whatever evidence actually ends up in the prompt) rather than hitting a
real Ollama server: a "formal" regression suite needs to run quickly and
reliably in CI, not depend on a local model server being up.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import models
from auth.security import hash_password
from investigation import graph as investigation_graph

ANALYST_EMAIL = "e2e-analyst@sentinelbank.ai"
ANALYST_PASSWORD = "E2eAnalystPass123!"
ADMIN_EMAIL = "e2e-admin@sentinelbank.ai"
ADMIN_PASSWORD = "E2eAdminPass123!"

RESULTS_DIR = Path(__file__).resolve().parent.parent / "evaluation" / "results"


def _make_users(session_factory) -> None:
    db = session_factory()
    try:
        db.add(
            models.User(
                email=ANALYST_EMAIL,
                full_name="E2E Analyst",
                hashed_password=hash_password(ANALYST_PASSWORD),
                role="ANALYST",
            )
        )
        db.add(
            models.User(
                email=ADMIN_EMAIL,
                full_name="E2E Admin",
                hashed_password=hash_password(ADMIN_PASSWORD),
                role="ADMIN",
            )
        )
        db.commit()
    finally:
        db.close()


def _seed_high_value_transaction(session_factory) -> int:
    """Inserts one synthetic high-value transaction directly, bypassing the
    `/api/v1/transactions` route's auto-detection-on-create -- so the admin's
    explicit `/detection/run` call below is actually the step that produces
    the alert, matching the checklist's own step ordering, not a side
    effect of transaction creation."""
    db = session_factory()
    try:
        txn = models.Transaction(
            transaction_ref=f"TXN-E2E-{datetime.now(timezone.utc).timestamp()}",
            from_account="ACC-E2E-SRC",
            to_account="ACC-E2E-DST",
            amount=Decimal("500000.00"),  # above FRAUD_HIGH_VALUE_THRESHOLD (200000)
            currency="INR",
            status="RECEIVED",
            created_at=datetime.now(timezone.utc),
        )
        db.add(txn)
        db.commit()
        return txn.id
    finally:
        db.close()


def _grounded_fake_llm(prompt: str, **_kwargs) -> dict:
    """Stands in for `investigation.llm_client.generate_json`. Grounds its
    citations in whatever primary transaction/accounts actually appear in
    the prompt, so the graph's anti-hallucination check passes regardless
    of which synthetic transaction this test created."""
    ref_match = re.search(r'"transaction_ref":\s*"([^"]+)"', prompt)
    from_match = re.search(r'"from_account":\s*"([^"]+)"', prompt)
    to_match = re.search(r'"to_account":\s*"([^"]+)"', prompt)
    cited_accounts = [m.group(1) for m in (from_match, to_match) if m]
    return {
        "summary": "Synthetic E2E regression report.",
        "confirmed_facts": ["High-value transaction confirmed in evidence."],
        "hypotheses": [],
        "uncertainties": [],
        "recommended_checks": ["Escalate to a human analyst for confirmation."],
        "cited_transaction_refs": [ref_match.group(1)] if ref_match else [],
        "cited_accounts": cited_accounts,
    }


def _snapshot_evaluation_results() -> dict[str, str]:
    """sha256 of every file under evaluation/results/, to prove this test
    run never touches the committed benchmark artifacts (checklist item 8)."""
    snapshot = {}
    if RESULTS_DIR.exists():
        for path in sorted(RESULTS_DIR.rglob("*")):
            if path.is_file():
                snapshot[str(path.relative_to(RESULTS_DIR))] = hashlib.sha256(
                    path.read_bytes()
                ).hexdigest()
    return snapshot


def test_critical_user_journey(api_client, monkeypatch):
    client, session_factory = api_client
    before = _snapshot_evaluation_results()

    monkeypatch.setattr(investigation_graph, "generate_json", _grounded_fake_llm)

    _make_users(session_factory)
    transaction_id = _seed_high_value_transaction(session_factory)

    # 1. Log in as an analyst.
    analyst_login = client.post(
        "/api/v1/auth/login",
        json={"email": ANALYST_EMAIL, "password": ANALYST_PASSWORD},
    )
    assert analyst_login.status_code == 200, analyst_login.text
    analyst_headers = {
        "Authorization": f"Bearer {analyst_login.json()['access_token']}"
    }

    # 2. Verify that analyst access cannot run admin-only detection.
    denied = client.post("/api/v1/detection/run", headers=analyst_headers)
    assert denied.status_code == 403
    assert set(denied.json().keys()) == {"detail", "request_id"}

    # 3. Log in as an administrator and run detection.
    admin_login = client.post(
        "/api/v1/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
    )
    assert admin_login.status_code == 200, admin_login.text
    admin_headers = {"Authorization": f"Bearer {admin_login.json()['access_token']}"}

    detection_res = client.post("/api/v1/detection/run", headers=admin_headers)
    assert detection_res.status_code == 200, detection_res.text
    matching_alerts = [
        a for a in detection_res.json() if a["transaction_id"] == transaction_id
    ]
    assert matching_alerts, "expected detection to raise an alert on the synthetic high-value transaction"
    alert_id = matching_alerts[0]["id"]

    # 4. Verify that an alert and investigation report are persisted.
    alerts_list = client.get("/api/v1/alerts", headers=admin_headers)
    assert alert_id in [a["id"] for a in alerts_list.json()]

    investigate_res = client.post(
        f"/api/v1/alerts/{alert_id}/investigate", headers=admin_headers
    )
    assert investigate_res.status_code == 201, investigate_res.text
    report = investigate_res.json()
    assert report["status"] == "PENDING_REVIEW"
    report_id = report["id"]

    reports_res = client.get(
        f"/api/v1/alerts/{alert_id}/reports", headers=admin_headers
    )
    assert any(r["id"] == report_id for r in reports_res.json())

    # 5. Submit a human review and verify reviewer identity and audit entry.
    review_res = client.post(
        f"/api/v1/reports/{report_id}/review",
        json={"status": "ESCALATED"},
        headers=analyst_headers,
    )
    assert review_res.status_code == 200, review_res.text
    reviewed = review_res.json()
    assert reviewed["status"] == "ESCALATED"
    assert reviewed["reviewed_by"] == "E2E Analyst"

    db = session_factory()
    try:
        audit_entries = (
            db.query(models.AuditLog)
            .filter(models.AuditLog.entity_type == "investigation_report")
            .filter(models.AuditLog.entity_id == report_id)
            .all()
        )
    finally:
        db.close()
    actions = {a.action for a in audit_entries}
    assert "AI_INVESTIGATION_COMPLETED" in actions
    assert "REPORT_ESCALATED" in actions
    escalation_entry = next(a for a in audit_entries if a.action == "REPORT_ESCALATED")
    assert escalation_entry.actor == ANALYST_EMAIL

    # 6. Attempt a duplicate review and expect 409 Conflict.
    duplicate_res = client.post(
        f"/api/v1/reports/{report_id}/review",
        json={"status": "APPROVED"},
        headers=admin_headers,
    )
    assert duplicate_res.status_code == 409
    assert set(duplicate_res.json().keys()) == {"detail", "request_id"}

    # 7. Verify request IDs and safe error responses.
    for res in (denied, review_res, duplicate_res):
        assert "x-request-id" in res.headers
    assert duplicate_res.json()["request_id"] == duplicate_res.headers["x-request-id"]

    # 8. Confirm that a clean test run leaves the original benchmark
    # artifacts untouched.
    after = _snapshot_evaluation_results()
    assert after == before
