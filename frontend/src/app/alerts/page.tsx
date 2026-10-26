"use client";

import Link from "next/link";
import { useCallback, useMemo, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/lib/AuthProvider";
import type { Alert } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";
import { PageHeader } from "@/components/PageHeader";
import { SeverityBadge, AlertStatusBadge, RuleBadge } from "@/components/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/States";

function matchesQuery(alert: Alert, query: string): boolean {
  if (!query) return true;
  const q = query.toLowerCase();
  return (
    alert.description.toLowerCase().includes(q) ||
    alert.rule_code.toLowerCase().includes(q) ||
    String(alert.id).includes(q) ||
    String(alert.transaction_id).includes(q)
  );
}

function AlertsTable({ alerts }: { alerts: Alert[] }) {
  const { user } = useAuth();
  const isAdmin = user?.role === "ADMIN";
  const [query, setQuery] = useState("");
  const [runningDetection, setRunningDetection] = useState(false);
  const [detectionMessage, setDetectionMessage] = useState<string | null>(null);

  const filtered = useMemo(
    () => alerts.filter((a) => matchesQuery(a, query)),
    [alerts, query]
  );

  async function handleRunDetection() {
    setRunningDetection(true);
    setDetectionMessage(null);
    try {
      const created = await api.runDetection();
      setDetectionMessage(
        created.length > 0
          ? `${created.length} new alert${created.length === 1 ? "" : "s"} created. Refresh to see them.`
          : "No new alerts -- detection is already up to date."
      );
    } catch (err) {
      setDetectionMessage(
        err instanceof Error ? err.message : "Detection run failed."
      );
    } finally {
      setRunningDetection(false);
    }
  }

  return (
    <div className="px-8 py-6">
      <div className="mb-4 flex items-center gap-3">
        <input
          type="search"
          placeholder="Search by alert id, transaction id, rule, or description..."
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-full max-w-md rounded-md border border-border bg-surface-card px-3 py-2 text-sm text-ink-primary placeholder:text-ink-muted focus:outline-none focus:ring-1 focus:ring-cat-1"
        />
        {isAdmin && (
          <button
            onClick={handleRunDetection}
            disabled={runningDetection}
            className="shrink-0 rounded-md border border-border bg-surface-card px-3 py-2 text-sm font-medium text-ink-primary hover:bg-surface-hover disabled:opacity-50"
            title="Admin-only: rescans every stored transaction"
          >
            {runningDetection ? "Running..." : "Rerun detection"}
          </button>
        )}
        <span className="text-sm text-ink-muted">
          {filtered.length} of {alerts.length}
        </span>
      </div>
      {detectionMessage && (
        <p className="mb-4 text-sm text-ink-secondary">{detectionMessage}</p>
      )}

      {alerts.length === 0 ? (
        <EmptyState
          title="No alerts yet"
          description="Post a transaction through the API, or rerun detection, to generate alerts."
        />
      ) : filtered.length === 0 ? (
        <EmptyState title="No alerts match your search" />
      ) : (
        <div className="overflow-hidden rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border bg-surface-card text-left text-xs uppercase tracking-wide text-ink-muted">
                <th className="px-4 py-3 font-medium">Alert</th>
                <th className="px-4 py-3 font-medium">Rule</th>
                <th className="px-4 py-3 font-medium">Severity</th>
                <th className="px-4 py-3 font-medium">Status</th>
                <th className="px-4 py-3 font-medium">Description</th>
                <th className="px-4 py-3 font-medium">Created</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((alert) => (
                <tr
                  key={alert.id}
                  className="border-b border-border bg-surface-page last:border-0 hover:bg-surface-hover"
                >
                  <td className="px-4 py-3">
                    <Link
                      href={`/alerts/${alert.id}`}
                      className="font-medium text-cat-1 hover:underline"
                    >
                      ALT-{alert.id}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <RuleBadge ruleCode={alert.rule_code} />
                  </td>
                  <td className="px-4 py-3">
                    <SeverityBadge severity={alert.severity} />
                  </td>
                  <td className="px-4 py-3">
                    <AlertStatusBadge status={alert.status} />
                  </td>
                  <td className="max-w-md truncate px-4 py-3 text-ink-secondary">
                    {alert.description}
                  </td>
                  <td className="tabular-nums px-4 py-3 text-ink-muted">
                    {new Date(alert.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export default function AlertsPage() {
  const alertsState = useAsync(useCallback(() => api.listAlerts(), []));

  return (
    <>
      <PageHeader
        title="Alert Queue"
        description="Every fraud alert generated by the detection engine, most recent first."
      />
      {alertsState.status === "loading" && (
        <div className="px-8">
          <LoadingState label="Loading alerts..." />
        </div>
      )}
      {alertsState.status === "error" && (
        <div className="px-8 py-6">
          <ErrorState message={alertsState.error} onRetry={alertsState.refetch} />
        </div>
      )}
      {alertsState.status === "success" && (
        <AlertsTable alerts={[...alertsState.data].reverse()} />
      )}
    </>
  );
}
