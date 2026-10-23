"use client";

import { useCallback } from "react";
import { api } from "@/lib/api";
import { useAsync } from "@/lib/useAsync";
import { PageHeader } from "@/components/PageHeader";
import { ErrorState, LoadingState, EmptyState } from "@/components/States";
import { TransactionGraph } from "@/components/TransactionGraph";

const LEGEND = [
  { label: "High value", color: "#3987e5" },
  { label: "Velocity", color: "#d95926" },
  { label: "Circular flow", color: "#199e70" },
  { label: "Not flagged", color: "#52514e" },
];

export default function NetworkPage() {
  const transactionsState = useAsync(useCallback(() => api.listTransactions(), []));
  const alertsState = useAsync(useCallback(() => api.listAlerts(), []));

  const loading =
    transactionsState.status === "loading" || alertsState.status === "loading";
  const error =
    transactionsState.status === "error"
      ? transactionsState.error
      : alertsState.status === "error"
        ? alertsState.error
        : null;

  return (
    <>
      <PageHeader
        title="Transaction Network"
        description="Accounts and transfers, with flagged edges colored by the rule that triggered."
      />
      <div className="px-8 py-6">
        {loading && <LoadingState label="Loading transaction graph..." />}
        {error && (
          <ErrorState
            message={error}
            onRetry={() => {
              transactionsState.refetch();
              alertsState.refetch();
            }}
          />
        )}
        {transactionsState.status === "success" &&
          alertsState.status === "success" &&
          (transactionsState.data.length === 0 ? (
            <EmptyState
              title="No transactions yet"
              description="Post a transaction through the API to see the account network."
            />
          ) : (
            <div className="rounded-xl border border-border bg-surface-card p-4">
              <div className="mb-3 flex flex-wrap gap-4 text-xs text-ink-secondary">
                {LEGEND.map((l) => (
                  <span key={l.label} className="inline-flex items-center gap-1.5">
                    <span
                      className="h-2 w-2 rounded-full"
                      style={{ backgroundColor: l.color }}
                    />
                    {l.label}
                  </span>
                ))}
              </div>
              <TransactionGraph
                transactions={transactionsState.data}
                alerts={alertsState.data}
              />
              <p className="mt-2 text-xs text-ink-muted">
                Each node is an account (from the {transactionsState.data.length}{" "}
                stored transactions); each edge is one transfer. Thicker,
                colored edges triggered a fraud alert.
              </p>
            </div>
          ))}
      </div>
    </>
  );
}
