"use client";

import { useCallback } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";
import type { Alert, Severity } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { ErrorState, LoadingState } from "@/components/States";

const SEVERITY_ORDER: Severity[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];
const SEVERITY_COLOR: Record<Severity, string> = {
  LOW: "var(--color-status-good)",
  MEDIUM: "var(--color-status-warning)",
  HIGH: "var(--color-status-serious)",
  CRITICAL: "var(--color-status-critical)",
};

const RULE_ORDER = ["TXN_HIGH_VALUE", "TXN_VELOCITY", "TXN_CIRCULAR_FLOW"];
const RULE_LABEL: Record<string, string> = {
  TXN_HIGH_VALUE: "High value",
  TXN_VELOCITY: "Velocity",
  TXN_CIRCULAR_FLOW: "Circular flow",
};
const RULE_COLOR: Record<string, string> = {
  TXN_HIGH_VALUE: "var(--color-cat-1)",
  TXN_VELOCITY: "var(--color-cat-2)",
  TXN_CIRCULAR_FLOW: "var(--color-cat-3)",
};

function ChartTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; payload: { fill: string } }>;
}) {
  if (!active || !payload?.length) return null;
  const point = payload[0];
  return (
    <div className="rounded-md border border-border bg-surface-card-raised px-3 py-2 text-xs shadow-lg">
      <p className="text-ink-secondary">{point.name}</p>
      <p className="font-semibold text-ink-primary">{point.value}</p>
    </div>
  );
}

function OverviewContent({ alerts }: { alerts: Alert[] }) {
  const bySeverity = SEVERITY_ORDER.map((severity) => ({
    name: severity,
    value: alerts.filter((a) => a.severity === severity).length,
    fill: SEVERITY_COLOR[severity],
  }));

  const byRule = RULE_ORDER.map((rule) => ({
    name: RULE_LABEL[rule],
    value: alerts.filter((a) => a.rule_code === rule).length,
    fill: RULE_COLOR[rule],
  }));

  const openCount = alerts.filter((a) => a.status === "OPEN").length;
  const criticalCount = alerts.filter((a) => a.severity === "CRITICAL").length;

  return (
    <div className="flex flex-col gap-6 px-8 py-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard label="Total alerts" value={alerts.length} />
        <StatCard
          label="Open alerts"
          value={openCount}
          accent="var(--color-status-warning)"
        />
        <StatCard
          label="Critical severity"
          value={criticalCount}
          accent="var(--color-status-critical)"
        />
        <StatCard label="Detection rules active" value={3} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface-card p-5">
          <div className="mb-1 flex items-center justify-between">
            <h2 className="text-sm font-medium text-ink-primary">
              Alerts by severity
            </h2>
          </div>
          <div className="mb-3 flex flex-wrap gap-3 text-xs text-ink-secondary">
            {SEVERITY_ORDER.map((s) => (
              <span key={s} className="inline-flex items-center gap-1.5">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: SEVERITY_COLOR[s] }}
                />
                {s}
              </span>
            ))}
          </div>
          {alerts.length === 0 ? (
            <p className="py-10 text-center text-sm text-ink-muted">
              No alerts yet.
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={bySeverity} barCategoryGap="30%">
                <CartesianGrid
                  vertical={false}
                  stroke="var(--color-gridline)"
                />
                <XAxis
                  dataKey="name"
                  tickLine={false}
                  axisLine={{ stroke: "var(--color-axis)" }}
                  tick={{ fill: "var(--color-ink-muted)", fontSize: 12 }}
                />
                <YAxis
                  allowDecimals={false}
                  tickLine={false}
                  axisLine={false}
                  tick={{ fill: "var(--color-ink-muted)", fontSize: 12 }}
                  width={28}
                />
                <Tooltip
                  cursor={{ fill: "var(--color-surface-hover)" }}
                  content={<ChartTooltip />}
                />
                <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={48}>
                  {bySeverity.map((entry) => (
                    <Cell key={entry.name} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>

        <div className="rounded-xl border border-border bg-surface-card p-5">
          <div className="mb-1 flex items-center justify-between">
            <h2 className="text-sm font-medium text-ink-primary">
              Alerts by detection rule
            </h2>
          </div>
          <div className="mb-3 flex flex-wrap gap-3 text-xs text-ink-secondary">
            {RULE_ORDER.map((r) => (
              <span key={r} className="inline-flex items-center gap-1.5">
                <span
                  className="h-2 w-2 rounded-full"
                  style={{ backgroundColor: RULE_COLOR[r] }}
                />
                {RULE_LABEL[r]}
              </span>
            ))}
          </div>
          {alerts.length === 0 ? (
            <p className="py-10 text-center text-sm text-ink-muted">
              No alerts yet.
            </p>
          ) : (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={byRule} barCategoryGap="30%">
                <CartesianGrid
                  vertical={false}
                  stroke="var(--color-gridline)"
                />
                <XAxis
                  dataKey="name"
                  tickLine={false}
                  axisLine={{ stroke: "var(--color-axis)" }}
                  tick={{ fill: "var(--color-ink-muted)", fontSize: 12 }}
                />
                <YAxis
                  allowDecimals={false}
                  tickLine={false}
                  axisLine={false}
                  tick={{ fill: "var(--color-ink-muted)", fontSize: 12 }}
                  width={28}
                />
                <Tooltip
                  cursor={{ fill: "var(--color-surface-hover)" }}
                  content={<ChartTooltip />}
                />
                <Bar dataKey="value" radius={[4, 4, 0, 0]} maxBarSize={48}>
                  {byRule.map((entry) => (
                    <Cell key={entry.name} fill={entry.fill} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          )}
        </div>
      </div>
    </div>
  );
}

export default function OverviewPage() {
  const alertsState = useAsync(useCallback(() => api.listAlerts(), []));

  return (
    <>
      <PageHeader
        title="Risk Overview"
        description="Live alert volume and severity across every detection rule."
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
        <OverviewContent alerts={alertsState.data} />
      )}
    </>
  );
}
