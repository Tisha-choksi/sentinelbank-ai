// Types mirror the backend response models exactly -- see API_CONTRACT.md
// at the repo root. Nothing here should be more "complete" than what the
// backend actually returns; extend the backend first, not the types.

export type Transaction = {
  transaction_ref: string;
  from_account: string;
  to_account: string;
  amount: string;
  currency: string;
  id: number;
  status: string;
  created_at: string;
};

export type RuleCode = "TXN_HIGH_VALUE" | "TXN_VELOCITY" | "TXN_CIRCULAR_FLOW";
export type Severity = "LOW" | "MEDIUM" | "HIGH" | "CRITICAL";
export type AlertStatus = "OPEN" | "IN_REVIEW" | "RESOLVED" | "DISMISSED";

export type Alert = {
  id: number;
  transaction_id: number;
  case_id: number | null;
  rule_code: RuleCode;
  severity: Severity;
  status: AlertStatus;
  description: string;
  evidence: Record<string, unknown>;
  created_at: string;
};

export type ReportStatus =
  | "PENDING_REVIEW"
  | "FAILED"
  | "APPROVED"
  | "DISMISSED"
  | "ESCALATED";

export type InvestigationFindings = {
  summary: string;
  confirmed_facts: string[];
  hypotheses: string[];
  uncertainties: string[];
  recommended_checks: string[];
  cited_transaction_refs: string[];
  cited_accounts: string[];
};

export type FailedFindings = { error: string };

export type TransactionEvidence = {
  transaction_ref: string;
  from_account: string;
  to_account: string;
  amount: string;
  currency: string;
  status: string;
  created_at: string;
};

export type AccountEvidence = {
  account_number: string;
  owner_name: string;
  account_type: string;
  status: string;
};

export type EvidenceSnapshot = {
  alert_id: number;
  rule_code: string;
  severity: string;
  alert_description: string;
  alert_evidence: Record<string, unknown>;
  primary_transaction: TransactionEvidence;
  related_transactions: TransactionEvidence[];
  known_accounts: AccountEvidence[];
  missing_evidence: string[];
};

export type Report = {
  id: number;
  alert_id: number;
  case_id: number | null;
  status: ReportStatus;
  model_provider: string;
  model_name: string;
  prompt_version: string;
  summary: string;
  findings: InvestigationFindings | FailedFindings;
  evidence_snapshot: EvidenceSnapshot;
  created_at: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
};

export function isFailedFindings(
  findings: Report["findings"]
): findings is FailedFindings {
  return typeof (findings as FailedFindings)?.error === "string";
}

export type ReviewStatus = "APPROVED" | "DISMISSED" | "ESCALATED";

// --- Evaluation (offline benchmark artifacts, not live telemetry) ---

export type EvaluationRunIndexEntry = {
  id: string;
  label: string;
  available: boolean;
  error: string | null;
  model_name: string | null;
  prompt_version: string | null;
  scenario_count: number | null;
  generated_at: string | null;
};

export type EvaluationRunSummary = {
  id: string;
  label: string;
  file_name: string;
  generated_at: string;
  scope_note: string | null;
  scenario_count: number;
  category_counts: Record<string, number>;
  evidence_grounding: {
    grounding_rate: number | null;
    unsupported_claim_scenarios: string[];
  };
  citation_validity: {
    citation_validity_rate: number | null;
    invalid_citation_examples: string[];
    hallucination_catch_rate: number | null;
  };
  factual_accuracy: {
    facts_hit_rate: number | null;
    uncertainty_hit_rate: number | null;
    uncertainty_hit_rate_v2: number | null;
    forbidden_claim_violation_count: number;
    forbidden_claim_violation_scenarios: string[];
  };
  latency_and_reliability: {
    median_duration_seconds: number | null;
    p95_duration_seconds: number | null;
    operational_timeout_rate: number | null;
    operational_timeout_rate_label: string | null;
    failure_rate_by_category: Record<string, number>;
    unexpected_status_mismatches: string[];
    timeout_handling_rate: number | null;
  };
  system_resilience: {
    adversarial_rejection_rate: number | null;
    hallucination_catch_rate: number | null;
  } | null;
  acceptance_criteria: {
    zero_unsupported_citations: boolean | null;
    zero_invalid_citations_in_successful_reports: boolean | null;
  } | null;
  run_config: {
    model_name: string | null;
    temperature: number | null;
    sample_per_category: number | null;
    prompt_version: string | null;
  };
};
