import { useState } from "react";
import { citationLabel } from "./ContextInspector";
import { DiffViewer } from "./DiffViewer";

import type {
  EvidenceItem,
  TestResultView,
  WorkflowView,
} from "../api/workflows";

export function EvidencePanel({ workflow, selectedId, onSelect }: { workflow: WorkflowView; selectedId: string | null; onSelect: (item: EvidenceItem) => void }) {
  const fileCount = new Set(workflow.evidence.map((item) => item.path)).size;
  return (
    <section className="review-section evidence-section" aria-labelledby="evidence-title">
      <div className="section-heading">
        <div>
          <p className="section-kicker">ContextPack provenance</p>
          <h2 id="evidence-title">Evidence</h2>
          <p className="section-intro">Retrieved source context supporting the proposed repair.</p>
        </div>
        <span className={`status-pill ${workflow.retrieval.degraded ? "warning" : "neutral"}`}>
          {workflow.retrieval.degraded ? "Lexical-only degraded" : workflow.retrieval.mode || "Pending"}
        </span>
      </div>
      <dl className="stage-summary" aria-label="Retrieval summary">
        <div><dt>Chunks</dt><dd>{workflow.retrieval.evidence_count}</dd></div>
        <div><dt>Files</dt><dd>{fileCount}</dd></div>
        <div><dt>Context</dt><dd>{workflow.retrieval.context_status || "Unavailable"}</dd></div>
      </dl>
      {workflow.retrieval.degradation_reason && (
        <p className="inline-note">{workflow.retrieval.degradation_reason}</p>
      )}
      {workflow.evidence.length === 0 ? (
        <p className="empty-state">No repository evidence is available.</p>
      ) : (
        <div className="evidence-list">
          {workflow.evidence.map((item) => <EvidenceItemView item={item} selected={item.chunk_id === selectedId} onSelect={onSelect} key={item.chunk_id} />)}
        </div>
      )}
    </section>
  );
}

function EvidenceItemView({ item, selected, onSelect }: { item: EvidenceItem; selected: boolean; onSelect: (item: EvidenceItem) => void }) {
  return (
    <div className={`evidence-item ${selected ? "is-selected" : ""}`}>
      <button className="evidence-button" type="button" aria-pressed={selected} onClick={() => onSelect(item)}>
        <span className="evidence-main">
          <span className="evidence-file"><code>{citationLabel(item)}</code><span aria-hidden="true">↗</span></span>
          <small>{item.symbol ? <code>{item.symbol}</code> : "No symbol"}<span aria-hidden="true"> · </span>{item.chunk_type}</small>
        </span>
        <span className="origin-tag">
          {item.origin === "retrieved" ? `Retrieved${item.retrieval_rank ? ` #${item.retrieval_rank}` : ""}` : "Structural expansion"}
        </span>
      </button>
      <p className="metadata-line evidence-id"><span>CHUNK</span><code>{item.chunk_id}</code></p>
      {item.structural_causes.length > 0 && (
        <p className="metadata-line">Expansion: {item.structural_causes.join(", ")}</p>
      )}
    </div>
  );
}

export function PlanPanel({
  workflow,
  pending,
  onDecision,
  onSelect,
}: {
  workflow: WorkflowView;
  pending: boolean;
  onDecision: (decision: "approve" | "reject", comment: string) => void;
  onSelect: (item: EvidenceItem) => void;
}) {
  const [comment, setComment] = useState("");
  if (!workflow.plan) return null;
  const scope = workflow.approved_file_scope || workflow.plan.proposed_files;
  return (
    <section className={`review-section plan-section ${workflow.status === "awaiting_approval" ? "decision-section" : ""}`} aria-labelledby="plan-title">
      <div className="section-heading">
        <div><p className="section-kicker">Evidence-grounded proposal</p><h2 id="plan-title">Repair plan</h2><p className="section-intro">Review the diagnosis, proposed edits, and exact file boundary before approving.</p></div>
        <span className="status-pill neutral">{workflow.plan.steps.length} steps</span>
      </div>
      <div className="diagnosis-block"><p className="content-label">Diagnosis</p><p className="plan-summary">{workflow.plan.summary}</p><p>{workflow.plan.diagnosis}</p></div>
      <div className="plan-block-heading"><div><p className="content-label">Proposed changes</p><h3>Ordered repair steps</h3></div><span>{workflow.plan.steps.length.toString().padStart(2, "0")}</span></div>
      <ol className="plan-steps graphite-steps">
        {workflow.plan.steps.map((step) => (
          <li key={step.order}>
            <strong>{step.description}</strong>
            <span className="step-files">Files <code>{step.affected_files.join(", ")}</code></span>
            <div className="citations">{step.evidence_chunk_ids.map((id) => <Citation key={id} id={id} workflow={workflow} onSelect={onSelect} />)}</div>
          </li>
        ))}
      </ol>
      <div className="scope-box scope-surface">
        <div><p className="content-label">Decision boundary</p><h3>{workflow.approved_file_scope ? "Approved file scope" : "Proposed file scope"}</h3><p>RepoPilot will be authorized to modify ONLY:</p></div>
        <ul>{scope.map((file) => <li key={file}><span aria-hidden="true">◇</span><code>{file}</code></li>)}</ul>
      </div>
      {workflow.plan.suggested_tests.length > 0 && <div className="suggested-tests"><p className="content-label">Suggested verification</p><h3>Tests</h3><ul className="file-list">{workflow.plan.suggested_tests.map((test) => <li key={test}><code>{test}</code></li>)}</ul></div>}
      <HashDisplay label="Plan hash" value={workflow.plan_hash || "Unavailable"} />
      {workflow.status === "awaiting_approval" && (
        <div className="decision-controls">
          <div className="decision-heading"><div><p className="checkpoint-label">Checkpoint 1 of 2</p><strong>Approve the plan and exact file scope</strong><span>No patch has been generated yet.</span></div><span className="checkpoint-index" aria-hidden="true">01 / 02</span></div>
          <label htmlFor="plan-comment">Reviewer comment <span>(optional)</span></label>
          <textarea id="plan-comment" rows={2} maxLength={4000} value={comment} disabled={pending} placeholder="Add review context for this decision…" onChange={(event) => setComment(event.target.value)} />
          <div className="button-row decision-actions">
            <button className="secondary danger" type="button" disabled={pending} onClick={() => onDecision("reject", comment)}>Reject plan</button>
            <button type="button" disabled={pending || !workflow.plan_hash} onClick={() => onDecision("approve", comment)}>Approve plan and file scope</button>
          </div>
        </div>
      )}
    </section>
  );
}

export function DiffPanel({ workflow, title = "Patch diff" }: { workflow: WorkflowView; title?: string }) {
  if (!workflow.patch) return null;
  return (
    <section className="review-section diff-section" aria-labelledby="diff-title">
      <div className="section-heading">
        <div><p className="section-kicker">Exact patch source of truth</p><h2 id="diff-title">{title}</h2><p className="section-intro">Review the canonical unified diff produced inside the approved file scope.</p></div>
        <span className="status-pill neutral">Attempt {workflow.patch.attempt_number}</span>
      </div>
      <div className="patch-metadata"><div className="changed-files"><span>Changed files</span><ul>{workflow.patch.changed_files.map((file) => <li key={file}><code>{file}</code></li>)}</ul></div><HashDisplay label="Patch hash" value={workflow.patch.patch_hash} /></div>
      <DiffViewer raw={workflow.patch.canonical_unified_diff} />
    </section>
  );
}

export function TestPanel({ test, attempt }: { test: TestResultView | null; attempt?: number }) {
  if (!test) return null;
  const label = testStatusLabel(test.status);
  return (
    <section className="review-section tests-section" aria-labelledby="tests-title">
      <div className="section-heading">
        <div><p className="section-kicker">Patch-bound Docker evidence</p><h2 id="tests-title">Docker tests</h2><p className="section-intro">Deterministic execution evidence for the exact candidate patch.</p></div>
        <span className={`status-pill test-${test.status}`}>{label}</span>
      </div>
      <div className={`test-summary test-${test.status}`}><div className="test-state-mark" aria-hidden="true">{test.status === "passed" ? "✓" : "!"}</div><div><span>Result</span><strong>{label}</strong></div><div><span>Duration</span><strong>{test.duration_ms} ms</strong></div><div><span>Exit code</span><strong>{test.exit_code ?? "—"}</strong></div>{attempt && <div><span>Attempt</span><strong>{attempt} of 2</strong></div>}</div>
      <dl className="fact-grid test-facts">
        <div><dt>Mode</dt><dd>{test.mode}</dd></div>
        <div><dt>Docker image</dt><dd><code>{test.image_reference}</code></dd></div>
        <div><dt>Image identity</dt><dd><code>{test.image_id || "Unavailable"}</code></dd></div>
        <div><dt>Tested patch</dt><dd><code>{test.tested_patch_hash}</code></dd></div>
      </dl>
      <p className="selector-line"><span>Selectors</span><code>{test.selectors.length ? test.selectors.join(", ") : "Full configured test suite"}</code></p>
      {test.failure_message && <div className="inline-note"><strong>{test.failure_classification || label}</strong><p>{test.failure_message}</p></div>}
      <TestConsole stdout={test.stdout} stderr={test.stderr} />
      {test.output_truncated && <p className="truncation-note">Output was bounded and truncated by RepoPilot.</p>}
    </section>
  );
}

function TestConsole({ stdout, stderr }: { stdout: string; stderr: string }) {
  const [channel, setChannel] = useState<"stdout" | "stderr">("stdout");
  const [wrap, setWrap] = useState(false);
  return <div className="test-console"><div className="console-toolbar"><div className="console-title"><span className="console-dots" aria-hidden="true"><i /><i /><i /></span><span>Test output</span></div><div className="console-controls"><div className="toolbar-actions" role="group" aria-label="Output channel">
    {(["stdout", "stderr"] as const).map((name) => <button type="button" className="text-button" key={name} aria-pressed={channel === name} onClick={() => setChannel(name)}>{name}</button>)}
  </div><button type="button" className="text-button" aria-pressed={wrap} onClick={() => setWrap(!wrap)}>Wrap</button></div></div>
    <pre tabIndex={0} className={wrap ? "wrap-code" : ""} aria-label={`${channel} output`}>{(channel === "stdout" ? stdout : stderr) || "(empty)"}</pre>
  </div>;
}

function testStatusLabel(status: string): string {
  const labels: Record<string, string> = {
    passed: "Passed",
      failed: "Test failure",
    infrastructure_failed: "Infrastructure failure",
    timed_out: "Timed out",
    no_tests_collected: "No tests collected",
    pytest_error: "Pytest error",
  };
  return labels[status] || status;
}

export function CriticPanel({ workflow, onSelect }: { workflow: WorkflowView; onSelect: (item: EvidenceItem) => void }) {
  if (!workflow.critic) return null;
  return (
    <section className="review-section critic-section" aria-labelledby="critic-title">
      <div className="section-heading"><div><p className="section-kicker">Bounded failure analysis</p><h2 id="critic-title">Critic review</h2><p className="section-intro">Advisory guidance after a deterministic test failure.</p></div><span className="status-pill warning">Two attempts maximum</span></div>
      <div className="critic-advisory"><span aria-hidden="true">i</span><p><strong>Advisory only</strong>Deterministic validators remain authoritative. RepoPilot permits at most one repair retry.</p></div>
      <div className="critic-grid"><div><p className="content-label">Assessment</p><h3>Summary</h3><p>{workflow.critic.summary}</p></div><div><p className="content-label">Cause</p><h3>Failure diagnosis</h3><p>{workflow.critic.failure_diagnosis}</p></div></div>
      {workflow.critic.evidence_chunk_ids.length > 0 && <div className="critic-evidence"><p className="content-label">Supporting evidence</p><div className="citations">{workflow.critic.evidence_chunk_ids.map((id) => <Citation key={id} id={id} workflow={workflow} onSelect={onSelect} />)}</div></div>}
      <div className="retry-recommendation"><div><p className="content-label">Recommendation</p><h3>{workflow.critic.retry_recommended ? "Retry within approved scope" : "Stop after failed attempt"}</h3></div><span className={`status-pill ${workflow.critic.retry_recommended ? "warning" : "neutral"}`}>{workflow.critic.retry_recommended ? "Retry authorized" : "No retry"}</span></div>
      {workflow.critic.retry_instructions.length > 0 && <ul className="retry-instructions">{workflow.critic.retry_instructions.map((item, index) => <li key={`${item.description}-${index}`}><span>{String(index + 1).padStart(2, "0")}</span><div>{item.description}<code>{item.affected_files.join(", ")}</code></div></li>)}</ul>}
      {workflow.attempts.length > 0 && <div className="attempt-history"><p className="content-label">Attempt history</p><ol>{workflow.attempts.map((attempt) => <li key={attempt.attempt_number}><span className={`attempt-marker test-${attempt.test_status || "pending"}`} aria-hidden="true" /><div><strong>Attempt {attempt.attempt_number} of 2</strong><small>Patch <code>{shortHash(attempt.patch_hash)}</code></small></div><span className={`status-pill test-${attempt.test_status || "pending"}`}>{attempt.test_status?.replaceAll("_", " ") || "Not run"}</span></li>)}</ol></div>}
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
  if (!workflow.final_review || !workflow.patch || !workflow.test) return <section className="review-section final-review"><h2>Final review</h2><p className="empty-state">Exact passing patch evidence is not available for approval.</p></section>;
  const matched = isFinalEvidenceMatched(workflow);
  const awaiting = workflow.status === "awaiting_final_approval" && workflow.final_review.awaiting_decision;
  return (
    <section className="review-section final-review" aria-labelledby="final-title">
      <div className="section-heading"><div><p className="section-kicker">Tested candidate</p><h2 id="final-title">Final review</h2><p className="section-intro">Approve the exact patch whose identity is bound to passing Docker evidence.</p></div><span className={`status-pill ${matched ? "success" : "danger"}`}>{matched ? "Tests passed · identity matched" : "Evidence mismatch"}</span></div>
      <div className="final-proof"><div className={`proof-mark ${matched ? "success" : "danger"}`} aria-hidden="true">{matched ? "✓" : "!"}</div><div><span>Verification</span><strong>{matched ? "Tested patch identity confirmed" : "Patch and test identities differ"}</strong><p>Attempt {workflow.final_review.attempt_number} of 2 · {workflow.final_review.final_changed_files.length} changed file(s)</p></div></div>
      <div className="final-summary-grid"><div><p className="content-label">Approved plan</p><p>{workflow.final_review.plan_summary}</p></div><div className="scope-box"><p className="content-label">Approved file scope</p><ul>{workflow.final_review.approved_file_scope.map((file) => <li key={file}><code>{file}</code></li>)}</ul></div></div>
      <div className="identity-pair"><HashDisplay label="Final patch hash" value={workflow.final_review.final_patch_hash} /><HashDisplay label="Tested patch hash" value={workflow.final_review.tested_patch_hash} /></div>
      <div className="changed-files final-files"><span>Changed files</span><ul>{workflow.final_review.final_changed_files.map((file) => <li key={file}><code>{file}</code></li>)}</ul></div>
      <p className="test-proof"><span>Docker result</span><strong>{testStatusLabel(workflow.test.status)}</strong><span>{workflow.test.duration_ms} ms</span><span>exit {workflow.test.exit_code ?? "unavailable"}</span></p>
      <div className="final-diff"><p className="content-label">Exact tested diff</p><DiffViewer raw={workflow.patch.canonical_unified_diff} /></div>
      <details className="test-evidence-details"><summary>Inspect Docker test evidence</summary><TestPanel test={workflow.test} attempt={workflow.final_review.attempt_number} /></details>
      {!matched && <p className="limit-callout" role="alert">Approval is unavailable: the displayed candidate and successful test evidence must match. Refresh authoritative state.</p>}
      {awaiting && <div className="decision-controls final-decision">
        <div className="decision-heading"><div><p className="checkpoint-label">Checkpoint 2 of 2</p><strong>Authorize tested patch export</strong><span>RepoPilot does not commit, merge, or open a PR.</span></div><span className="checkpoint-index" aria-hidden="true">02 / 02</span></div>
        <label htmlFor="final-comment">Reviewer comment <span>(optional)</span></label>
        <textarea id="final-comment" rows={2} maxLength={4000} value={comment} disabled={pending} onChange={(event) => setComment(event.target.value)} />
        <div className="button-row"><button className="secondary danger" type="button" disabled={pending} onClick={() => onDecision("reject", comment)}>Reject tested patch</button><button type="button" disabled={pending || !matched} onClick={() => onDecision("approve", comment)}>Approve tested patch for export</button></div>
      </div>}
    </section>
  );
}

export function CompletionPanel({ workflow }: { workflow: WorkflowView }) {
  const [copyStatus, setCopyStatus] = useState("");
  if (workflow.status !== "completed" || !workflow.export) return null;
  return (
    <section className="review-section completion" aria-labelledby="complete-title">
      <div className="completion-heading"><div className="completion-mark" aria-hidden="true">✓</div><div><p className="section-kicker">Workflow complete</p><h2 id="complete-title">Repair complete</h2><p>The approved patch is ready for human-controlled application.</p></div></div>
      <div className="artifact-receipt"><div className="receipt-header"><span>Exported artifact</span><strong><code>{workflow.export.filename}</code></strong></div><dl className="receipt-grid"><div><dt>Patch hash</dt><dd><code>{workflow.export.patch_hash}</code></dd></div><div><dt>Test result</dt><dd>{workflow.test?.status || "Unavailable"}</dd></div><div><dt>Attempt</dt><dd>{workflow.patch?.attempt_number || "Unavailable"} of 2</dd></div><div><dt>Changed files</dt><dd>{workflow.export.changed_files.length}</dd></div><div><dt>Final approval</dt><dd>Approved for export</dd></div></dl><div className="receipt-files">{workflow.export.changed_files.map((file) => <code key={file}>{file}</code>)}</div></div>
      <div className="export-identities"><HashDisplay label="Artifact ID" value={workflow.export.artifact_id} /><HashDisplay label="Test run" value={workflow.export.test_run_id} /></div>
      <p className="authority-receipt"><span aria-hidden="true">◇</span>RepoPilot did not apply, commit, push, merge, or create a pull request.</p>
      <div className="completion-actions"><button type="button" className="secondary" onClick={async () => {
        try { await navigator.clipboard.writeText(JSON.stringify(workflow.export, null, 2)); setCopyStatus("Artifact details copied."); }
        catch { setCopyStatus("Clipboard unavailable. Select and copy the artifact details above."); }
      }}>Copy artifact details</button><p role="status">{copyStatus}</p></div>
    </section>
  );
}

const failureContent: Record<string, { title: string; message: string; didNot: string }> = {
  validation_failed: { title: "Decision not accepted", message: "Refresh and review the authoritative workflow before deciding again.", didNot: "The decision was not automatically resent." },
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
  const rejected = workflow.status.includes("rejected");
  return <section className={`review-section failure ${rejected ? "rejection" : ""}`} role="alert"><div className="failure-mark" aria-hidden="true">{rejected ? "×" : "!"}</div><div className="failure-copy"><p className="section-kicker">Workflow outcome</p><h2>{content.title}</h2><p>{content.message}</p><p className="failure-boundary"><strong>What did not happen</strong><span>{content.didNot}</span></p>{workflow.error?.classification && <p className="metadata-line">Classification <code>{workflow.error.classification}</code></p>}</div></section>;
}

export function HashDisplay({ label, value }: { label: string; value: string }) {
  return <div className="hash-row"><span>{label}</span><code>{value}</code></div>;
}

function shortHash(hash: string): string { return `${hash.slice(0, 10)}…`; }

export function isFinalEvidenceMatched(workflow: WorkflowView): boolean {
  const { final_review: final, patch, test } = workflow;
  return !!final && !!patch && !!test && test.status === "passed"
    && /^[0-9a-f]{64}$/.test(patch.patch_hash)
    && patch.patch_hash === final.final_patch_hash
    && patch.patch_hash === final.tested_patch_hash
    && patch.patch_hash === test.tested_patch_hash
    && patch.attempt_number === final.attempt_number;
}

function Citation({ id, workflow, onSelect }: { id: string; workflow: WorkflowView; onSelect: (item: EvidenceItem) => void }) {
  const item = workflow.evidence.find((evidence) => evidence.chunk_id === id);
  return item ? <button className="citation" type="button" title={id} onClick={() => onSelect(item)}><code>{citationLabel(item)}</code><span aria-hidden="true">↗</span></button>
    : <span className="missing-citation"><code>{id}</code> · source unavailable</span>;
}
