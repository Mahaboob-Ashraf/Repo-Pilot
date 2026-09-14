import { act, render, screen, within } from "@testing-library/react";
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
  await user.click(screen.getByRole("button", { name: "Analyze repository" }));
  await screen.findByText(`Workflow status: ${value.status.replaceAll("_", " ")}`);
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
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Analyze repository" }));
    expect(mockedCreate).not.toHaveBeenCalled();
    expect(screen.getAllByRole("alert")).toHaveLength(2);
    expect(screen.getByText("Repository path is required.")).toBeVisible();
    expect(screen.getByText("Issue is required.")).toBeVisible();
    expect(screen.getByRole("textbox", { name: "Repository path" })).toHaveFocus();
    await user.type(screen.getByRole("textbox", { name: "Repository path" }), "C:\\work\\repo");
    expect(screen.queryByText("Repository path is required.")).not.toBeInTheDocument();
  });

  it("keeps repository validation inline when the backend rejects the path", async () => {
    const { WorkflowApiError } = await import("./api/workflows");
    mockedCreate.mockRejectedValueOnce(new WorkflowApiError("invalid", "invalid_repository", 400));
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByRole("textbox", { name: "Repository path" }), "C:\\missing");
    await user.type(screen.getByRole("textbox", { name: "Issue" }), "Fix the parser defect");
    await user.click(screen.getByRole("button", { name: "Analyze repository" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Repository path must identify a readable local Python directory.");
    expect(screen.queryByText("Request not completed")).not.toBeInTheDocument();
  });

  it("renders authoritative workflow evidence and plan state", async () => {
    await startWith(workflow());
    expect(screen.getByRole("heading", { name: "Repair plan" })).toBeVisible();
    expect(screen.getByText("Correct the discount arithmetic.")).toBeVisible();
    expect(screen.getAllByText("pricing.py").length).toBeGreaterThan(0);
  });

  it("shows exact plan hash and scope, then submits that displayed hash", async () => {
    mockedPlanDecision.mockResolvedValue(workflow({ status: "rejected" }));
    const user = await startWith(workflow());
    expect(screen.getByText(planHash)).toBeVisible();
    expect(screen.getByText("RepoPilot will be authorized to modify ONLY:")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Approve plan and file scope" }));
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
    await user.click(screen.getByRole("button", { name: "Analyze repository" }));
    await screen.findByRole("heading", { name: "Repair complete" });
    await user.click(screen.getByRole("button", { name: /Patch complete/ }));
    expect(await screen.findByLabelText("Canonical unified diff")).toHaveTextContent("return total * (1 - rate)");
    await user.click(screen.getByRole("button", { name: /Retrieval complete/ }));
    await user.click(screen.getByRole("button", { name: /pricing.py:1/ }));
    expect(screen.getByText(unsafe)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it.each([
    ["passed", "Passed"],
    ["failed", "Test failure"],
    ["infrastructure_failed", "Infrastructure failure"],
    ["timed_out", "Timed out"],
    ["no_tests_collected", "No tests collected"],
    ["pytest_error", "Pytest error"],
  ])("distinguishes %s test evidence", async (status, label) => {
    const base = testedWorkflow();
    const user = await startWith(testedWorkflow({
      status: status === "infrastructure_failed" ? "test_infrastructure_failed" : base.status,
      test: { ...base.test!, status },
    }));
    await user.click(screen.getByRole("button", { name: /Tests (complete|failed|Current checkpoint)/ }));
    expect(screen.getAllByText(label)[0]).toBeVisible();
  });

  it("shows critic and bounded retry history only when critic data exists", async () => {
    const base = testedWorkflow();
    const user = await startWith(testedWorkflow({
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
    await user.click(screen.getByRole("button", { name: /Tests complete/ }));
    expect(screen.getByText(/RepoPilot permits at most one repair retry/)).toBeVisible();
    expect(screen.getAllByText(/Attempt 2/)[0]).toBeVisible();
  });

  it("submits the exact displayed final patch hash", async () => {
    mockedFinalDecision.mockResolvedValue(testedWorkflow({ status: "final_rejected" }));
    const user = await startWith(testedWorkflow());
    await user.click(screen.getByRole("button", { name: "Approve tested patch for export" }));
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
    expect(screen.queryByRole("button", { name: "Approve plan and file scope" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve tested patch for export" })).not.toBeInTheDocument();
  });

  it("disables the state-changing start button while a request is pending", async () => {
    let resolveRequest!: (value: WorkflowView) => void;
    mockedCreate.mockReturnValue(new Promise((resolve) => { resolveRequest = resolve; }));
    const user = userEvent.setup();
    render(<App />);
    await user.type(screen.getByRole("textbox", { name: "Repository path" }), "repo");
    await user.type(screen.getByRole("textbox", { name: "Issue" }), "issue");
    await user.click(screen.getByRole("button", { name: "Analyze repository" }));
    expect(screen.getByRole("button", { name: "Analyzing repository…" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Analyzing repository…" }));
    expect(mockedCreate).toHaveBeenCalledTimes(1);
    resolveRequest(workflow());
    expect(await screen.findByRole("heading", { name: "Plan review" })).toBeVisible();
  });

  it("reopens a URL thread through one read-only GET", async () => {
    window.history.replaceState(null, "", "/?thread=thread-017");
    mockedFetch.mockResolvedValue(workflow());
    render(<App />);
    expect(await screen.findByRole("heading", { name: "Plan review" })).toBeVisible();
    expect(mockedFetch).toHaveBeenCalledTimes(1);
    expect(mockedCreate).not.toHaveBeenCalled();
  });

  it("persists theme choices and restores them after remount", async () => {
    const user = userEvent.setup();
    const view = render(<App />);
    expect(document.documentElement.dataset.theme).toBe("dark");
    await user.click(screen.getByRole("button", { name: "Light" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    expect(localStorage.getItem("repopilot-theme")).toBe("light");
    view.unmount(); render(<App />);
    expect(screen.getByRole("button", { name: "Light" })).toHaveAttribute("aria-pressed", "true");
  });

  it("follows system color changes only in System mode", async () => {
    const listeners = new Set<() => void>();
    const media = { matches: false, media: "(prefers-color-scheme: dark)", onchange: null,
      addEventListener: (_: string, listener: () => void) => listeners.add(listener),
      removeEventListener: (_: string, listener: () => void) => listeners.delete(listener),
      addListener: vi.fn(), removeListener: vi.fn(), dispatchEvent: vi.fn() };
    vi.spyOn(window, "matchMedia").mockReturnValue(media as unknown as MediaQueryList);
    const user = userEvent.setup(); render(<App />);
    await user.click(screen.getByRole("button", { name: "System" }));
    expect(document.documentElement.dataset.theme).toBe("light");
    act(() => { media.matches = true; listeners.forEach((listener) => listener()); });
    expect(document.documentElement.dataset.theme).toBe("dark");
    await user.click(screen.getByRole("button", { name: "Light" }));
    act(() => { listeners.forEach((listener) => listener()); });
    expect(document.documentElement.dataset.theme).toBe("light");
  });

  it("views completed stages without executing or refreshing workflow actions", async () => {
    const user = await startWith(testedWorkflow());
    await user.click(screen.getByRole("button", { name: /Retrieval complete/ }));
    expect(screen.getByRole("heading", { name: "Evidence" })).toBeVisible();
    expect(screen.getByRole("button", { name: /Retrieval complete/ })).toHaveAttribute("aria-current", "page");
    expect(screen.getByText(/Viewing retrieval/)).toBeVisible();
    await user.selectOptions(screen.getByRole("combobox", { name: "Stage" }), "patch");
    expect(screen.getByRole("heading", { name: "Patch diff" })).toBeVisible();
    expect(mockedCreate).toHaveBeenCalledTimes(1);
    expect(mockedPlanDecision).not.toHaveBeenCalled(); expect(mockedFinalDecision).not.toHaveBeenCalled(); expect(mockedFetch).not.toHaveBeenCalled();
  });

  it("opens exact citation source in a drawer and restores focus after closing", async () => {
    vi.spyOn(window, "matchMedia").mockReturnValue({ matches: false, addEventListener: vi.fn(), removeEventListener: vi.fn() } as unknown as MediaQueryList);
    const user = await startWith(workflow());
    await user.click(screen.getByRole("button", { name: /Retrieval complete/ }));
    const citation = screen.getByRole("button", { name: /pricing\.py:1–2/ });
    await user.click(citation);
    expect(citation).toHaveAttribute("aria-pressed", "true");
    const drawer = screen.getByRole("dialog", { name: "Source context" });
    expect(within(drawer).getByText("chunk-pricing")).toBeVisible();
    expect(within(drawer).getByText("return total * (1 + rate)")).toBeVisible();
    await user.click(within(drawer).getByRole("button", { name: "Close context" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument(); expect(citation).toHaveFocus();
    expect(mockedPlanDecision).not.toHaveBeenCalled();
  });

  it("does not fabricate source for an unavailable citation", async () => {
    const user = await startWith(workflow({ evidence: [{ ...workflow().evidence[0], source_text: null }] }));
    await user.click(screen.getByRole("button", { name: "pricing.py:1–2" }));
    expect(screen.getByText("Source context is unavailable for this citation.")).toBeVisible();
  });

  it("guards duplicate plan decisions and exposes comments", async () => {
    let resolve!: (value: WorkflowView) => void;
    mockedPlanDecision.mockReturnValue(new Promise((done) => { resolve = done; }));
    const user = await startWith(workflow());
    await user.type(screen.getByLabelText(/Reviewer comment/), "Reviewed scope");
    const button = screen.getByRole("button", { name: "Approve plan and file scope" });
    await user.dblClick(button);
    expect(button).toBeDisabled(); expect(mockedPlanDecision).toHaveBeenCalledTimes(1);
    expect(mockedPlanDecision).toHaveBeenCalledWith("thread-017", { decision: "approve", comment: "Reviewed scope" }, planHash);
    await act(async () => resolve(testedWorkflow()));
  });

  it("guards duplicate final decisions", async () => {
    let resolve!: (value: WorkflowView) => void;
    mockedFinalDecision.mockReturnValue(new Promise((done) => { resolve = done; }));
    const user = await startWith(testedWorkflow());
    const button = screen.getByRole("button", { name: "Approve tested patch for export" });
    await user.dblClick(button);
    expect(button).toBeDisabled(); expect(mockedFinalDecision).toHaveBeenCalledTimes(1);
    await act(async () => resolve(testedWorkflow({ status: "final_rejected" })));
  });

  it("blocks final approval when passing evidence has a different patch identity", async () => {
    const base = testedWorkflow();
    const user = await startWith(testedWorkflow({ test: { ...base.test!, tested_patch_hash: "e".repeat(64) } }));
    const button = screen.getByRole("button", { name: "Approve tested patch for export" });
    expect(button).toBeDisabled(); await user.click(button);
    expect(mockedFinalDecision).not.toHaveBeenCalled();
    expect(screen.getByText("Evidence mismatch")).toBeVisible();
  });

  it("requires read-only recovery after a stale approval and never retries the POST", async () => {
    const { WorkflowApiError } = await import("./api/workflows");
    mockedPlanDecision.mockRejectedValue(new WorkflowApiError("private diagnostic", "stale_plan_hash", 409));
    mockedFetch.mockResolvedValue(workflow());
    const user = await startWith(workflow());
    await user.click(screen.getByRole("button", { name: "Approve plan and file scope" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("displayed plan hash is stale");
    expect(screen.queryByText("private diagnostic")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve plan and file scope" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Refresh state" }));
    expect(mockedFetch).toHaveBeenCalledTimes(1); expect(mockedPlanDecision).toHaveBeenCalledTimes(1);
    expect(screen.getByRole("button", { name: "Approve plan and file scope" })).toBeEnabled();
  });

  it("retains the thread after an ambiguous start and recovers through GET", async () => {
    const { WorkflowApiError } = await import("./api/workflows");
    mockedCreate.mockRejectedValueOnce(new WorkflowApiError("network", "network_error", 0));
    mockedFetch.mockResolvedValue(workflow());
    const user = userEvent.setup(); render(<App />);
    await user.type(screen.getByLabelText("Repository path"), "repo"); await user.type(screen.getByLabelText("Issue"), "issue");
    await user.click(screen.getByRole("button", { name: "Analyze repository" }));
    expect(window.location.search).toContain("thread=");
    expect(screen.getByRole("button", { name: "Analyze repository" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Refresh state" }));
    expect(await screen.findByRole("heading", { name: "Plan review" })).toBeVisible();
    expect(mockedCreate).toHaveBeenCalledTimes(1); expect(mockedFetch).toHaveBeenCalledTimes(1);
  });
});
