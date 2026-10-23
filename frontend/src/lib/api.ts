import type {
  Alert,
  EvaluationRunIndexEntry,
  EvaluationRunSummary,
  Report,
  ReviewStatus,
  Transaction,
} from "./types";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      0,
      `Could not reach the backend at ${BASE_URL}. Is it running?`
    );
  }

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.detail ?? detail;
    } catch {
      // response wasn't JSON -- keep statusText
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  listAlerts: () => request<Alert[]>("/api/v1/alerts"),
  runDetection: () =>
    request<Alert[]>("/api/v1/detection/run", { method: "POST" }),

  listTransactions: () => request<Transaction[]>("/api/v1/transactions"),

  investigateAlert: (alertId: number) =>
    request<Report>(`/api/v1/alerts/${alertId}/investigate`, {
      method: "POST",
    }),
  listReportsForAlert: (alertId: number) =>
    request<Report[]>(`/api/v1/alerts/${alertId}/reports`),
  reviewReport: (reportId: number, status: ReviewStatus, reviewedBy: string) =>
    request<Report>(`/api/v1/reports/${reportId}/review`, {
      method: "POST",
      body: JSON.stringify({ status, reviewed_by: reviewedBy }),
    }),

  health: () => request<{ status: string }>("/health"),
  healthDatabase: () =>
    request<{ status: string; database: string }>("/health/database"),

  listEvaluationRuns: () =>
    request<EvaluationRunIndexEntry[]>("/api/v1/evaluation/runs"),
  getEvaluationRun: (runId: string) =>
    request<EvaluationRunSummary>(`/api/v1/evaluation/runs/${runId}`),
};
