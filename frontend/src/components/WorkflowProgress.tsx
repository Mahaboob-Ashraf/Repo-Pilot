import type { WorkflowStatus, WorkflowView } from "../api/workflows";

type StageState = "complete" | "current" | "pending" | "failed" | "skipped";

const stages = [
  ["evidence", "Evidence"],
  ["plan", "Plan"],
  ["approval", "Approval #1"],
  ["patch", "Patch"],
  ["tests", "Tests"],
  ["critic", "Critic / Retry"],
  ["final", "Final Approval"],
  ["export", "Export"],
] as const;

const terminalStatuses = new Set<WorkflowStatus>([
  "planner_failed",
  "patch_failed",
  "test_infrastructure_failed",
  "critic_failed",
  "repair_failed",
  "rejected",
  "final_rejected",
  "export_failed",
  "completed",
]);

export function deriveStageStates(workflow: WorkflowView): Record<string, StageState> {
  const state: Record<string, StageState> = Object.fromEntries(
    stages.map(([key]) => [key, "pending"]),
  );
  const status = workflow.status;
  const hasPlan = workflow.plan !== null;
  const hasPatch = workflow.patch !== null;
  const hasTest = workflow.test !== null;
  const usedRetry = workflow.critic !== null || workflow.patch?.attempt_number === 2;

  state.evidence = status === "planning" ? "current" : "complete";
  if (status === "planner_failed") {
    state.evidence = workflow.evidence.length ? "complete" : "failed";
    state.plan = "failed";
  } else if (!hasPlan) {
    state.plan = "current";
  } else {
    state.plan = "complete";
  }

  if (status === "awaiting_approval") state.approval = "current";
  else if (status === "rejected") state.approval = "complete";
  else if (workflow.approved_file_scope) state.approval = "complete";

  if (status === "patch_failed") state.patch = "failed";
  else if (hasPatch) state.patch = "complete";
  else if (["approval_recorded", "approved_for_patch"].includes(status)) {
    state.patch = "current";
  }

  if (status === "test_infrastructure_failed") state.tests = "failed";
  else if (hasTest) state.tests = "complete";
  else if (status === "patch_ready") state.tests = "current";

  if (status === "critic_failed" || status === "repair_failed") {
    state.critic = "failed";
  } else if (usedRetry) {
    state.critic = "complete";
  } else if (
    hasTest &&
    ["awaiting_final_approval", "final_approval_recorded", "final_approved", "final_rejected", "completed", "export_failed"].includes(status)
  ) {
    state.critic = "skipped";
  } else if (status === "tests_failed") {
    state.critic = "current";
  }

  if (status === "awaiting_final_approval") state.final = "current";
  else if (status === "final_rejected") state.final = "failed";
  else if (["final_approval_recorded", "final_approved", "completed", "export_failed"].includes(status)) {
    state.final = "complete";
  }

  if (status === "completed") state.export = "complete";
  else if (status === "export_failed") state.export = "failed";
  else if (status === "final_approved" || status === "final_approval_recorded") {
    state.export = "current";
  }

  if (terminalStatuses.has(status)) {
    let seenTerminal = false;
    for (const [key] of stages) {
      if (state[key] === "failed") seenTerminal = true;
      if (seenTerminal && state[key] === "pending") state[key] = "skipped";
    }
    if (status === "rejected") {
      for (const key of ["patch", "tests", "critic", "final", "export"]) state[key] = "skipped";
    }
    if (status === "final_rejected") state.export = "skipped";
  }
  return state;
}

export function WorkflowProgress({ workflow }: { workflow: WorkflowView }) {
  const stageStates = deriveStageStates(workflow);
  return (
    <nav className="progress" aria-label="Workflow progress">
      <ol>
        {stages.map(([key, label], index) => (
          <li className={`progress-step is-${stageStates[key]}`} key={key}>
            <span className="step-index" aria-hidden="true">{index + 1}</span>
            <span className="step-copy">
              <strong>{label}</strong>
              <small>{stageStates[key]}</small>
            </span>
          </li>
        ))}
      </ol>
    </nav>
  );
}
