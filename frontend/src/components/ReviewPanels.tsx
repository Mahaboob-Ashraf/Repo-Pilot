import { useState } from "react";

import type {
  EvidenceItem,
  TestResultView,
  WorkflowView,
} from "../api/workflows";

export function EvidencePanel({ workflow }: { workflow: WorkflowView }) {
  return (
    <section className="review-section" aria-labelledby="evidence-title">
      <div className="section-heading">
        <div>
          <p className="section-kicker">ContextPack provenance</p>
          <h2 id="evidence-title">Repository Evidence</h2>
        </div>
        <span className={`status-pill ${workflow.retrieval.degraded ? "warning" : "neutral"}`}>
          {workflow.retrieval.degraded ? "Lexical-only degraded" : workflow.retrieval.mode || "Pending"}
        </span>
      </div>
      {workflow.retrieval.degradation_reason && (
        <p className="inline-note">{workflow.retrieval.degradation_reason}</p>
      )}
      {workflow.evidence.length === 0 ? (
        <p className="empty-state">No repository evidence is available.</p>
      ) : (
        <div className="evidence-list">
          {workflow.evidence.map((item) => <EvidenceItemView item={item} key={item.chunk_id} />)}
        </div>
      )}
    </section>
  );
}

function EvidenceItemView({ item }: { item: EvidenceItem }) {
  return (
    <details className="evidence-item">
      <summary>
        <span>
          <strong>{item.path}</strong>
          <small>{item.symbol} · {item.chunk_type} · lines {item.start_line}–{item.end_line}</small>
        </span>
        <span className="origin-tag">
          {item.origin === "retrieved" ? `Retrieved${item.retrieval_rank ? ` #${item.retrieval_rank}` : ""}` : "Structural expansion"}
        </span>
      </summary>
      {item.structural_causes.length > 0 && (
        <p className="metadata-line">Expansion: {item.structural_causes.join(", ")}</p>
      )}
      {item.source_text !== null && <pre className="source-block">{item.source_text}</pre>}
    </details>
  );
}

export function PlanPanel({
  workflow,
  pending,
  onDecision,
}: {
  workflow: WorkflowView;
  pending: boolean;
  onDecision: (decision: "approve" | "reject", comment: string) => void;
}) {
  const [comment, setComment] = useState("");
  if (!workflow.plan) return null;
  const scope = workflow.approved_file_scope || workflow.plan.proposed_files;
  return (
    <section className={`review-section ${workflow.status === "awaiting_approval" ? "decision-section" : ""}`} aria-labelledby="plan-title">
      <div className="section-heading">
        <div><p className="section-kicker">Evidence-grounded proposal</p><h2 id="plan-title">Repair Plan</h2></div>
        <span className="status-pill neutral">{workflow.plan.steps.length} steps</span>
      </div>
      <p className="plan-summary">{workflow.plan.summary}</p>
      <h3>Diagnosis</h3><p>{workflow.plan.diagnosis}</p>
      <h3>Ordered steps</h3>
      <ol className="plan-steps">
        {workflow.plan.steps.map((step) => (
          <li key={step.order}>
            <strong>{step.description}</strong>
            <span>Files: {step.affected_files.join(", ")}</span>
            <span>Evidence: {step.evidence_chunk_ids.join(", ")}</span>
          </li>
        ))}
      </ol>
      <div className="scope-box">
        <strong>RepoPilot will be authorized to modify ONLY:</strong>
        <ul>{scope.map((file) => <li key={file}><code>{file}</code></li>)}</ul>
      </div>
      <HashDisplay label="Plan hash" value={workflow.plan_hash || "Unavailable"} />
      {workflow.status === "awaiting_approval" && (
        <div className="decision-controls">
          <label htmlFor="plan-comment">Reviewer comment <span>(optional)</span></label>
          <textarea id="plan-comment" rows={3} value={comment} disabled={pending} onChange={(event) => setComment(event.target.value)} />
          <div className="button-row">
            <button className="secondary danger" type="button" disabled={pending} onClick={() => onDecision("reject", comment)}>Reject plan</button>
            <button type="button" disabled={pending} onClick={() => onDecision("approve", comment)}>Approve plan</button>
          </div>
        </div>
      )}
    </section>
  );
}

export function DiffPanel({ workflow, title = "Canonical Unified Diff" }: { workflow: WorkflowView; title?: string }) {
  if (!workflow.patch) return null;
  return (
    <section className="review-section" aria-labelledby="diff-title">
      <div className="section-heading">
        <div><p className="section-kicker">Exact patch source of truth</p><h2 id="diff-title">{title}</h2></div>
        <span className="status-pill neutral">Attempt {workflow.patch.attempt_number}</span>
      </div>
      <div className="changed-files"><strong>Changed files</strong><ul>{workflow.patch.changed_files.map((file) => <li key={file}><code>{file}</code></li>)}</ul></div>
      <HashDisplay label="Patch hash" value={workflow.patch.patch_hash} />
      <pre className="diff-block" aria-label="Canonical unified diff">{workflow.patch.canonical_unified_diff}</pre>
    </section>
  );
}

export function TestPanel({ test }: { test: TestResultView | null }) {
  if (!test) return null;
  const label = testStatusLabel(test.status);
  return (
    <section className="review-section" aria-labelledby="tests-title">
      <div className="section-heading">
        <div><p className="section-kicker">Patch-bound Docker evidence</p><h2 id="tests-title">Test Result</h2></div>
        <span className={`status-pill test-${test.status}`}>{label}</span>
      </div>
      <dl className="fact-grid">
        <div><dt>Mode</dt><dd>{test.mode}</dd></div>
        <div><dt>Duration</dt><dd>{test.duration_ms} ms</dd></div>
        <div><dt>Exit code</dt><dd>{test.exit_code ?? "Not available"}</dd></div>
        <div><dt>Docker image</dt><dd><code>{test.image_reference}</code></dd></div>
        <div><dt>Image identity</dt><dd><code>{test.image_id || "Unavailable"}</code></dd></div>
        <div><dt>Tested patch</dt><dd><code>{test.tested_patch_hash}</code></dd></div>
      </dl>
      {test.selectors.length > 0 && <p className="metadata-line">Selectors: {test.selectors.join(", ")}</p>}
      {test.failure_message && <div className="inline-note"><strong>{test.failure_classification || label}</strong><p>{test.failure_message}</p></div>}
      <LogOutput label="stdout" value={test.stdout} />
      <LogOutput label="stderr" value={test.stderr} />
      {test.output_truncated && <p className="truncation-note">Output was bounded and truncated by RepoPilot.</p>}
    </section>
  );
}

function LogOutput({ label, value }: { label: string; value: string }) {
  return <details className="log-output"><summary>{label}</summary><pre>{value || "(empty)"}</pre></details>;
}

function testStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    passed: "Passed",
    failed: "Failed",
    infrastructure_failed: "Infrastructure failure",
    timed_out: "Timed out",
    no_tests_collected: "No tests collected",
    pytest_error: "Pytest error",
  };
  return labels[status] || status;
}

export function CriticPanel({ workflow }: { workflow: WorkflowView }) {
  if (!workflow.critic) return null;
  return (
    <section className="review-section" aria-labelledby="critic-title">
      <div className="section-heading"><div><p className="section-kicker">Bounded failure analysis</p><h2 id="critic-title">Critic &amp; Retry</h2></div><span className="status-pill warning">One retry maximum</span></div>
      <p className="limit-callout">RepoPilot permits at most one repair retry.</p>
      <h3>Summary</h3><p>{workflow.critic.summary}</p>
      <h3>Failure diagnosis</h3><p>{workflow.critic.failure_diagnosis}</p>
      <h3>Retry recommendation</h3><p>{workflow.critic.retry_recommended ? "A single retry was authorized within the original file scope." : "No retry was recommended."}</p>
      {workflow.critic.retry_instructions.length > 0 && <ul>{workflow.critic.retry_instructions.map((item, index) => <li key={`${item.description}-${index}`}>{item.description} <span>({item.affected_files.join(", ")})</span></li>)}</ul>}
      {workflow.attempts.length > 0 && <div className="attempt-history"><h3>Attempt history</h3><ol>{workflow.attempts.map((attempt) => <li key={attempt.attempt_number}><strong>Attempt {attempt.attempt_number}</strong> — patch {shortHash(attempt.patch_hash)} — tests {attempt.test_status || "not run"}</li>)}</ol></div>}
    </section>
  );
}

export function FinalReviewPanel({
  workflow,
  pending,
  onDecision,
}: {
  workflow: WorkflowView;
  pending: boolean;
  onDecision: (decision: "approve" | "reject", comment: string) => void;
}) {
  const [comment, setComment] = useState("");
  if (workflow.status !== "awaiting_final_approval" || !workflow.final_review || !workflow.patch || !workflow.test) return null;
  return (
    <section className="review-section final-review" aria-labelledby="final-title">
      <div className="section-heading"><div><p className="section-kicker">Human checkpoint #2</p><h2 id="final-title">Final Patch Approval</h2></div><span className="status-pill success">Tests passed</span></div>
      <p className="authority-callout">Successful tests do not automatically authorize export.</p>
      <p><strong>Plan:</strong> {workflow.final_review.plan_summary}</p>
      <p><strong>Final candidate:</strong> attempt {workflow.final_review.attempt_number}; {workflow.final_review.final_changed_files.length} changed file(s).</p>
      <div className="scope-box"><strong>Approved file scope</strong><ul>{workflow.final_review.approved_file_scope.map((file) => <li key={file}><code>{file}</code></li>)}</ul></div>
      <HashDisplay label="Final patch hash" value={workflow.final_review.final_patch_hash} />
      <HashDisplay label="Tested patch hash" value={workflow.final_review.tested_patch_hash} />
      <pre className="diff-block" aria-label="Final canonical unified diff">{workflow.patch.canonical_unified_diff}</pre>
      <div className="decision-controls">
        <label htmlFor="final-comment">Reviewer comment <span>(optional)</span></label>
        <textarea id="final-comment" rows={3} value={comment} disabled={pending} onChange={(event) => setComment(event.target.value)} />
        <div className="button-row"><button className="secondary danger" type="button" disabled={pending} onClick={() => onDecision("reject", comment)}>Reject final patch</button><button type="button" disabled={pending} onClick={() => onDecision("approve", comment)}>Approve &amp; export patch</button></div>
      </div>
    </section>
  );
}

export function CompletionPanel({ workflow }: { workflow: WorkflowView }) {
  if (workflow.status !== "completed" || !workflow.export) return null;
  return (
    <section className="review-section completion" aria-labelledby="complete-title">
      <p className="section-kicker">Workflow complete</p><h2 id="complete-title">Patch exported</h2>
      <p>Patch exported for human-controlled application.</p>
      <dl className="fact-grid"><div><dt>Artifact</dt><dd><code>{workflow.export.filename}</code></dd></div><div><dt>Patch hash</dt><dd><code>{workflow.export.patch_hash}</code></dd></div><div><dt>Tests</dt><dd>{workflow.test?.status || "Unavailable"}</dd></div><div><dt>Changed files</dt><dd>{workflow.export.changed_files.join(", ")}</dd></div></dl>
      <p className="inline-note">RepoPilot did not apply, commit, push, merge, or create a pull request.</p>
    </section>
  );
}

const failureContent: Record<string, { title: string; message: string; didNot: string }> = {
  planner_failed: { title: "Planning failed", message: "RepoPilot could not produce a grounded RepairPlan.", didNot: "No plan was approved and the canonical repository was not modified." },
  patch_failed: { title: "Patch generation failed", message: "RepoPilot could not produce a valid patch within the approved scope.", didNot: "The canonical repository was not modified and no tests or export ran." },
  tests_failed: { title: "Tests failed", message: "The candidate did not satisfy the configured tests.", didNot: "A failing patch was not exported." },
  test_infrastructure_failed: { title: "Test infrastructure failed", message: "Docker or the bounded test environment could not complete the test run.", didNot: "This is not classified as a code-test failure; critic and export did not run." },
  critic_failed: { title: "Critic failed", message: "The bounded critic could not produce safe retry guidance.", didNot: "No ungrounded retry or export occurred." },
  repair_failed: { title: "Repair attempts exhausted", message: "The repair did not reach a passing candidate within two attempts.", didNot: "No third retry will occur and no patch was exported." },
  rejected: { title: "Plan rejected", message: "The reviewer rejected the proposed plan and scope.", didNot: "No patch was generated and the canonical repository was not modified." },
  final_rejected: { title: "Final patch rejected", message: "The reviewer rejected the tested candidate.", didNot: "The patch was not exported." },
  export_failed: { title: "Export failed", message: "The approved patch could not be exported safely.", didNot: "RepoPilot did not apply or commit the patch." },
};

export function FailurePanel({ workflow }: { workflow: WorkflowView }) {
  const content = failureContent[workflow.status];
  if (!content) return null;
  return <section className="review-section failure" role="alert"><p className="section-kicker">Bounded terminal state</p><h2>{content.title}</h2><p>{workflow.error?.message || content.message}</p><p><strong>What did not happen:</strong> {content.didNot}</p>{workflow.error?.classification && <p className="metadata-line">Classification: {workflow.error.classification}</p>}</section>;
}

export function HashDisplay({ label, value }: { label: string; value: string }) {
  return <div className="hash-row"><span>{label}</span><code>{value}</code></div>;
}

function shortHash(hash: string): string { return `${hash.slice(0, 10)}…`; }
