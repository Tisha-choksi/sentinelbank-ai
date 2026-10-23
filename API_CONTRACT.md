# SentinelBank AI — Backend API Contract

This document describes the **actual, implemented** request/response shapes of the FastAPI backend, as of:

- Model/prompt freeze: `llama3.1:8b`, prompt version `v2-strict-citation-rules`
- Backend source of truth: `backend/main.py`, `backend/api/alerts.py`, `backend/api/investigations.py`

Nothing here is aspirational — every field listed is pulled directly from the Pydantic response models in the code. If the frontend needs a field that isn't listed, it doesn't exist yet; extend the backend first rather than guessing.

Base URL (local dev): `http://127.0.0.1:8000`

---

## Health

### `GET /`
```json
{ "project": "SentinelBank AI", "message": "Banking risk intelligence platform is running", "version": "0.2.0" }
```

### `GET /health`
```json
{ "status": "healthy", "timestamp": "2026-10-22T05:00:00.000000+00:00" }
```

### `GET /health/database`
200:
```json
{ "status": "connected", "database": "sentinelbank" }
```
503 if the DB is unreachable (`{"detail": "database unavailable"}`).

---

## Transactions

### `POST /api/v1/transactions`
Creates a transaction and synchronously runs fraud detection against it (may create one or more alerts as a side effect).

Request body:
```ts
{
  transaction_ref: string;   // 1-64 chars, must be unique
  from_account: string;      // 1-64 chars, free text (not FK'd to an accounts table)
  to_account: string;        // 1-64 chars
  amount: string;             // decimal, > 0, up to 15 digits / 2 decimal places
  currency?: string;          // default "INR", pattern ^[A-Z]{3}$
}
```

201 response:
```ts
{
  transaction_ref: string;
  from_account: string;
  to_account: string;
  amount: string;             // e.g. "250000.00"
  currency: string;
  id: number;
  status: string;              // always "RECEIVED" today
  created_at: string;          // ISO 8601
}
```
409 if `transaction_ref` already exists.

### `GET /api/v1/transactions`
200: `TransactionResponse[]` (same shape as above), ordered by `id` ascending. No pagination, filtering, or sorting params exist yet.

---

## Alerts

### `GET /api/v1/alerts`
200:
```ts
{
  id: number;
  transaction_id: number;
  case_id: number | null;      // always null today -- no endpoint assigns a case yet
  rule_code: string;             // "TXN_HIGH_VALUE" | "TXN_VELOCITY" | "TXN_CIRCULAR_FLOW"
  severity: string;               // "LOW" | "MEDIUM" | "HIGH" | "CRITICAL"
  status: string;                  // "OPEN" | "IN_REVIEW" | "RESOLVED" | "DISMISSED" (DB-level enum; no endpoint currently transitions alert.status)
  description: string;              // human-readable, e.g. "Account X sent 5 transfers within 300 seconds..."
  evidence: Record<string, unknown>; // shape depends on rule_code -- see below
  created_at: string;
}[]
```
Ordered by `id` ascending. No pagination/filtering params exist.

**`evidence` shape varies by `rule_code`** (this is raw rule output, not a fixed schema):
- `TXN_HIGH_VALUE`: `{ amount: string, currency: string, threshold: string }`
- `TXN_VELOCITY`: `{ account: string, window_seconds: number, transfer_count: number, transaction_refs: string[] }`
- `TXN_CIRCULAR_FLOW`: `{ account_path: string[], transaction_refs: string[], hops: number }`

### `POST /api/v1/detection/run`
Reruns detection across every stored transaction. Idempotent (existing `(transaction_id, rule_code)` alerts are never duplicated).

200: `AlertResponse[]` — only the **newly created** alerts from this run (often `[]` if nothing new fired).

---

## Investigations / Reports

### `POST /api/v1/alerts/{alert_id}/investigate`
Runs the LangGraph investigation workflow for the given alert. Safe to call repeatedly — each call creates a **new** report row rather than overwriting the previous one.

201 response:
```ts
{
  id: number;
  alert_id: number;
  case_id: number | null;        // copied from the alert's case_id at persistence time (currently always null)
  status: string;                  // "PENDING_REVIEW" | "FAILED" | "APPROVED" | "DISMISSED" | "ESCALATED"
  model_provider: string;           // "ollama" on success; "none" if investigation failed before an LLM call
  model_name: string;                // e.g. "llama3.1:8b"
  prompt_version: string;             // e.g. "v2-strict-citation-rules"
  summary: string;                     // on FAILED, this is "Investigation did not complete: <error>"
  findings: Record<string, unknown>;    // see "Findings shape" below
  evidence_snapshot: Record<string, unknown>; // see "Evidence snapshot shape" below
  created_at: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
}
```
404 if `alert_id` does not exist (`{"detail": "Alert <id> does not exist."}`) — nothing is persisted in this case.

**`findings` shape when `status != "FAILED"`:**
```ts
{
  summary: string;
  confirmed_facts: string[];
  hypotheses: string[];
  uncertainties: string[];
  recommended_checks: string[];
  cited_transaction_refs: string[];  // guaranteed subset of evidence_snapshot's known transaction refs
  cited_accounts: string[];           // guaranteed subset of evidence_snapshot's known account numbers
}
```
**`findings` shape when `status == "FAILED"`:** `{ "error": string }` only — none of the fields above are present.

**`evidence_snapshot` shape** (always present, even on failure, as long as the alert existed):
```ts
{
  alert_id: number;
  rule_code: string;
  severity: string;
  alert_description: string;
  alert_evidence: Record<string, unknown>;   // same as Alert.evidence
  primary_transaction: {
    transaction_ref: string; from_account: string; to_account: string;
    amount: string; currency: string; status: string; created_at: string;
  };
  related_transactions: Array<typeof primary_transaction>;  // same shape
  known_accounts: Array<{
    account_number: string; owner_name: string; account_type: string; status: string;
  }>;
  missing_evidence: string[];   // human-readable gaps, e.g. "Account 'X' has no entry in the account registry..."
}
```

### `GET /api/v1/alerts/{alert_id}/reports`
200: `ReportResponse[]` (same shape as above) for that alert, ordered by `id` ascending — i.e. full history of every investigation run, most recent last. Empty array if none yet.

### `POST /api/v1/reports/{report_id}/review`
The human-approval step.

Request body:
```ts
{ status: "APPROVED" | "DISMISSED" | "ESCALATED"; reviewed_by: string }  // reviewed_by: 1-128 chars
```
200: `ReportResponse` (updated: `status`, `reviewed_by`, `reviewed_at` now set). Also writes an `AuditLog` row server-side (not directly exposed via any endpoint yet).

404 if `report_id` not found. 422 if `status` isn't one of the three allowed values.

---

## Explicitly NOT implemented yet (do not build frontend screens assuming these exist)

- No `GET /api/v1/accounts` or account-detail endpoint (the `accounts` table exists in the DB but has no API surface).
- No `GET /api/v1/investigation-cases` / case management endpoints (the `investigation_cases` table exists but is unused by any endpoint — every `case_id` in responses today is `null`).
- No `GET /api/v1/audit-logs` endpoint (audit rows are written on detection, investigation, and review, but nothing reads them back).
- No endpoint to fetch a single alert or transaction by id (`GET /api/v1/alerts/{id}`, `GET /api/v1/transactions/{id}` do not exist — only list and the investigation-report endpoints are scoped by id).
- No pagination, filtering, sorting, or search on any list endpoint.
- No authentication/authorization on any endpoint.
- No evaluation-metrics endpoint — `evaluation/results/*.json` are local files, not served over HTTP.

---

## Error shape

All FastAPI default error responses: `{"detail": string}`, with the status codes noted per-endpoint above (404, 409, 422, 503). No custom error envelope exists.
