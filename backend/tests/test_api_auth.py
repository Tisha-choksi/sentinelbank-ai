"""Tests for authentication, role-based access control, and the
review-endpoint integrity fixes: reviewer identity comes from the
authenticated session (never a client-supplied name), and duplicate /
concurrent review attempts on the same report are rejected, not silently
overwritten.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from decimal import Decimal

import models
from auth.security import hash_password

ANALYST_EMAIL = "test-analyst@sentinelbank.ai"
ANALYST_PASSWORD = "AnalystPass123!"
ADMIN_EMAIL = "test-admin@sentinelbank.ai"
ADMIN_PASSWORD = "AdminPass123!"


def _make_users(session_factory):
    db = session_factory()
    try:
        db.add(
            models.User(
                email=ANALYST_EMAIL,
                full_name="Test Analyst",
                hashed_password=hash_password(ANALYST_PASSWORD),
                role="ANALYST",
            )
        )
        db.add(
            models.User(
                email=ADMIN_EMAIL,
                full_name="Test Admin",
                hashed_password=hash_password(ADMIN_PASSWORD),
                role="ADMIN",
            )
        )
        db.commit()
    finally:
        db.close()


def _login(client, email, password):
    res = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth_headers(token):
    return {"Authorization": f"Bearer {token}"}


def _make_alert_with_report(session_factory) -> tuple[int, int]:
    """Inserts a transaction -> alert -> pending report chain directly,
    bypassing detection/investigation (those are covered elsewhere); returns
    (alert_id, report_id)."""
    db = session_factory()
    try:
        txn = models.Transaction(
            transaction_ref=f"TXN-AUTH-TEST-{datetime.now().timestamp()}",
            from_account="ACC-A",
            to_account="ACC-B",
            amount=Decimal("300000.00"),
            currency="INR",
            status="RECEIVED",
            created_at=datetime.now(timezone.utc),
        )
        db.add(txn)
        db.commit()
        db.refresh(txn)

        alert = models.Alert(
            transaction_id=txn.id,
            rule_code="TXN_HIGH_VALUE",
            severity="HIGH",
            status="OPEN",
            description="test alert",
            evidence={},
        )
        db.add(alert)
        db.commit()
        db.refresh(alert)

        report = models.InvestigationReport(
            alert_id=alert.id,
            status="PENDING_REVIEW",
            model_provider="ollama",
            model_name="llama3.1:8b",
            prompt_version="v2-strict-citation-rules",
            summary="test summary",
            findings={
                "summary": "test",
                "confirmed_facts": [],
                "hypotheses": [],
                "uncertainties": [],
                "recommended_checks": [],
                "cited_transaction_refs": [],
                "cited_accounts": [],
            },
            evidence_snapshot={},
        )
        db.add(report)
        db.commit()
        db.refresh(report)
        return alert.id, report.id
    finally:
        db.close()


class TestLogin:
    def test_login_succeeds_with_correct_credentials(self, api_client):
        client, session_factory = api_client
        _make_users(session_factory)

        res = client.post(
            "/api/v1/auth/login",
            json={"email": ANALYST_EMAIL, "password": ANALYST_PASSWORD},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["role"] == "ANALYST"
        assert body["token_type"] == "bearer"
        assert body["access_token"]

    def test_login_fails_with_wrong_password(self, api_client):
        client, session_factory = api_client
        _make_users(session_factory)

        res = client.post(
            "/api/v1/auth/login",
            json={"email": ANALYST_EMAIL, "password": "wrong-password"},
        )
        assert res.status_code == 401

    def test_login_fails_with_unknown_email(self, api_client):
        client, session_factory = api_client
        _make_users(session_factory)

        res = client.post(
            "/api/v1/auth/login",
            json={"email": "nobody@sentinelbank.ai", "password": "whatever"},
        )
        assert res.status_code == 401

    def test_me_returns_current_user(self, api_client):
        client, session_factory = api_client
        _make_users(session_factory)
        token = _login(client, ANALYST_EMAIL, ANALYST_PASSWORD)

        res = client.get("/api/v1/auth/me", headers=_auth_headers(token))
        assert res.status_code == 200
        assert res.json()["email"] == ANALYST_EMAIL
        assert res.json()["role"] == "ANALYST"


class TestAuthRequired:
    def test_protected_route_without_token_is_rejected(self, api_client):
        client, session_factory = api_client
        _make_users(session_factory)

        res = client.get("/api/v1/alerts")
        assert res.status_code == 401

    def test_protected_route_with_garbage_token_is_rejected(self, api_client):
        client, session_factory = api_client
        _make_users(session_factory)

        res = client.get("/api/v1/alerts", headers=_auth_headers("not-a-real-token"))
        assert res.status_code == 401

    def test_valid_token_grants_access(self, api_client):
        client, session_factory = api_client
        _make_users(session_factory)
        token = _login(client, ANALYST_EMAIL, ANALYST_PASSWORD)

        res = client.get("/api/v1/alerts", headers=_auth_headers(token))
        assert res.status_code == 200


class TestRoleEnforcement:
    def test_analyst_cannot_rerun_detection(self, api_client):
        client, session_factory = api_client
        _make_users(session_factory)
        token = _login(client, ANALYST_EMAIL, ANALYST_PASSWORD)

        res = client.post("/api/v1/detection/run", headers=_auth_headers(token))
        assert res.status_code == 403

    def test_admin_can_rerun_detection(self, api_client):
        client, session_factory = api_client
        _make_users(session_factory)
        token = _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)

        res = client.post("/api/v1/detection/run", headers=_auth_headers(token))
        assert res.status_code == 200


class TestReviewIntegrity:
    def test_reviewer_identity_comes_from_auth_not_request_body(self, api_client):
        client, session_factory = api_client
        _make_users(session_factory)
        token = _login(client, ANALYST_EMAIL, ANALYST_PASSWORD)
        _, report_id = _make_alert_with_report(session_factory)

        # Even if a client tried to smuggle a reviewed_by field, the
        # request schema no longer accepts one -- identity is server-side.
        res = client.post(
            f"/api/v1/reports/{report_id}/review",
            json={"status": "APPROVED", "reviewed_by": "Someone Else"},
            headers=_auth_headers(token),
        )
        assert res.status_code == 200
        assert res.json()["reviewed_by"] == "Test Analyst"
        assert res.json()["reviewed_by_user_id"] is not None

    def test_review_requires_authentication(self, api_client):
        client, session_factory = api_client
        _make_users(session_factory)
        _, report_id = _make_alert_with_report(session_factory)

        res = client.post(
            f"/api/v1/reports/{report_id}/review", json={"status": "APPROVED"}
        )
        assert res.status_code == 401

    def test_duplicate_review_is_rejected(self, api_client):
        client, session_factory = api_client
        _make_users(session_factory)
        token = _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        _, report_id = _make_alert_with_report(session_factory)

        first = client.post(
            f"/api/v1/reports/{report_id}/review",
            json={"status": "APPROVED"},
            headers=_auth_headers(token),
        )
        assert first.status_code == 200

        second = client.post(
            f"/api/v1/reports/{report_id}/review",
            json={"status": "DISMISSED"},
            headers=_auth_headers(token),
        )
        assert second.status_code == 409
        assert "already reviewed" in second.json()["detail"].lower()

        # The first decision must be the one that stuck.
        db = session_factory()
        try:
            report = db.get(models.InvestigationReport, report_id)
            assert report.status == "APPROVED"
        finally:
            db.close()

    def test_review_of_nonexistent_report_is_404(self, api_client):
        client, session_factory = api_client
        _make_users(session_factory)
        token = _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)

        res = client.post(
            "/api/v1/reports/999999/review",
            json={"status": "APPROVED"},
            headers=_auth_headers(token),
        )
        assert res.status_code == 404

    def test_invalid_status_value_is_422(self, api_client):
        client, session_factory = api_client
        _make_users(session_factory)
        token = _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        _, report_id = _make_alert_with_report(session_factory)

        res = client.post(
            f"/api/v1/reports/{report_id}/review",
            json={"status": "NOT_A_REAL_STATUS"},
            headers=_auth_headers(token),
        )
        assert res.status_code == 422

    def test_concurrent_reviews_only_one_wins(self, api_client):
        """Fires two review requests at the same report from separate
        threads at (approximately) the same time. The atomic conditional
        UPDATE in the route (WHERE reviewed_by_user_id IS NULL) must ensure
        exactly one succeeds and the other gets 409 -- never both
        succeeding, and never a crash/deadlock.
        """
        client, session_factory = api_client
        _make_users(session_factory)
        token = _login(client, ADMIN_EMAIL, ADMIN_PASSWORD)
        _, report_id = _make_alert_with_report(session_factory)

        barrier = threading.Barrier(2)

        def attempt(status: str):
            barrier.wait(timeout=5)
            return client.post(
                f"/api/v1/reports/{report_id}/review",
                json={"status": status},
                headers=_auth_headers(token),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            future_a = pool.submit(attempt, "APPROVED")
            future_b = pool.submit(attempt, "ESCALATED")
            status_codes = sorted([future_a.result().status_code, future_b.result().status_code])

        assert status_codes == [200, 409]

        db = session_factory()
        try:
            report = db.get(models.InvestigationReport, report_id)
            assert report.status in ("APPROVED", "ESCALATED")
            assert report.reviewed_by_user_id is not None
        finally:
            db.close()
