export type WorkflowStatus =
  | "planning"
  | "awaiting_approval"
  | "approval_recorded"
  | "approved_for_patch"
  | "patch_ready"
  | "patch_failed"
  | "tests_passed"
  | "tests_failed"
  | "test_infrastructure_failed"
  | "critic_complete"
  | "critic_failed"
  | "repair_failed"
  | "awaiting_final_approval"
  | "final_approval_recorded"
  | "final_approved"
  | "final_rejected"
  | "export_failed"
  | "completed"
  | "rejected"
  | "planner_failed"
  | "validation_failed";

export interface EvidenceItem {
  chunk_id: string;
  path: string;
  symbol: string;
  chunk_type: string;
  start_line: number;
  end_line: number;
  origin: string;
  retrieval_rank: number | null;
  structural_causes: string[];
  source_text: string | null;
}

export interface RepairStep {
  order: number;
  description: string;
  affected_files: string[];
  evidence_chunk_ids: string[];
}

export interface RepairPlan {
  summary: string;
  diagnosis: string;
  proposed_files: string[];
  steps: RepairStep[];
  suggested_tests: string[];
}

export interface AttemptSummary {
  attempt_number: number;
  patch_hash: string;
  changed_files: string[];
  patch_status: string;
  test_status: string | null;
  test_run_id: string | null;
}

export interface PatchView {
  patch_hash: string;
  changed_files: string[];
  canonical_unified_diff: string;
  attempt_number: number;
}

export interface TestResultView {
  test_run_id: string;
  tested_patch_hash: string;
  mode: string;
  selectors: string[];
  status: string;
  exit_code: number | null;
  duration_ms: number;
  stdout: string;
  stderr: string;
  output_truncated: boolean;
  image_reference: string;
  image_id: string | null;
  failure_classification: string | null;
  failure_message: string | null;
}

export interface CriticView {
  summary: string;
  failure_diagnosis: string;
  retry_recommended: boolean;
  retry_instructions: Array<{
    description: string;
    affected_files: string[];
  }>;
  evidence_chunk_ids: string[];
}

export interface WorkflowView {
  thread_id: string;
  status: WorkflowStatus;
  issue: string;
  repository: { name: string; path: string };
  retrieval: {
    mode: string | null;
    degraded: boolean;
    degradation_reason: string | null;
    context_status: string | null;
    evidence_count: number;
  };
  evidence: EvidenceItem[];
  plan: RepairPlan | null;
  plan_hash: string | null;
  approved_file_scope: string[] | null;
  reviewer_comment: string | null;
  attempts: AttemptSummary[];
  patch: PatchView | null;
  test: TestResultView | null;
  critic: CriticView | null;
  final_review: {
    awaiting_decision: boolean;
    plan_summary: string;
    approved_file_scope: string[];
    final_changed_files: string[];
    final_patch_hash: string;
    tested_patch_hash: string;
    attempt_number: number;
    decision: { decision: "approve" | "reject"; comment: string | null } | null;
  } | null;
  export: {
    artifact_id: string;
    filename: string;
    patch_hash: string;
    changed_files: string[];
    test_run_id: string;
  } | null;
  error: {
    code: string;
    message: string;
    stage: string;
    classification: string | null;
  } | null;
}

export interface CreateWorkflowInput {
  repository_path: string;
  issue: string;
  thread_id?: string;
}

export interface ReviewDecision {
  decision: "approve" | "reject";
  comment?: string;
}

export class WorkflowApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly stage?: string;

  constructor(message: string, code: string, status: number, stage?: string) {
    super(message);
    this.name = "WorkflowApiError";
    this.code = code;
    this.status = status;
    this.stage = stage;
  }
}

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";

function apiBaseUrl(): string {
  return (import.meta.env.VITE_API_BASE_URL || DEFAULT_API_BASE_URL).replace(
    /\/$/,
    "",
  );
}

async function apiRequest<T>(
  path: string,
  init: RequestInit,
  signal?: AbortSignal,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${apiBaseUrl()}${path}`, { ...init, signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    throw new WorkflowApiError(
      "Could not reach the RepoPilot backend. The request was not resent.",
      "network_error",
      0,
    );
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new WorkflowApiError(
      "The backend returned an unreadable response.",
      "unreadable_response",
      response.status,
    );
  }
  if (!response.ok) {
    const detail = readErrorDetail(payload);
    throw new WorkflowApiError(
      detail?.message || "The workflow request failed safely.",
      detail?.code || "workflow_request_failed",
      response.status,
      detail?.stage,
    );
  }
  return payload as T;
}

function readErrorDetail(payload: unknown): {
  code?: string;
  message?: string;
  stage?: string;
} | null {
  if (typeof payload !== "object" || payload === null || !("detail" in payload)) {
    return null;
  }
  const detail = payload.detail;
  if (typeof detail === "string") return { message: detail };
  if (typeof detail !== "object" || detail === null) return null;
  return {
    code: "code" in detail && typeof detail.code === "string" ? detail.code : undefined,
    message:
      "message" in detail && typeof detail.message === "string"
        ? detail.message
        : undefined,
    stage:
      "stage" in detail && typeof detail.stage === "string"
        ? detail.stage
        : undefined,
  };
}

const jsonHeaders = { "Content-Type": "application/json" };

export function createWorkflow(
  input: CreateWorkflowInput,
  signal?: AbortSignal,
): Promise<WorkflowView> {
  return apiRequest<WorkflowView>(
    "/api/workflows",
    { method: "POST", headers: jsonHeaders, body: JSON.stringify(input) },
    signal,
  );
}

export function fetchWorkflow(
  threadId: string,
  signal?: AbortSignal,
): Promise<WorkflowView> {
  return apiRequest<WorkflowView>(
    `/api/workflows/${encodeURIComponent(threadId)}`,
    { method: "GET" },
    signal,
  );
}

export function submitPlanDecision(
  threadId: string,
  decision: ReviewDecision,
  planHash: string,
  signal?: AbortSignal,
): Promise<WorkflowView> {
  return apiRequest<WorkflowView>(
    `/api/workflows/${encodeURIComponent(threadId)}/plan-decision`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ ...decision, plan_hash: planHash }),
    },
    signal,
  );
}

export function submitFinalDecision(
  threadId: string,
  decision: ReviewDecision,
  patchHash: string,
  signal?: AbortSignal,
): Promise<WorkflowView> {
  return apiRequest<WorkflowView>(
    `/api/workflows/${encodeURIComponent(threadId)}/final-decision`,
    {
      method: "POST",
      headers: jsonHeaders,
      body: JSON.stringify({ ...decision, patch_hash: patchHash }),
    },
    signal,
  );
}
