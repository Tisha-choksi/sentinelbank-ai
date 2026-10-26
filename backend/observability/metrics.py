"""Live API metrics for THIS running process, in Prometheus format.

Deliberately separate from evaluation/results/*.json (see api/evaluation.py
and its scope_note): those are timestamped snapshots of one-time offline
benchmark runs against synthetic scenarios; these are a running counter of
real traffic this server has actually handled since it started. Neither
module imports from the other, and nothing here is ever written to disk as
a "benchmark result."

Route *templates* are used as metric labels (e.g.
"/api/v1/alerts/{alert_id}/reports"), never resolved paths with real IDs in
them -- using actual IDs as a label would make cardinality grow without
bound as new alerts/reports are created.
"""

from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

REQUEST_COUNT = Counter(
    "http_requests_total",
    "Total HTTP requests handled",
    ["method", "path", "status_code"],
)
REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds",
    ["method", "path"],
)
AUTH_FAILURES = Counter(
    "auth_failures_total",
    "Failed authentication attempts (bad credentials or invalid/expired token)",
    ["reason"],
)
ACTIONS_DENIED = Counter(
    "actions_denied_total",
    "Authenticated requests rejected by role-based access control",
    ["path", "role"],
)


def record_request(method: str, path_template: str, status_code: int, duration_seconds: float) -> None:
    REQUEST_COUNT.labels(method=method, path=path_template, status_code=str(status_code)).inc()
    REQUEST_DURATION_SECONDS.labels(method=method, path=path_template).observe(duration_seconds)


def record_auth_failure(reason: str) -> None:
    AUTH_FAILURES.labels(reason=reason).inc()


def record_action_denied(path_template: str, role: str) -> None:
    ACTIONS_DENIED.labels(path=path_template, role=role).inc()


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(), CONTENT_TYPE_LATEST
