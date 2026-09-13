import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import {
  createWorkflow,
  fetchWorkflow,
  submitFinalDecision,
  submitPlanDecision,
  type WorkflowView,
} from "./api/workflows";

vi.mock("./api/workflows", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./api/workflows")>();
  return {
    ...actual,
    createWorkflow: vi.fn(),
    fetchWorkflow: vi.fn(),
    submitPlanDecision: vi.fn(),
    submitFinalDecision: vi.fn(),
  };
});

const mockedCreate = vi.mocked(createWorkflow);
const mockedFetch = vi.mocked(fetchWorkflow);
const mockedPlanDecision = vi.mocked(submitPlanDecision);
const mockedFinalDecision = vi.mocked(submitFinalDecision);
const planHash = "a".repeat(64);
const patchHash = "b".repeat(64);

function workflow(overrides: Partial<WorkflowView> = {}): WorkflowView {
  return {
    thread_id: "thread-017",
    status: "awaiting_approval",
    issue: "Discounts increase the price instead of reducing it.",
    repository: { name: "toy-repo", path: "C:\\work\\toy-repo" },
    retrieval: {
      mode: "hybrid",
      degraded: false,
      degradation_reason: null,
      context_status: "complete",
      evidence_count: 1,
    },
    evidence: [
      {
        chunk_id: "chunk-pricing",
        path: "pricing.py",
        symbol: "apply_discount",
        chunk_type: "function",
        start_line: 1,
        end_line: 2,
        origin: "retrieved",
        retrieval_rank: 1,
        structural_causes: [],
        source_text: "def apply_discount(total, rate):\n    return total * (1 + rate)",
      },
    ],
    plan: {
      summary: "Correct the discount arithmetic.",
      diagnosis: "The rate is added instead of subtracted.",
      proposed_files: ["pricing.py"],
      steps: [
        {
          order: 1,
          description: "Subtract the discount rate.",
          affected_files: ["pricing.py"],
          evidence_chunk_ids: ["chunk-pricing"],
        },
      ],
      suggested_tests: ["tests/test_pricing.py"],
    },
    plan_hash: planHash,
    approved_file_scope: null,
    reviewer_comment: null,
    attempts: [],
    patch: null,
    test: null,
    critic: null,
    final_review: null,
    export: null,
    error: null,
    ...overrides,
  };
}

function testedWorkflow(overrides: Partial<WorkflowView> = {}): WorkflowView {
  return workflow({
    status: "awaiting_final_approval",
    approved_file_scope: ["pricing.py"],
    attempts: [
      {
        attempt_number: 1,
        patch_hash: patchHash,
        changed_files: ["pricing.py"],
        patch_status: "patch_ready",
        test_status: "passed",
        test_run_id: "c".repeat(64),
      },
    ],
    patch: {
      patch_hash: patchHash,
      changed_files: ["pricing.py"],
      canonical_unified_diff:
        "--- a/pricing.py\n+++ b/pricing.py\n@@ -1 +1 @@\n- return total * (1 + rate)\n+ return total * (1 - rate)\n",
      attempt_number: 1,
    },
    test: {
      test_run_id: "c".repeat(64),
      tested_patch_hash: patchHash,
      mode: "full",
      selectors: [],
      status: "passed",
      exit_code: 0,
      duration_ms: 320,
      stdout: "2 passed",
      stderr: "",
      output_truncated: false,
      image_reference: "repopilot-python-test:3.11-pytest9",
      image_id: `sha256:${"d".repeat(64)}`,
      failure_classification: null,
      failure_message: null,
    },
    final_review: {
      awaiting_decision: true,
      plan_summary: "Correct the discount arithmetic.",
      approved_file_scope: ["pricing.py"],
      final_changed_files: ["pricing.py"],
      final_patch_hash: patchHash,
      tested_patch_hash: patchHash,
      attempt_number: 1,
      decision: null,
    },
    ...overrides,
  });
}

async function startWith(value: WorkflowView) {
  mockedCreate.mockResolvedValueOnce(value);
  const user = userEvent.setup();
  render(<App />);
  await user.type(screen.getByRole("textbox", { name: "Repository path" }), "C:\\work\\toy-repo");
  await user.type(screen.getByRole("textbox", { name: "Issue" }), "Fix discount arithmetic");
  await user.click(screen.getByRole("button", { name: "Start Repair" }));
  await screen.findByRole("heading", { name: "Human Review Workspace" });
  return user;
}

describe("RepoPilot human review workspace", () => {
  beforeEach(() => {
    window.history.replaceState(null, "", "/");
    vi.clearAllMocks();
  });

  it("validates both required start fields", async () => {
    const user = userEvent.setup();
    render(<App />);
    await user.click(screen.getByRole("button", { name: "Start Repair" }));
    expect(mockedCreate).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Repository path and issue are required");
  });

  it("renders authoritative workflow evidence and plan state", async () => {
    await startWith(workflow());
    expect(screen.getByRole("heading", { name: "Repository Evidence" })).toBeVisible();
    expect(screen.getByText("Correct the discount arithmetic.")).toBeVisible();
    expect(screen.getAllByText("pricing.py").length).toBeGreaterThan(0);
  });

  it("shows exact plan hash and scope, then submits that displayed hash", async () => {
    mockedPlanDecision.mockResolvedValue(workflow({ status: "rejected" }));
    const user = await startWith(workflow());
    expect(screen.getByText(planHash)).toBeVisible();
    expect(screen.getByText("RepoPilot will be authorized to modify ONLY:")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Approve plan" }));
    expect(mockedPlanDecision).toHaveBeenCalledWith(
      "thread-017",
      { decision: "approve", comment: undefined },
      planHash,
    );
  });

  it("renders the canonical diff as text without interpreting repository HTML", async () => {
    const unsafe = "<img src=x onerror=alert(1)>";
    const value = testedWorkflow({
      status: "completed",
      evidence: [{ ...workflow().evidence[0], source_text: unsafe }],
      export: {
        artifact_id: patchHash,
        filename: `${patchHash}.patch`,
        patch_hash: patchHash,
        changed_files: ["pricing.py"],
        test_run_id: "c".repeat(64),
      },
    });
    const { container } = render(<App />);
    mockedCreate.mockResolvedValueOnce(value);
    const user = userEvent.setup();
    await user.type(screen.getByRole("textbox", { name: "Repository path" }), "repo");
    await user.type(screen.getByRole("textbox", { name: "Issue" }), "issue");
    await user.click(screen.getByRole("button", { name: "Start Repair" }));
    expect(await screen.findByLabelText("Canonical unified diff")).toHaveTextContent("return total * (1 - rate)");
    expect(screen.getByText(unsafe)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it.each([
    ["passed", "Passed"],
    ["failed", "Failed"],
    ["infrastructure_failed", "Infrastructure failure"],
    ["timed_out", "Timed out"],
  ])("distinguishes %s test evidence", async (status, label) => {
    const base = testedWorkflow();
    await startWith(testedWorkflow({
      status: status === "infrastructure_failed" ? "test_infrastructure_failed" : base.status,
      test: { ...base.test!, status },
    }));
    expect(screen.getByText(label)).toBeVisible();
  });

  it("shows critic and bounded retry history only when critic data exists", async () => {
    const base = testedWorkflow();
    await startWith(testedWorkflow({
      patch: { ...base.patch!, attempt_number: 2 },
      critic: {
        summary: "The sign fix was incomplete.",
        failure_diagnosis: "A boundary case still failed.",
        retry_recommended: true,
        retry_instructions: [{ description: "Handle the boundary.", affected_files: ["pricing.py"] }],
        evidence_chunk_ids: ["chunk-pricing"],
      },
      attempts: [
        ...base.attempts,
        { ...base.attempts[0], attempt_number: 2, patch_hash: "e".repeat(64) },
      ],
    }));
    expect(screen.getByText("RepoPilot permits at most one repair retry.")).toBeVisible();
    expect(screen.getByText(/Attempt 2/)).toBeVisible();
  });

  it("submits the exact displayed final patch hash", async () => {
    mockedFinalDecision.mockResolvedValue(testedWorkflow({ status: "final_rejected" }));
    const user = await startWith(testedWorkflow());
    await user.click(screen.getByRole("button", { name: "Approve & export patch" }));
    expect(mockedFinalDecision).toHaveBeenCalledWith(
      "thread-017",
      { decision: "approve", comment: undefined },
      patchHash,
    );
  });

  it.each(["rejected", "completed"] as const)("does not show invalid approval actions for %s", async (status) => {
    const value = status === "completed"
      ? testedWorkflow({ status, export: { artifact_id: patchHash, filename: `${patchHash}.patch`, patch_hash: patchHash, changed_files: ["pricing.py"], test_run_id: "c".repeat(64) } })
      : workflow({ status });
    await startWith(value);
    expect(screen.queryByRole("button", { name: "Approve plan" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve & export patch" })).not.toBeInTheDocument();
  });

  it("disables the state-changing start button while a request is pending", async () => {
    let resolveRequest!: (value: WorkflowView) => void;
    mockedCreate.mockReturnValue(new Promise((resolve) => { resolveRequest = resolve; }));
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByRole("textbox", { name: "Repository path" }), "repo");
    await user.type(screen.getByRole("textbox", { name: "Issue" }), "issue");
    await user.click(screen.getByRole("button", { name: "Start Repair" }));
    expect(screen.getByRole("button", { name: "Running analysis…" })).toBeDisabled();
    resolveRequest(workflow());
    expect(await screen.findByRole("heading", { name: "Human Review Workspace" })).toBeVisible();
  });

  it("reopens a URL thread through one read-only GET", async () => {
    window.history.replaceState(null, "", "/?thread=thread-017");
    mockedFetch.mockResolvedValue(workflow());
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Human Review Workspace" })).toBeVisible();
    expect(mockedFetch).toHaveBeenCalledTimes(1);
    expect(mockedCreate).not.toHaveBeenCalled();
  });
});
