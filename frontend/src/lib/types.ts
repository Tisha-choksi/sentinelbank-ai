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
