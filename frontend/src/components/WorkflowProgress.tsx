import type { WorkflowView } from "../api/workflows";
export const stages = [
  ["repository", "Repository"], ["retrieval", "Retrieval"], ["plan", "Plan review"],
  ["patch", "Patch"], ["tests", "Tests"], ["final", "Final approval"], ["export", "Export"],
] as const;
export type Stage = typeof stages[number][0];
type StageState = "complete" | "current" | "pending" | "failed" | "rejected" | "skipped";
export function activeStage(workflow: WorkflowView | null): Stage {
  if (!workflow) return "repository";
  const status = workflow.status;
  if (["completed", "export_failed", "final_approved", "final_approval_recorded"].includes(status)) return "export";
  if (["awaiting_final_approval", "final_rejected"].includes(status)) return "final";
  if (["patch_ready", "tests_passed", "tests_failed", "test_infrastructure_failed", "critic_complete", "critic_failed", "repair_failed"].includes(status)) return "tests";
  if (["approval_recorded", "approved_for_patch", "patch_failed"].includes(status)) return "patch";
  if (status === "planning") return "retrieval";
  return "plan";
}
export function deriveStageStates(workflow: WorkflowView | null): Record<Stage, StageState> {
  const state: Record<Stage, StageState> = { repository: "current", retrieval: "pending", plan: "pending", patch: "pending", tests: "pending", final: "pending", export: "pending" };
  if (!workflow) return state;
  state.repository = "complete";
  if (workflow.evidence.length || workflow.plan) state.retrieval = "complete";
  if (workflow.approved_file_scope) state.plan = "complete";
  if (workflow.patch) state.patch = "complete";
  if (workflow.test) state.tests = workflow.test.status === "passed" ? "complete" : "failed";
  if (workflow.final_review?.decision?.decision === "approve" || workflow.export) state.final = "complete";
  const current = activeStage(workflow);
  state[current] = workflow.status === "completed" ? "complete"
    : ["rejected", "final_rejected"].includes(workflow.status) ? "rejected"
    : workflow.status.endsWith("failed") || workflow.status === "validation_failed" ? "failed" : "current";
  if (["failed", "rejected"].includes(state[current])) {
    let after = false;
    for (const [key] of stages) { if (after && state[key] === "pending") state[key] = "skipped"; if (key === current) after = true; }
  }
  return state;
}
export function canViewStage(stage: Stage, workflow: WorkflowView | null): boolean {
  if (stage === "repository") return true;
  if (!workflow) return false;
  if (stage === activeStage(workflow)) return true;
  return ({ retrieval: !!workflow.evidence.length, plan: !!workflow.plan, patch: !!workflow.patch,
    tests: !!workflow.test || !!workflow.critic, final: !!workflow.final_review, export: !!workflow.export })[stage];
}
export function WorkflowProgress({ workflow, viewed, onView }: { workflow: WorkflowView | null; viewed: Stage; onView: (stage: Stage) => void; }) {
  const states = deriveStageStates(workflow);
  return <>
    <nav className="progress" aria-label="Workflow stages"><ol>
      {stages.map(([key, label], index) => <li key={key} className={`is-${states[key]}`}>
        <button type="button" className={`stage-button ${viewed === key ? "is-viewed" : ""}`} aria-current={viewed === key ? "page" : undefined}
          disabled={!canViewStage(key, workflow)} onClick={() => onView(key)}>
          <span className="step-index" aria-hidden="true">{states[key] === "complete" ? "✓" : states[key] === "failed" ? "!" : states[key] === "rejected" ? "×" : String(index + 1).padStart(2, "0")}</span>
          <span className="step-copy"><strong>{label}</strong>{(states[key] !== "pending" || workflow) && <small>{states[key] === "current" ? (workflow ? "Current checkpoint" : "Ready") : states[key]}</small>}</span>
        </button>
      </li>)}
    </ol></nav>
    <label className="mobile-stage-selector">Stage<select value={viewed} onChange={(event) => onView(event.target.value as Stage)}>
      {stages.map(([key, label]) => <option key={key} value={key} disabled={!canViewStage(key, workflow)}>{label} · {states[key]}</option>)}
    </select></label>
  </>;
}
