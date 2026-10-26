import type {
  Alert,
  CurrentUser,
  EvaluationRunIndexEntry,
  EvaluationRunSummary,
  LoginResponse,
  Report,
  ReviewStatus,
  Transaction,
} from "./types";
import { clearToken, getToken } from "./authToken";

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

/** Fired whenever a request comes back 401 -- the stored token is cleared
 * here (single source of truth for "are we logged out"), and anything that
 * wants to react (e.g. redirecting to /login) listens for this instead of
 * re-deriving auth state from each failed request. */
const AUTH_EVENT = "sentinelbank:unauthorized";

export function onUnauthorized(handler: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener(AUTH_EVENT, handler);
  return () => window.removeEventListener(AUTH_EVENT, handler);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const token = getToken();
  let res: Response;
  try {
    res = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...init?.headers,
      },
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
    if (res.status === 401) {
      clearToken();
      if (typeof window !== "undefined") {
        window.dispatchEvent(new Event(AUTH_EVENT));
      }
    }
    throw new ApiError(res.status, detail);
  }

  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export const api = {
  login: (email: string, password: string) =>
    request<LoginResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify({ email, password }),
    }),
  me: () => request<CurrentUser>("/api/v1/auth/me"),

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
  reviewReport: (reportId: number, status: ReviewStatus) =>
    request<Report>(`/api/v1/reports/${reportId}/review`, {
      method: "POST",
      body: JSON.stringify({ status }),
    }),

  health: () => request<{ status: string }>("/health"),
  healthDatabase: () =>
    request<{ status: string; database: string }>("/health/database"),

  listEvaluationRuns: () =>
    request<EvaluationRunIndexEntry[]>("/api/v1/evaluation/runs"),
  getEvaluationRun: (runId: string) =>
    request<EvaluationRunSummary>(`/api/v1/evaluation/runs/${runId}`),
};
