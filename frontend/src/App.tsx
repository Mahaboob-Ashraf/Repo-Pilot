import { FormEvent, useEffect, useRef, useState } from "react";
import { createWorkflow, fetchWorkflow, submitFinalDecision, submitPlanDecision, WorkflowApiError, type WorkflowView, type EvidenceItem } from "./api/workflows";
import { CompletionPanel, CriticPanel, DiffPanel, EvidencePanel, FailurePanel, FinalReviewPanel, PlanPanel, TestPanel, isFinalEvidenceMatched } from "./components/ReviewPanels";
import { WorkflowProgress, activeStage, stages, type Stage } from "./components/WorkflowProgress";
import { ContextInspector } from "./components/ContextInspector";
import { ThemeSelector } from "./components/ThemeSelector";
import "./App.css";

type PendingAction = "start" | "refresh" | "plan" | "final" | null;
function threadFromLocation(): string | null { return new URLSearchParams(window.location.search).get("thread"); }

function App() {
  const [repositoryPath, setRepositoryPath] = useState("");
  const [issue, setIssue] = useState("");
  const [workflow, setWorkflow] = useState<WorkflowView | null>(null);
  const [viewed, setViewed] = useState<Stage>("repository");
  const [selected, setSelected] = useState<EvidenceItem | null>(null);
  const [contextOpen, setContextOpen] = useState(false);
  const [pending, setPending] = useState<PendingAction>(threadFromLocation() ? "refresh" : null);
  const [error, setError] = useState<string | null>(null);
  const [fieldErrors, setFieldErrors] = useState<{ repository?: string; issue?: string }>({});
  const [needsRefresh, setNeedsRefresh] = useState(!!threadFromLocation());
  const requestLock = useRef(false);
  const surface = useRef<HTMLDivElement>(null);

  function acceptWorkflow(current: WorkflowView, follow = true) {
    setWorkflow(current);
    setSelected((previous) => current.evidence.find((item) => item.chunk_id === previous?.chunk_id) || null);
    if (follow) setViewed(activeStage(current));
    setError(null); setNeedsRefresh(false);
  }
  useEffect(() => {
    const threadId = threadFromLocation();
    if (!threadId) return;
    const controller = new AbortController();
    requestLock.current = true;
    fetchWorkflow(threadId, controller.signal).then((current) => acceptWorkflow(current))
      .catch((failure: unknown) => { if (!(failure instanceof DOMException && failure.name === "AbortError")) setError(messageFor(failure)); })
      .finally(() => { requestLock.current = false; setPending(null); });
    return () => controller.abort();
  }, []);

  function begin(action: PendingAction): boolean {
    if (requestLock.current) return false;
    requestLock.current = true; setPending(action); setError(null); return true;
  }
  function finish() { requestLock.current = false; setPending(null); }
  function viewStage(stage: Stage) { setViewed(stage); surface.current?.focus(); }
  function selectEvidence(item: EvidenceItem) { setSelected(item); setContextOpen(true); }
  function updateRepositoryPath(value: string) {
    setRepositoryPath(value);
    if (fieldErrors.repository) setFieldErrors((current) => ({ ...current, repository: undefined }));
  }
  function updateIssue(value: string) {
    setIssue(value);
    if (fieldErrors.issue) setFieldErrors((current) => ({ ...current, issue: undefined }));
  }

  async function handleStart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (requestLock.current || needsRefresh) return;
    const cleanPath = repositoryPath.trim(), cleanIssue = issue.trim();
    const errors = { repository: cleanPath ? undefined : "Repository path is required.", issue: cleanIssue ? undefined : "Issue is required." };
    setFieldErrors(errors);
    if (!cleanPath || !cleanIssue) {
      document.getElementById(!cleanPath ? "repository-path" : "issue")?.focus(); return;
    }
    setFieldErrors({});
    if (!begin("start")) return;
    const requestedThreadId = crypto.randomUUID();
    window.history.replaceState(null, "", `?thread=${encodeURIComponent(requestedThreadId)}`);
    try {
      acceptWorkflow(await createWorkflow({ repository_path: cleanPath, issue: cleanIssue, thread_id: requestedThreadId }));
    } catch (failure) {
      const fieldFailure = failure instanceof WorkflowApiError && ["invalid_repository", "invalid_issue"].includes(failure.code);
      setError(fieldFailure ? null : messageFor(failure));
      const ambiguous = !(failure instanceof WorkflowApiError) || failure.status === 0 || failure.status >= 500 || failure.code === "unreadable_response" || failure.code === "thread_conflict";
      setNeedsRefresh(ambiguous);
      if (!ambiguous) window.history.replaceState(null, "", window.location.pathname);
      if (failure instanceof WorkflowApiError && failure.code === "invalid_repository") setFieldErrors({ repository: messageFor(failure) });
      if (failure instanceof WorkflowApiError && failure.code === "invalid_issue") setFieldErrors({ issue: messageFor(failure) });
    } finally { finish(); }
  }
  async function refreshWorkflow() {
    const threadId = workflow?.thread_id || threadFromLocation();
    if (!threadId || !begin("refresh")) return;
    try { acceptWorkflow(await fetchWorkflow(threadId), !workflow); }
    catch (failure) { setError(messageFor(failure)); }
    finally { finish(); }
  }
  async function handlePlanDecision(decision: "approve" | "reject", comment: string) {
    if (!workflow?.plan_hash || workflow.status !== "awaiting_approval" || needsRefresh || !begin("plan")) return;
    const displayedHash = workflow.plan_hash;
    try { acceptWorkflow(await submitPlanDecision(workflow.thread_id, { decision, comment: comment.trim() || undefined }, displayedHash)); }
    catch (failure) { setError(messageFor(failure)); setNeedsRefresh(true); }
    finally { finish(); }
  }
  async function handleFinalDecision(decision: "approve" | "reject", comment: string) {
    if (!workflow?.final_review || workflow.status !== "awaiting_final_approval" || needsRefresh || (decision === "approve" && !isFinalEvidenceMatched(workflow)) || !begin("final")) return;
    const displayedHash = workflow.final_review.final_patch_hash;
    try { acceptWorkflow(await submitFinalDecision(workflow.thread_id, { decision, comment: comment.trim() || undefined }, displayedHash)); }
    catch (failure) { setError(messageFor(failure)); setNeedsRefresh(true); }
    finally { finish(); }
  }
  function startAnother() {
    if (requestLock.current) return;
    setWorkflow(null); setRepositoryPath(""); setIssue(""); setError(null); setFieldErrors({}); setSelected(null); setContextOpen(false); setViewed("repository"); setNeedsRefresh(false);
    window.history.replaceState(null, "", window.location.pathname);
  }
  const current = activeStage(workflow);
  const title = stages.find(([key]) => key === viewed)![1];
  const disabled = pending !== null || needsRefresh;
  return <div className="app-shell">
    <a className="skip-link" href="#review-surface">Skip to review</a>
    <header className="topbar">
      <div className="topbar-path">
        <a className="brand" href={window.location.pathname} aria-label="RepoPilot home">
          <span className="brand-mark" aria-hidden="true"><svg viewBox="0 0 28 28"><path d="M8 19V9h6.2a4 4 0 0 1 0 8H8m6.2 0 4.8 4" /></svg></span>
          <strong>RepoPilot</strong>
        </a>
        <span className="breadcrumb-divider" aria-hidden="true">/</span>
        <span className="workspace-identity">{workflow?.repository.name || "New repair"}</span>
      </div>
      <div className="topbar-actions"><span className="control-plane-label"><span aria-hidden="true" /> Review control plane</span><ThemeSelector /></div>
    </header>
    <div className={`workspace-layout ${workflow ? "" : "initial-layout"}`}>
      <aside className={`workflow-sidebar ${workflow ? "" : "initial-rail"}`}>
        <div className="rail-heading"><p className="section-kicker">Workflow</p><span className="rail-caption">Bounded repair sequence</span></div>
        <WorkflowProgress workflow={workflow} viewed={viewed} onView={viewStage} />
        <div className="sidebar-footer"><div className="rail-boundary"><span aria-hidden="true" /><div><strong>2 checkpoints</strong><small>Patch export only</small></div></div>
          {(workflow || needsRefresh) && <div className="sidebar-actions"><button className="secondary" type="button" disabled={pending !== null} onClick={refreshWorkflow}>Refresh state</button><button className="text-button" type="button" disabled={pending !== null} onClick={startAnother}>Start another repair</button></div>}
        </div>
      </aside>
      <main className={`review-workspace ${workflow ? "" : "initial-workspace"}`} id="review-surface" tabIndex={-1} ref={surface}>
        <div className="workspace-toolbar"><span>{workflow ? `${title} / Review surface` : "Workspace / New repair"}</span><button className="text-button context-toggle" type="button" onClick={() => setContextOpen(true)}>Open context</button></div>
        {workflow && pending && <LoadingState action={pending} />}
        {error && <div className="request-error request-error-compact" role="alert"><strong>Request not completed</strong><p>{error}</p>{needsRefresh && <p>The request was not automatically resent. Refresh authoritative state before deciding again. The workflow identity is retained in the URL.</p>}</div>}
        {!workflow ? <StartScreen repositoryPath={repositoryPath} issue={issue} pending={pending !== null} blocked={needsRefresh} errors={fieldErrors} onRepositoryChange={updateRepositoryPath} onIssueChange={updateIssue} onSubmit={handleStart} />
          : <>
            <header className="review-header"><div><p className="section-kicker">{workflow.repository.name}</p><h1>{title}</h1></div><span className={`workflow-status ${workflow.status.includes("failed") ? "danger" : workflow.status.includes("rejected") ? "warning" : workflow.status === "completed" ? "success" : ""}`}>{workflow.status.replaceAll("_", " ")}</span></header>
            <p className="sr-only" role="status">Workflow status: {workflow.status.replaceAll("_", " ")}</p>
            {workflow.retrieval.degraded && viewed !== "retrieval" && <p className="limit-callout">Lexical-only retrieval: dense evidence was unavailable. Review the available citations before deciding.</p>}
            {viewed !== current && <div className="viewing-note">Viewing {title.toLowerCase()}. Current checkpoint: {stages.find(([key]) => key === current)![1]}. <button className="text-button" type="button" onClick={() => viewStage(current)}>View current checkpoint</button></div>}
            {viewed === current && <FailurePanel workflow={workflow} />}
            <div className="stage-surface" key={`${workflow.thread_id}-${viewed}`}>
              {viewed === "repository" && <section className="review-section"><h2>Repository &amp; issue</h2><details><summary>Repository path</summary><p><code>{workflow.repository.path}</code></p></details><h3>Issue</h3><p className="issue-text">{workflow.issue}</p><p className="muted">Canonical source is preserved. Patches are prepared in an isolated workspace.</p></section>}
              {viewed !== "repository" && <details className="issue-disclosure"><summary>Issue under review</summary><p className="issue-text">{workflow.issue}</p></details>}
              {viewed === "retrieval" && <EvidencePanel workflow={workflow} selectedId={selected?.chunk_id || null} onSelect={selectEvidence} />}
              {viewed === "plan" && <PlanPanel workflow={workflow} pending={disabled} onDecision={handlePlanDecision} onSelect={selectEvidence} />}
              {viewed === "plan" && !workflow.plan && <p className="empty-state">No validated repair plan is available.</p>}
              {viewed === "patch" && <><DiffPanel workflow={workflow} /><TestPanel test={workflow.test} attempt={workflow.patch?.attempt_number} />{!workflow.patch && <p className="empty-state">No validated patch is available.</p>}</>}
              {viewed === "tests" && <><TestPanel test={workflow.test} attempt={workflow.patch?.attempt_number} /><CriticPanel workflow={workflow} onSelect={selectEvidence} />{!workflow.test && <p className="empty-state">No test result is available at this checkpoint.</p>}</>}
              {viewed === "final" && <FinalReviewPanel workflow={workflow} pending={disabled} onDecision={handleFinalDecision} />}
              {viewed === "export" && <><CompletionPanel workflow={workflow} />{!workflow.export && <p className="empty-state">No exported artifact is available.</p>}</>}
            </div>
          </>}
      </main>
      <ContextInspector workflow={workflow} selected={selected} open={contextOpen} onClose={() => setContextOpen(false)} />
    </div>
  </div>;
}

function StartScreen({ repositoryPath, issue, pending, blocked, errors, onRepositoryChange, onIssueChange, onSubmit }: {
  repositoryPath: string; issue: string; pending: boolean; blocked: boolean; errors: { repository?: string; issue?: string };
  onRepositoryChange: (value: string) => void; onIssueChange: (value: string) => void; onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return <section className="start-screen" aria-labelledby="start-title">
    <div className="start-canvas">
      <header className="start-heading">
        <div className="start-eyebrow"><span aria-hidden="true" /> New workflow</div>
        <h1 id="start-title">New repair</h1>
        <p>Analyze a local Python repository and build an evidence-grounded repair plan.</p>
        <div className="start-metadata"><span>PYTHON 3.11+</span><span>LOCAL SOURCE</span><span>2 APPROVALS</span></div>
      </header>
      <form className="start-form" onSubmit={onSubmit} noValidate>
        <div className={`field-shell repository-field ${errors.repository ? "has-error" : ""}`}>
          <div className="field-heading"><label htmlFor="repository-path"><span className="field-icon" aria-hidden="true"><svg viewBox="0 0 20 20"><path d="M2.75 5.75h5l1.5 1.75h8v7.75h-14.5z" /></svg></span>Repository</label><span>PATH</span></div>
          <div className="input-frame"><input className="path-input" id="repository-path" name="repository_path" value={repositoryPath} disabled={pending || blocked} onChange={(event) => onRepositoryChange(event.target.value)} placeholder="C:\projects\python-repository" autoComplete="off" aria-label="Repository path" aria-invalid={!!errors.repository} aria-describedby={errors.repository ? "repository-error" : "repository-help"} /></div>
          <div className="field-footer">{errors.repository ? <p id="repository-error" className="field-error" role="alert">{errors.repository}</p> : <p className="form-help" id="repository-help">Absolute path to an existing local repository</p>}<span>READ ONLY</span></div>
        </div>
        <div className={`field-shell issue-field ${errors.issue ? "has-error" : ""}`}>
          <div className="field-heading"><label htmlFor="issue"><span className="field-icon issue-icon" aria-hidden="true"><svg viewBox="0 0 20 20"><path d="M4 3.5h12v13H4zM7 7h6M7 10h6M7 13h3" /></svg></span>Issue</label><span>REPAIR BRIEF</span></div>
          <div className="input-frame"><textarea id="issue" name="issue" rows={9} value={issue} disabled={pending || blocked} onChange={(event) => onIssueChange(event.target.value)} placeholder="Describe the defect, expected behavior, and relevant constraints…" aria-invalid={!!errors.issue} aria-describedby={errors.issue ? "issue-error" : "issue-help"} /></div>
          <div className="field-footer">{errors.issue ? <p id="issue-error" className="field-error" role="alert">{errors.issue}</p> : <p className="form-help" id="issue-help">Repository content and issue text are treated as untrusted evidence</p>}<span>{issue.length.toLocaleString()} / 100,000</span></div>
        </div>
        <div className="start-action"><div className="action-boundary"><span aria-hidden="true" /><p><strong>First stop: plan review</strong>Nothing is patched before you approve the exact file scope.</p></div><button type="submit" disabled={pending || blocked}>{pending ? "Analyzing repository…" : "Analyze repository"}<span className="button-arrow" aria-hidden="true">→</span></button></div>
      </form>
      {pending && <div className="start-loading"><LoadingState action="start" /></div>}
    </div>
  </section>;
}
function LoadingState({ action }: { action: Exclude<PendingAction, null> }) {
  const copy = { start: "Building repository evidence and generating a grounded repair plan. Inference may take several minutes.", refresh: "Reading the durable workflow checkpoint. No workflow stage is being rerun.", plan: "Submitting the plan decision. If approved, scoped patching and Docker tests run; a genuine failure may invoke the single allowed retry.", final: "Submitting the final decision. If approved, the exact tested patch is verified and exported." }[action];
  return <div className="loading-banner" role="status"><span className="spinner" aria-hidden="true" /><span>{copy}</span></div>;
}
function messageFor(error: unknown): string {
  if (!(error instanceof WorkflowApiError)) return "The request could not be completed. Refresh authoritative state before trying again.";
  const messages: Record<string, string> = {
    network_error: "Could not reach the RepoPilot backend. Check the local backend connection.",
    invalid_repository: "Repository path must identify a readable local Python directory.",
    invalid_issue: "Issue text must contain searchable words or identifiers.",
    context_failed: "Repository evidence could not fit the fixed context budget.",
    stale_plan_hash: "The displayed plan hash is stale. Refresh and review the current plan.",
    stale_patch_hash: "The displayed patch hash is stale. Refresh and review the current tested patch.",
    invalid_transition: "This workflow is not waiting for that decision.",
    workflow_not_found: "The workflow checkpoint is not available. Keep its URL for read-only recovery, or explicitly start another repair.",
    thread_conflict: "This workflow identity already exists. Refresh its authoritative state.",
    unreadable_response: "The backend returned an unreadable response.",
  };
  return messages[error.code] || "The workflow request failed safely. Check the backend and refresh authoritative state.";
}
export default App;
