import type { AlertStatus, ReportStatus, Severity } from "@/lib/types";

const SEVERITY_STYLES: Record<Severity, { color: string; icon: string }> = {
  LOW: { color: "var(--color-status-good)", icon: "●" },
  MEDIUM: { color: "var(--color-status-warning)", icon: "▲" },
  HIGH: { color: "var(--color-status-serious)", icon: "▲" },
  CRITICAL: { color: "var(--color-status-critical)", icon: "■" },
};

// Status colors carry meaning paired with an icon + label, never alone.
export function SeverityBadge({ severity }: { severity: Severity }) {
  const style = SEVERITY_STYLES[severity];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-0.5 text-xs font-medium"
      style={{ color: style.color }}
    >
      <span aria-hidden="true">{style.icon}</span>
      {severity}
    </span>
  );
}

const ALERT_STATUS_LABEL: Record<AlertStatus, string> = {
  OPEN: "Open",
  IN_REVIEW: "In review",
  RESOLVED: "Resolved",
  DISMISSED: "Dismissed",
};

export function AlertStatusBadge({ status }: { status: AlertStatus }) {
  return (
    <span className="inline-flex items-center rounded-full bg-surface-card-raised px-2.5 py-0.5 text-xs font-medium text-ink-secondary">
      {ALERT_STATUS_LABEL[status]}
    </span>
  );
}

const REPORT_STATUS_STYLE: Record<ReportStatus, { color: string; label: string }> = {
  PENDING_REVIEW: { color: "var(--color-status-warning)", label: "Pending review" },
  FAILED: { color: "var(--color-status-critical)", label: "Failed" },
  APPROVED: { color: "var(--color-status-good)", label: "Approved" },
  DISMISSED: { color: "var(--color-ink-muted)", label: "Dismissed" },
  ESCALATED: { color: "var(--color-status-serious)", label: "Escalated" },
};

export function ReportStatusBadge({ status }: { status: ReportStatus }) {
  const style = REPORT_STATUS_STYLE[status];
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-0.5 text-xs font-medium"
      style={{ color: style.color }}
    >
      <span
        aria-hidden="true"
        className="h-1.5 w-1.5 rounded-full"
        style={{ backgroundColor: style.color }}
      />
      {style.label}
    </span>
  );
}

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

export function RuleBadge({ ruleCode }: { ruleCode: string }) {
  const color = RULE_COLOR[ruleCode] ?? "var(--color-ink-muted)";
  return (
    <span
      className="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-0.5 text-xs font-medium"
      style={{ color }}
    >
      <span
        aria-hidden="true"
        className="h-1.5 w-1.5 rounded-full"
        style={{ backgroundColor: color }}
      />
      {RULE_LABEL[ruleCode] ?? ruleCode}
    </span>
  );
}
