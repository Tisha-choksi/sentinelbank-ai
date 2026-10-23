"use client";

import { useParams } from "next/navigation";
import Link from "next/link";
import { useCallback, useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { Alert, Report, ReviewStatus } from "@/lib/types";
import { isFailedFindings } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";
import { PageHeader } from "@/components/PageHeader";
import {
  AlertStatusBadge,
  ReportStatusBadge,
  RuleBadge,
  SeverityBadge,
} from "@/components/Badges";
import { EmptyState, ErrorState, LoadingState } from "@/components/States";

function EvidenceList({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
        {title}
      </p>
      <ul className="mt-1.5 space-y-1">
        {items.map((item, i) => (
          <li key={i} className="text-sm text-ink-secondary">
            {item}
          </li>
        ))}
      </ul>
    </div>
  );
}

function CitationChips({ refs, accounts }: { refs: string[]; accounts: string[] }) {
  if (refs.length === 0 && accounts.length === 0) return null;
  return (
    <div>
      <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
        Cited evidence
      </p>
      <div className="mt-1.5 flex flex-wrap gap-1.5">
        {refs.map((ref) => (
          <span
            key={ref}
            className="rounded-md bg-cat-1/10 px-2 py-0.5 font-mono text-xs text-cat-1"
          >
            {ref}
          </span>
        ))}
        {accounts.map((acc) => (
          <span
            key={acc}
            className="rounded-md bg-cat-3/10 px-2 py-0.5 font-mono text-xs text-cat-3"
          >
            {acc}
          </span>
        ))}
      </div>
    </div>
  );
}

function ReviewPanel({ report, onReviewed }: { report: Report; onReviewed: (r: Report) => void }) {
  const [reviewedBy, setReviewedBy] = useState("");
  const [submitting, setSubmitting] = useState<ReviewStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  const canReview = report.status === "PENDING_REVIEW" || report.status === "FAILED";
  if (!canReview) return null;

  async function submit(status: ReviewStatus) {
    if (!reviewedBy.trim()) {
      setError("Enter the reviewing analyst's name first.");
      return;
    }
    setSubmitting(status);
    setError(null);
    try {
      const updated = await api.reviewReport(report.id, status, reviewedBy.trim());
      onReviewed(updated);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Review failed.");
    } finally {
      setSubmitting(null);
    }
  }

  return (
    <div className="mt-4 rounded-lg border border-border bg-surface-card-raised p-3">
      <p className="mb-2 text-xs font-medium uppercase tracking-wide text-ink-muted">
        Analyst review
      </p>
      <input
        type="text"
        placeholder="Your name"
        value={reviewedBy}
        onChange={(e) => setReviewedBy(e.target.value)}
        className="mb-2 w-full max-w-xs rounded-md border border-border bg-surface-page px-3 py-1.5 text-sm text-ink-primary placeholder:text-ink-muted focus:outline-none focus:ring-1 focus:ring-cat-1"
      />
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => submit("APPROVED")}
          disabled={submitting !== null}
          className="rounded-md px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
          style={{ backgroundColor: "var(--color-status-good)" }}
        >
          {submitting === "APPROVED" ? "Approving..." : "Approve"}
        </button>
        <button
          onClick={() => submit("DISMISSED")}
          disabled={submitting !== null}
          className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-ink-primary hover:bg-surface-hover disabled:opacity-50"
        >
          {submitting === "DISMISSED" ? "Dismissing..." : "Dismiss"}
        </button>
        <button
          onClick={() => submit("ESCALATED")}
          disabled={submitting !== null}
          className="rounded-md px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
          style={{ backgroundColor: "var(--color-status-serious)" }}
        >
          {submitting === "ESCALATED" ? "Escalating..." : "Escalate"}
        </button>
      </div>
      {error && <p className="mt-2 text-xs" style={{ color: "var(--color-status-critical)" }}>{error}</p>}
    </div>
  );
}

function ReportCard({ report, onReviewed }: { report: Report; onReviewed: (r: Report) => void }) {
  const findings = report.findings;

  return (
    <div className="rounded-xl border border-border bg-surface-card p-5">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <ReportStatusBadge status={report.status} />
          <span className="text-xs text-ink-muted">
            {report.model_name} &middot; {report.prompt_version}
          </span>
        </div>
        <span className="tabular-nums text-xs text-ink-muted">
          {new Date(report.created_at).toLocaleString()}
        </span>
      </div>

      {isFailedFindings(findings) ? (
        <p className="text-sm" style={{ color: "var(--color-status-critical)" }}>
          {report.summary}
        </p>
      ) : (
        <div className="space-y-4">
          <p className="text-sm text-ink-primary">{report.summary}</p>
          <EvidenceList title="Confirmed facts" items={findings.confirmed_facts} />
          <EvidenceList title="Hypotheses" items={findings.hypotheses} />
          <EvidenceList title="Uncertainties" items={findings.uncertainties} />
          <EvidenceList
            title="Recommended checks"
            items={findings.recommended_checks}
          />
          <CitationChips
            refs={findings.cited_transaction_refs}
            accounts={findings.cited_accounts}
          />
        </div>
      )}

      {report.reviewed_by ? (
        <p className="mt-4 text-xs text-ink-muted">
          Reviewed by {report.reviewed_by} on{" "}
          {report.reviewed_at && new Date(report.reviewed_at).toLocaleString()}
        </p>
      ) : (
        <ReviewPanel report={report} onReviewed={onReviewed} />
      )}
    </div>
  );
}

function AlertDetail({ alert, reports, onInvestigated, onReviewed }: {
  alert: Alert;
  reports: Report[];
  onInvestigated: (r: Report) => void;
  onReviewed: (r: Report) => void;
}) {
  const [investigating, setInvestigating] = useState(false);
  const [investigateError, setInvestigateError] = useState<string | null>(null);

  async function handleInvestigate() {
    setInvestigating(true);
    setInvestigateError(null);
    try {
      const report = await api.investigateAlert(alert.id);
      onInvestigated(report);
    } catch (err) {
      setInvestigateError(
        err instanceof ApiError ? err.message : "Investigation failed."
      );
    } finally {
      setInvestigating(false);
    }
  }

  return (
    <div className="flex flex-col gap-6 px-8 py-6">
      <div className="rounded-xl border border-border bg-surface-card p-5">
        <div className="flex flex-wrap items-center gap-2">
          <RuleBadge ruleCode={alert.rule_code} />
          <SeverityBadge severity={alert.severity} />
          <AlertStatusBadge status={alert.status} />
        </div>
        <p className="mt-3 text-sm text-ink-primary">{alert.description}</p>
        <dl className="mt-4 grid grid-cols-2 gap-3 text-sm sm:grid-cols-3">
          <div>
            <dt className="text-xs text-ink-muted">Transaction</dt>
            <dd className="font-mono text-ink-secondary">#{alert.transaction_id}</dd>
          </div>
          <div>
            <dt className="text-xs text-ink-muted">Created</dt>
            <dd className="text-ink-secondary">
              {new Date(alert.created_at).toLocaleString()}
            </dd>
          </div>
        </dl>
        <details className="mt-4">
          <summary className="cursor-pointer text-xs font-medium text-ink-muted hover:text-ink-secondary">
            Raw rule evidence
          </summary>
          <pre className="mt-2 overflow-x-auto rounded-md bg-surface-page p-3 text-xs text-ink-secondary">
            {JSON.stringify(alert.evidence, null, 2)}
          </pre>
        </details>
      </div>

      <div>
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-medium text-ink-primary">
            AI investigation reports ({reports.length})
          </h2>
          <button
            onClick={handleInvestigate}
            disabled={investigating}
            className="rounded-md bg-cat-1 px-3 py-1.5 text-xs font-medium text-white hover:opacity-90 disabled:opacity-50"
          >
            {investigating
              ? "Investigating (can take ~1 min)..."
              : reports.length > 0
                ? "Run new investigation"
                : "Run investigation"}
          </button>
        </div>
        {investigateError && (
          <div className="mb-3">
            <ErrorState message={investigateError} />
          </div>
        )}
        {reports.length === 0 ? (
          <EmptyState
            title="No investigation yet"
            description="Run the AI investigation workflow to generate a grounded report for this alert."
          />
        ) : (
          <div className="space-y-4">
            {[...reports].reverse().map((r) => (
              <ReportCard key={r.id} report={r} onReviewed={onReviewed} />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

export default function AlertDetailPage() {
  const params = useParams<{ id: string }>();
  const alertId = Number(params.id);

  const alertsState = useAsync(useCallback(() => api.listAlerts(), []));
  const reportsState = useAsync(
    useCallback(() => api.listReportsForAlert(alertId), [alertId])
  );

  const [localReports, setLocalReports] = useState<Report[] | null>(null);
  const reports = localReports ?? (reportsState.status === "success" ? reportsState.data : []);

  function handleInvestigated(report: Report) {
    setLocalReports([...reports, report]);
  }
  function handleReviewed(updated: Report) {
    setLocalReports(reports.map((r) => (r.id === updated.id ? updated : r)));
  }

  const alert =
    alertsState.status === "success"
      ? alertsState.data.find((a) => a.id === alertId)
      : undefined;

  return (
    <>
      <PageHeader
        title={`Alert ALT-${alertId}`}
        description="Investigation evidence, AI findings, and the analyst review decision."
        actions={
          <Link
            href="/alerts"
            className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-ink-secondary hover:bg-surface-hover"
          >
            Back to queue
          </Link>
        }
      />
      {(alertsState.status === "loading" || reportsState.status === "loading") && (
        <div className="px-8">
          <LoadingState />
        </div>
      )}
      {alertsState.status === "error" && (
        <div className="px-8 py-6">
          <ErrorState message={alertsState.error} onRetry={alertsState.refetch} />
        </div>
      )}
      {alertsState.status === "success" && !alert && (
        <div className="px-8 py-6">
          <EmptyState
            title={`Alert ${alertId} not found`}
            description="It may not exist, or the backend's demo data was reset."
          />
        </div>
      )}
      {alertsState.status === "success" && alert && reportsState.status !== "loading" && (
        <AlertDetail
          alert={alert}
          reports={reports}
          onInvestigated={handleInvestigated}
          onReviewed={handleReviewed}
        />
      )}
    </>
  );
}
