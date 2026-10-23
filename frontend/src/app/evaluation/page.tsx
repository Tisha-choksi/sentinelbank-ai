"use client";

import { useCallback } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { api } from "@/lib/api";
import type { EvaluationRunIndexEntry, EvaluationRunSummary } from "@/lib/types";
import { useAsync } from "@/lib/useAsync";
import { fmtDateTime, fmtPct, fmtSeconds } from "@/lib/format";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { BenchmarkNotice } from "@/components/BenchmarkNotice";
import { ErrorState, LoadingState, EmptyState } from "@/components/States";

const QWEN_ID = "qwen2.5-coder_7b_v2";
const LLAMA_ID = "llama3.1_8b_v2";
const QWEN_COLOR = "var(--color-cat-2)";
const LLAMA_COLOR = "var(--color-cat-1)";

type EvalData = {
  index: EvaluationRunIndexEntry[];
  details: Record<string, EvaluationRunSummary>;
};

async function loadEvaluationData(): Promise<EvalData> {
  const index = await api.listEvaluationRuns();
  const availableIds = index.filter((r) => r.available).map((r) => r.id);
  const details = await Promise.all(availableIds.map((id) => api.getEvaluationRun(id)));
  const byId: Record<string, EvaluationRunSummary> = {};
  details.forEach((d) => (byId[d.id] = d));
  return { index, details: byId };
}

function ChartTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: Array<{ name: string; value: number; color: string }>;
  label?: string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-border bg-surface-card-raised px-3 py-2 text-xs shadow-lg">
      <p className="mb-1 text-ink-secondary">{label}</p>
      {payload.map((p) => (
        <p key={p.name} style={{ color: p.color }}>
          {p.name}: {p.value.toFixed(1)}
        </p>
      ))}
    </div>
  );
}

// --- Section 1: model comparison ---

function ModelComparisonSection({
  qwen,
  llama,
}: {
  qwen: EvaluationRunSummary;
  llama: EvaluationRunSummary;
}) {
  const qualityData = [
    {
      metric: "Evidence grounding",
      Qwen: (qwen.evidence_grounding.grounding_rate ?? 0) * 100,
      Llama: (llama.evidence_grounding.grounding_rate ?? 0) * 100,
    },
    {
      metric: "Facts hit rate",
      Qwen: (qwen.factual_accuracy.facts_hit_rate ?? 0) * 100,
      Llama: (llama.factual_accuracy.facts_hit_rate ?? 0) * 100,
    },
  ];

  const latencyData = [
    {
      metric: "Median",
      Qwen: qwen.latency_and_reliability.median_duration_seconds ?? 0,
      Llama: llama.latency_and_reliability.median_duration_seconds ?? 0,
    },
    {
      metric: "P95",
      Qwen: qwen.latency_and_reliability.p95_duration_seconds ?? 0,
      Llama: llama.latency_and_reliability.p95_duration_seconds ?? 0,
    },
  ];

  const unsupportedQwen = 1 - (qwen.evidence_grounding.grounding_rate ?? 1);
  const unsupportedLlama = 1 - (llama.evidence_grounding.grounding_rate ?? 1);

  return (
    <section>
      <h2 className="mb-1 text-sm font-medium text-ink-primary">
        1. Model comparison
      </h2>
      <p className="mb-3 text-xs text-ink-muted">
        {qwen.label} vs {llama.label} -- same 30 sampled scenarios, same
        temperature, same prompt version.
      </p>

      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <StatCard
          label="Unsupported citations -- Qwen"
          value={fmtPct(unsupportedQwen)}
          accent={unsupportedQwen > 0 ? "var(--color-status-warning)" : undefined}
        />
        <StatCard
          label="Unsupported citations -- Llama"
          value={fmtPct(unsupportedLlama)}
          accent={unsupportedLlama > 0 ? "var(--color-status-warning)" : undefined}
        />
        <StatCard
          label="Median latency -- Qwen"
          value={fmtSeconds(qwen.latency_and_reliability.median_duration_seconds)}
        />
        <StatCard
          label="Median latency -- Llama"
          value={fmtSeconds(llama.latency_and_reliability.median_duration_seconds)}
        />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-2">
        <div className="rounded-xl border border-border bg-surface-card p-5">
          <h3 className="mb-3 text-sm font-medium text-ink-primary">
            Report quality (%)
          </h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={qualityData} barGap={4}>
              <CartesianGrid vertical={false} stroke="var(--color-gridline)" />
              <XAxis
                dataKey="metric"
                tickLine={false}
                axisLine={{ stroke: "var(--color-axis)" }}
                tick={{ fill: "var(--color-ink-muted)", fontSize: 12 }}
              />
              <YAxis
                domain={[0, 100]}
                tickLine={false}
                axisLine={false}
                tick={{ fill: "var(--color-ink-muted)", fontSize: 12 }}
                width={32}
              />
              <Tooltip
                cursor={{ fill: "var(--color-surface-hover)" }}
                content={<ChartTooltip />}
              />
              <Legend
                wrapperStyle={{ fontSize: 12, color: "var(--color-ink-secondary)" }}
              />
              <Bar dataKey="Qwen" fill={QWEN_COLOR} radius={[4, 4, 0, 0]} maxBarSize={40} />
              <Bar dataKey="Llama" fill={LLAMA_COLOR} radius={[4, 4, 0, 0]} maxBarSize={40} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="rounded-xl border border-border bg-surface-card p-5">
          <h3 className="mb-3 text-sm font-medium text-ink-primary">
            Latency (seconds)
          </h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={latencyData} barGap={4}>
              <CartesianGrid vertical={false} stroke="var(--color-gridline)" />
              <XAxis
                dataKey="metric"
                tickLine={false}
                axisLine={{ stroke: "var(--color-axis)" }}
                tick={{ fill: "var(--color-ink-muted)", fontSize: 12 }}
              />
              <YAxis
                tickLine={false}
                axisLine={false}
                tick={{ fill: "var(--color-ink-muted)", fontSize: 12 }}
                width={32}
              />
              <Tooltip
                cursor={{ fill: "var(--color-surface-hover)" }}
                content={<ChartTooltip />}
              />
              <Legend
                wrapperStyle={{ fontSize: 12, color: "var(--color-ink-secondary)" }}
              />
              <Bar dataKey="Qwen" fill={QWEN_COLOR} radius={[4, 4, 0, 0]} maxBarSize={40} />
              <Bar dataKey="Llama" fill={LLAMA_COLOR} radius={[4, 4, 0, 0]} maxBarSize={40} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </div>
    </section>
  );
}

// --- Section 2: operational reliability ---

function ReliabilityRow({
  label,
  qwenValue,
  llamaValue,
}: {
  label: string;
  qwenValue: string;
  llamaValue: string;
}) {
  return (
    <tr className="border-b border-border last:border-0">
      <td className="px-4 py-2.5 text-ink-secondary">{label}</td>
      <td className="px-4 py-2.5 text-right tabular-nums text-ink-primary">
        {qwenValue}
      </td>
      <td className="px-4 py-2.5 text-right tabular-nums text-ink-primary">
        {llamaValue}
      </td>
    </tr>
  );
}

function OperationalReliabilitySection({
  qwen,
  llama,
}: {
  qwen: EvaluationRunSummary;
  llama: EvaluationRunSummary;
}) {
  return (
    <section>
      <h2 className="mb-1 text-sm font-medium text-ink-primary">
        2. Operational reliability
      </h2>
      <p className="mb-3 text-xs text-ink-muted">
        From this same benchmark run -- these describe the 30-scenario test,
        not an ongoing service-health signal.
      </p>
      <div className="overflow-hidden rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-surface-card text-left text-xs uppercase tracking-wide text-ink-muted">
              <th className="px-4 py-3 font-medium">Metric</th>
              <th className="px-4 py-3 text-right font-medium">Qwen 2.5 Coder 7B</th>
              <th className="px-4 py-3 text-right font-medium">Llama 3.1 8B</th>
            </tr>
          </thead>
          <tbody className="bg-surface-page">
            <ReliabilityRow
              label="Operational timeout rate"
              qwenValue={
                qwen.latency_and_reliability.operational_timeout_rate_label ??
                fmtPct(qwen.latency_and_reliability.operational_timeout_rate)
              }
              llamaValue={
                llama.latency_and_reliability.operational_timeout_rate_label ??
                fmtPct(llama.latency_and_reliability.operational_timeout_rate)
              }
            />
            <ReliabilityRow
              label="Adversarial rejection rate"
              qwenValue={fmtPct(qwen.system_resilience?.adversarial_rejection_rate)}
              llamaValue={fmtPct(llama.system_resilience?.adversarial_rejection_rate)}
            />
            <ReliabilityRow
              label="Forbidden-claim violations"
              qwenValue={String(qwen.factual_accuracy.forbidden_claim_violation_count)}
              llamaValue={String(llama.factual_accuracy.forbidden_claim_violation_count)}
            />
            <ReliabilityRow
              label="Scenario completion"
              qwenValue={`${qwen.scenario_count}/${qwen.scenario_count}`}
              llamaValue={`${llama.scenario_count}/${llama.scenario_count}`}
            />
          </tbody>
        </table>
      </div>
    </section>
  );
}

// --- Section 3: evaluation history ---

function HistorySection({ index }: { index: EvaluationRunIndexEntry[] }) {
  return (
    <section>
      <h2 className="mb-1 text-sm font-medium text-ink-primary">
        3. Evaluation history
      </h2>
      <p className="mb-3 text-xs text-ink-muted">
        Every saved benchmark artifact -- v1 and v2 results are both
        preserved; nothing here is ever overwritten by a later run.
      </p>
      <div className="overflow-hidden rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-surface-card text-left text-xs uppercase tracking-wide text-ink-muted">
              <th className="px-4 py-3 font-medium">Run</th>
              <th className="px-4 py-3 font-medium">Model</th>
              <th className="px-4 py-3 font-medium">Prompt version</th>
              <th className="px-4 py-3 font-medium">Scenarios</th>
              <th className="px-4 py-3 font-medium">Generated</th>
              <th className="px-4 py-3 font-medium">Status</th>
            </tr>
          </thead>
          <tbody className="bg-surface-page">
            {index.map((run) => (
              <tr key={run.id} className="border-b border-border last:border-0">
                <td className="px-4 py-2.5 font-mono text-xs text-ink-primary">
                  {run.id}
                </td>
                <td className="px-4 py-2.5 text-ink-secondary">
                  {run.model_name ?? "--"}
                </td>
                <td className="px-4 py-2.5 text-ink-secondary">
                  {run.prompt_version ?? "--"}
                </td>
                <td className="tabular-nums px-4 py-2.5 text-ink-secondary">
                  {run.scenario_count ?? "--"}
                </td>
                <td className="tabular-nums px-4 py-2.5 text-ink-muted">
                  {fmtDateTime(run.generated_at)}
                </td>
                <td className="px-4 py-2.5">
                  {run.available ? (
                    <span style={{ color: "var(--color-status-good)" }}>
                      Available
                    </span>
                  ) : (
                    <span
                      title={run.error ?? undefined}
                      style={{ color: "var(--color-status-critical)" }}
                    >
                      Unavailable
                    </span>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

// --- Section 4: uncertainty scorer v1 vs v2 ---

function UncertaintyScorerSection({ index }: { index: EvaluationRunIndexEntry[] }) {
  return (
    <section>
      <h2 className="mb-1 text-sm font-medium text-ink-primary">
        4. Uncertainty scorer: v1 vs v2
      </h2>
      <div className="mb-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div className="rounded-lg border border-border bg-surface-card p-3">
          <p className="text-xs font-medium text-ink-primary">
            v1 -- literal phrase match
          </p>
          <p className="mt-1 text-xs text-ink-muted">
            Checks the <code className="text-ink-secondary">uncertainties</code>{" "}
            field only, for one exact expected phrase (e.g. &quot;account
            registry&quot;). Misses a model that correctly surfaces the same
            gap in different words.
          </p>
        </div>
        <div className="rounded-lg border border-border bg-surface-card p-3">
          <p className="text-xs font-medium text-ink-primary">
            v2 -- synonym-aware (corrected)
          </p>
          <p className="mt-1 text-xs text-ink-muted">
            Checks <code className="text-ink-secondary">uncertainties</code>,{" "}
            <code className="text-ink-secondary">recommended_checks</code>, and{" "}
            <code className="text-ink-secondary">summary</code> together,
            against a synonym set per concept. Not directly comparable to
            v1 -- the scoring logic changed, not just the threshold.
          </p>
        </div>
      </div>
      <div className="overflow-hidden rounded-xl border border-border">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border bg-surface-card text-left text-xs uppercase tracking-wide text-ink-muted">
              <th className="px-4 py-3 font-medium">Run</th>
              <th className="px-4 py-3 text-right font-medium">
                Uncertainty hit rate (v1)
              </th>
              <th className="px-4 py-3 text-right font-medium">
                Uncertainty hit rate (v2)
              </th>
            </tr>
          </thead>
          <tbody className="bg-surface-page">
            {index
              .filter((r) => r.available)
              .map((run) => (
                <UncertaintyRow key={run.id} runId={run.id} />
              ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function UncertaintyRow({ runId }: { runId: string }) {
  const state = useAsync(useCallback(() => api.getEvaluationRun(runId), [runId]));
  if (state.status !== "success") {
    return (
      <tr className="border-b border-border last:border-0">
        <td className="px-4 py-2.5 font-mono text-xs text-ink-muted" colSpan={3}>
          {runId} -- {state.status === "error" ? state.error : "loading..."}
        </td>
      </tr>
    );
  }
  const run = state.data;
  const v2 = run.factual_accuracy.uncertainty_hit_rate_v2;
  return (
    <tr className="border-b border-border last:border-0">
      <td className="px-4 py-2.5 font-mono text-xs text-ink-primary">{run.id}</td>
      <td className="tabular-nums px-4 py-2.5 text-right text-ink-primary">
        {fmtPct(run.factual_accuracy.uncertainty_hit_rate)}
      </td>
      <td className="tabular-nums px-4 py-2.5 text-right">
        {v2 === null || v2 === undefined ? (
          <span className="text-ink-muted" title="Captured before the v2 scorer existed">
            not available
          </span>
        ) : (
          <span className="text-ink-primary">{fmtPct(v2)}</span>
        )}
      </td>
    </tr>
  );
}

// --- page ---

function EvaluationContent({ data }: { data: EvalData }) {
  const qwen = data.details[QWEN_ID];
  const llama = data.details[LLAMA_ID];

  return (
    <div className="flex flex-col gap-8 px-8 py-6">
      <BenchmarkNotice />

      {qwen && llama ? (
        <>
          <ModelComparisonSection qwen={qwen} llama={llama} />
          <OperationalReliabilitySection qwen={qwen} llama={llama} />
        </>
      ) : (
        <EmptyState
          title="Current-prompt comparison unavailable"
          description={`Expected both "${QWEN_ID}" and "${LLAMA_ID}" result artifacts to compare sections 1 and 2.`}
        />
      )}

      <HistorySection index={data.index} />
      <UncertaintyScorerSection index={data.index} />
    </div>
  );
}

export default function EvaluationPage() {
  const state = useAsync(useCallback(() => loadEvaluationData(), []));

  return (
    <>
      <PageHeader
        title="Model Evaluation"
        description="Offline benchmark results comparing candidate models against the investigation-evaluation dataset."
      />
      {state.status === "loading" && (
        <div className="px-8">
          <LoadingState label="Loading evaluation results..." />
        </div>
      )}
      {state.status === "error" && (
        <div className="px-8 py-6">
          <ErrorState message={state.error} onRetry={state.refetch} />
        </div>
      )}
      {state.status === "success" && <EvaluationContent data={state.data} />}
    </>
  );
}
