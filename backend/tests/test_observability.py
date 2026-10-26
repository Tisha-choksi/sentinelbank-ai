"""Tests for the observability layer: request IDs, the consistent error
envelope, safe handling of unhandled exceptions, and that auth failures /
denied actions are logged without ever including a secret.
"""

from __future__ import annotations

import io
import json
import logging

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from observability.error_handlers import register_error_handlers
from observability.logging_config import JsonFormatter, configure_logging
from observability.middleware import RequestIDMiddleware

ANALYST_EMAIL = "obs-analyst@sentinelbank.ai"
ANALYST_PASSWORD = "ObsAnalystPass123!"


@pytest.fixture()
def log_capture():
    """Captures every JSON log line emitted during the test, so assertions
    can check log *content* (e.g. "the password never appears anywhere"),
    not just side effects."""
    configure_logging()
    buf = io.StringIO()
    handler = logging.StreamHandler(buf)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        yield buf
    finally:
        root.removeHandler(handler)


def _parsed_lines(buf: io.StringIO) -> list[dict]:
    lines = []
    for line in buf.getvalue().splitlines():
        try:
            lines.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return lines


class TestRequestID:
    def test_response_carries_a_request_id_header(self, api_client):
        client, _ = api_client
        res = client.get("/api/v1/alerts")  # 401, no auth -- still gets an ID
        assert "x-request-id" in res.headers
        assert len(res.headers["x-request-id"]) > 0

    def test_incoming_request_id_is_honored_not_replaced(self, api_client):
        client, _ = api_client
        res = client.get(
            "/api/v1/alerts", headers={"X-Request-ID": "caller-supplied-id-123"}
        )
        assert res.headers["x-request-id"] == "caller-supplied-id-123"

    def test_different_requests_get_different_ids(self, api_client):
        client, _ = api_client
        first = client.get("/api/v1/alerts").headers["x-request-id"]
        second = client.get("/api/v1/alerts").headers["x-request-id"]
        assert first != second


class TestErrorEnvelope:
    def test_401_has_consistent_shape(self, api_client):
        client, _ = api_client
        res = client.get("/api/v1/alerts")
        assert res.status_code == 401
        body = res.json()
        assert set(body.keys()) == {"detail", "request_id"}
        assert body["request_id"] == res.headers["x-request-id"]

    def test_404_has_consistent_shape(self, api_client):
        client, _ = api_client
        res = client.get("/api/v1/evaluation/runs/does-not-exist")
        # unauthenticated -> 401, not 404, but still the same envelope
        assert res.status_code in (401, 404)
        assert set(res.json().keys()) == {"detail", "request_id"}

    def test_422_validation_error_has_consistent_shape_and_scrubs_password(
        self, api_client
    ):
        client, _ = api_client
        res = client.post(
            "/api/v1/auth/login", json={"email": "", "password": ""}
        )
        # email min_length=1 and password min_length=1 both fail
        assert res.status_code == 422
        body = res.json()
        assert set(body.keys()) == {"detail", "request_id"}
        for error in body["detail"]:
            if "password" in error.get("loc", []):
                assert "input" not in error


class TestUnhandledException:
    """Uses a throwaway app wired with the same observability stack as
    main.py, since this tests cross-cutting infrastructure rather than any
    specific business route."""

    def _app(self):
        app = FastAPI()
        register_error_handlers(app)
        app.add_middleware(RequestIDMiddleware)

        @app.get("/boom")
        def boom():
            raise RuntimeError("internal detail: db password is hunter2")

        return app

    def test_client_response_never_leaks_the_exception_message(self):
        client = TestClient(self._app(), raise_server_exceptions=False)
        res = client.get("/boom")
        assert res.status_code == 500
        body = res.json()
        assert "hunter2" not in json.dumps(body)
        assert "RuntimeError" not in json.dumps(body)
        assert set(body.keys()) == {"detail", "request_id"}

    def test_client_response_still_carries_a_request_id_header(self):
        client = TestClient(self._app(), raise_server_exceptions=False)
        res = client.get("/boom")
        assert "x-request-id" in res.headers
        assert res.json()["request_id"] == res.headers["x-request-id"]

    def test_full_traceback_is_captured_server_side(self, log_capture):
        client = TestClient(self._app(), raise_server_exceptions=False)
        client.get("/boom")

        records = [
            r
            for r in _parsed_lines(log_capture)
            if r.get("level") == "ERROR" and "exception" in r
        ]
        assert records, "expected an ERROR-level log with a captured traceback"
        assert "hunter2" in records[0]["exception"]
        assert "RuntimeError" in records[0]["exception"]


class TestMetricsEndpoint:
    def test_requires_authentication(self, api_client):
        client, _ = api_client
        res = client.get("/metrics")
        assert res.status_code == 401

    def test_requires_admin_role(self, api_client):
        import models
        from auth.security import hash_password

        client, session_factory = api_client
        db = session_factory()
        try:
            db.add(
                models.User(
                    email=ANALYST_EMAIL,
                    full_name="Obs Analyst",
                    hashed_password=hash_password(ANALYST_PASSWORD),
                    role="ANALYST",
                )
            )
            db.commit()
        finally:
            db.close()

        login = client.post(
            "/api/v1/auth/login",
            json={"email": ANALYST_EMAIL, "password": ANALYST_PASSWORD},
        )
        token = login.json()["access_token"]
        res = client.get(
            "/metrics", headers={"Authorization": f"Bearer {token}"}
        )
        assert res.status_code == 403

    def test_admin_sees_prometheus_format_with_real_counters(self, api_client):
        import models
        from auth.security import hash_password

        client, session_factory = api_client
        db = session_factory()
        try:
            db.add(
                models.User(
                    email="obs-admin@sentinelbank.ai",
                    full_name="Obs Admin",
                    hashed_password=hash_password("ObsAdminPass123!"),
                    role="ADMIN",
                )
            )
            db.commit()
        finally:
            db.close()

        login = client.post(
            "/api/v1/auth/login",
            json={"email": "obs-admin@sentinelbank.ai", "password": "ObsAdminPass123!"},
        )
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        client.get("/api/v1/alerts", headers=headers)
        client.get("/api/v1/alerts", headers=headers)

        res = client.get("/metrics", headers=headers)
        assert res.status_code == 200
        assert "text/plain" in res.headers["content-type"]
        assert "http_requests_total" in res.text
        assert "http_request_duration_seconds" in res.text
        # route TEMPLATE, never a resolved id-bearing path
        assert '/api/v1/alerts"' in res.text


class TestSafeAuthLogging:
    def test_failed_login_is_logged_without_the_password(self, api_client, log_capture):
        client, session_factory = api_client
        import models
        from auth.security import hash_password

        db = session_factory()
        try:
            db.add(
                models.User(
                    email="safe-log@sentinelbank.ai",
                    full_name="Safe Log",
                    hashed_password=hash_password("TheRealPassword123!"),
                    role="ANALYST",
                )
            )
            db.commit()
        finally:
            db.close()

        client.post(
            "/api/v1/auth/login",
            json={
                "email": "safe-log@sentinelbank.ai",
                "password": "a-wrong-but-sensitive-guess-998877",
            },
        )

        full_log_text = log_capture.getvalue()
        assert "a-wrong-but-sensitive-guess-998877" not in full_log_text
        assert "TheRealPassword123!" not in full_log_text

        records = _parsed_lines(log_capture)
        failures = [r for r in records if r.get("message") == "login_failed"]
        assert failures
        assert failures[0]["attempted_email"] == "safe-log@sentinelbank.ai"
        assert failures[0]["reason"] == "invalid_credentials"

    def test_denied_admin_action_is_logged_with_role_and_path_template(
        self, api_client, log_capture
    ):
        client, session_factory = api_client
        import models
        from auth.security import hash_password

        db = session_factory()
        try:
            db.add(
                models.User(
                    email="denied@sentinelbank.ai",
                    full_name="Denied Analyst",
                    hashed_password=hash_password("DeniedPass123!"),
                    role="ANALYST",
                )
            )
            db.commit()
        finally:
            db.close()

        login = client.post(
            "/api/v1/auth/login",
            json={"email": "denied@sentinelbank.ai", "password": "DeniedPass123!"},
        )
        token = login.json()["access_token"]
        client.post(
            "/api/v1/detection/run", headers={"Authorization": f"Bearer {token}"}
        )

        records = _parsed_lines(log_capture)
        denials = [r for r in records if r.get("message") == "action_denied"]
        assert denials
        assert denials[0]["user_email"] == "denied@sentinelbank.ai"
        assert denials[0]["user_role"] == "ANALYST"
        assert denials[0]["path"] == "/api/v1/detection/run"
