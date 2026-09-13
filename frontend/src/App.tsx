import { FormEvent, useEffect, useState } from "react";

import {
  createWorkflow,
  fetchWorkflow,
  submitFinalDecision,
  submitPlanDecision,
  WorkflowApiError,
  type WorkflowView,
} from "./api/workflows";
import {
  CompletionPanel,
  CriticPanel,
  DiffPanel,
  EvidencePanel,
  FailurePanel,
  FinalReviewPanel,
  PlanPanel,
  TestPanel,
} from "./components/ReviewPanels";
import { WorkflowProgress } from "./components/WorkflowProgress";
import "./App.css";

type PendingAction = "start" | "refresh" | "plan" | "final" | null;

function threadFromLocation(): string | null {
  return new URLSearchParams(window.location.search).get("thread");
}

function App() {
  const [repositoryPath, setRepositoryPath] = useState("");
  const [issue, setIssue] = useState("");
  const [workflow, setWorkflow] = useState<WorkflowView | null>(null);
  const [pending, setPending] = useState<PendingAction>(
    threadFromLocation() ? "refresh" : null,
  );
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const threadId = threadFromLocation();
    if (!threadId) return;
    const controller = new AbortController();
    fetchWorkflow(threadId, controller.signal)
      .then((current) => {
        setWorkflow(current);
        setError(null);
      })
      .catch((requestError: unknown) => {
        if (!(requestError instanceof DOMException && requestError.name === "AbortError")) {
          setError(messageFor(requestError));
        }
      })
      .finally(() => setPending(null));
    return () => controller.abort();
  }, []);

  async function handleStart(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const cleanPath = repositoryPath.trim();
    const cleanIssue = issue.trim();
    if (!cleanPath || !cleanIssue) {
      setError(
        !cleanPath && !cleanIssue
          ? "Repository path and issue are required."
          : !cleanPath
            ? "Repository path is required."
            : "Issue is required.",
      );
      return;
    }
    setPending("start");
    setError(null);
    const requestedThreadId = crypto.randomUUID();
    window.history.replaceState(
      null,
      "",
      `?thread=${encodeURIComponent(requestedThreadId)}`,
    );
    try {
      const created = await createWorkflow({
        repository_path: cleanPath,
        issue: cleanIssue,
        thread_id: requestedThreadId,
      });
      setWorkflow(created);
      window.history.replaceState(null, "", `?thread=${encodeURIComponent(created.thread_id)}`);
    } catch (requestError) {
      if (requestError instanceof WorkflowApiError && requestError.code === "network_error") {
        setError(
          `${messageFor(requestError)} Workflow ${requestedThreadId} remains in the URL; refresh to read its authoritative state before starting again.`,
        );
      } else {
        window.history.replaceState(null, "", window.location.pathname);
        setError(messageFor(requestError));
      }
    } finally {
      setPending(null);
    }
  }

  async function refreshWorkflow() {
    if (!workflow || pending) return;
    setPending("refresh");
    setError(null);
    try {
      setWorkflow(await fetchWorkflow(workflow.thread_id));
    } catch (requestError) {
      setError(messageFor(requestError));
    } finally {
      setPending(null);
    }
  }

  async function handlePlanDecision(
    decision: "approve" | "reject",
    comment: string,
  ) {
    if (!workflow || !workflow.plan_hash || pending) return;
    const displayedHash = workflow.plan_hash;
    setPending("plan");
    setError(null);
    try {
      setWorkflow(
        await submitPlanDecision(
          workflow.thread_id,
          { decision, comment: comment.trim() || undefined },
          displayedHash,
        ),
      );
    } catch (requestError) {
      setError(messageFor(requestError));
    } finally {
      setPending(null);
    }
  }

  async function handleFinalDecision(
    decision: "approve" | "reject",
    comment: string,
  ) {
    if (!workflow?.final_review || pending) return;
    const displayedHash = workflow.final_review.final_patch_hash;
    setPending("final");
    setError(null);
    try {
      setWorkflow(
        await submitFinalDecision(
          workflow.thread_id,
          { decision, comment: comment.trim() || undefined },
          displayedHash,
        ),
      );
    } catch (requestError) {
      setError(messageFor(requestError));
    } finally {
      setPending(null);
    }
  }

  function startAnother() {
    if (pending) return;
    setWorkflow(null);
    setRepositoryPath("");
    setIssue("");
    setError(null);
    window.history.replaceState(null, "", window.location.pathname);
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <a className="brand" href={window.location.pathname} aria-label="RepoPilot home">
          <span className="brand-mark" aria-hidden="true">RP</span>
          <span><strong>RepoPilot</strong><small>Local Human-Controlled Repair Agent</small></span>
        </a>
        <span className="local-badge">Local workflow</span>
      </header>

      {!workflow ? (
        <StartScreen
          repositoryPath={repositoryPath}
          issue={issue}
          pending={pending !== null}
          onRepositoryChange={setRepositoryPath}
          onIssueChange={setIssue}
          onSubmit={handleStart}
        />
      ) : (
        <div className="workspace-layout">
          <aside className="workflow-sidebar">
            <div className="repo-identity">
              <p className="section-kicker">Active workflow</p>
              <h1>{workflow.repository.name}</h1>
              <code>{workflow.repository.path}</code>
              <span className="thread-id">Thread {workflow.thread_id}</span>
            </div>
            <WorkflowProgress workflow={workflow} />
            <div className="sidebar-actions">
              <button className="secondary" type="button" disabled={pending !== null} onClick={refreshWorkflow}>Refresh state</button>
              <button className="text-button" type="button" disabled={pending !== null} onClick={startAnother}>Start another repair</button>
            </div>
          </aside>

          <section className="review-workspace" aria-label="Workflow review workspace">
            <header className="review-header">
              <div><p className="section-kicker">Issue under review</p><h1>Human Review Workspace</h1><p>{workflow.issue}</p></div>
              <span className="workflow-status">{workflow.status.replaceAll("_", " ")}</span>
            </header>

            {pending && <LoadingState action={pending} />}
            {error && <div className="request-error" role="alert"><strong>Request not completed</strong><p>{error}</p><p>RepoPilot did not automatically resend this state-changing request. Refresh the authoritative state before deciding again.</p></div>}

            <FailurePanel workflow={workflow} />
            <CompletionPanel workflow={workflow} />
            <FinalReviewPanel workflow={workflow} pending={pending !== null} onDecision={handleFinalDecision} />
            <EvidencePanel workflow={workflow} />
            <PlanPanel workflow={workflow} pending={pending !== null} onDecision={handlePlanDecision} />
            {workflow.status !== "awaiting_final_approval" && <DiffPanel workflow={workflow} />}
            <TestPanel test={workflow.test} />
            <CriticPanel workflow={workflow} />
          </section>
        </div>
      )}

      {!workflow && error && <div className="start-error" role="alert">{error}</div>}
    </main>
  );
}

function StartScreen({
  repositoryPath,
  issue,
  pending,
  onRepositoryChange,
  onIssueChange,
  onSubmit,
}: {
  repositoryPath: string;
  issue: string;
  pending: boolean;
  onRepositoryChange: (value: string) => void;
  onIssueChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <section className="start-screen" aria-labelledby="start-title">
      <div className="start-intro">
        <p className="section-kicker">Local-first · bounded · reviewable</p>
        <h1 id="start-title">Repair with evidence.<br />Decide with context.</h1>
        <p>RepoPilot analyzes a local Python repository and pauses before any patch generation. You approve the exact plan and file scope.</p>
        <ul className="trust-list"><li>No edits before plan approval</li><li>Tests run only in the configured Docker sandbox</li><li>Export only — no commit, push, merge, or PR</li></ul>
      </div>
      <form className="start-form" onSubmit={onSubmit} noValidate>
        <div><label htmlFor="repository-path">Repository path</label><input id="repository-path" name="repository_path" type="text" value={repositoryPath} disabled={pending} onChange={(event) => onRepositoryChange(event.target.value)} placeholder="C:\path\to\python-repository" autoComplete="off" /></div>
        <div><label htmlFor="issue">Issue</label><textarea id="issue" name="issue" rows={8} value={issue} disabled={pending} onChange={(event) => onIssueChange(event.target.value)} placeholder="Describe the bug, expected behavior, and relevant constraints." /></div>
        <p className="form-help">Repository content is treated as untrusted evidence. RepoPilot remains the authority for scope and workflow transitions.</p>
        <button type="submit" disabled={pending}>{pending ? "Running analysis…" : "Start Repair"}</button>
        {pending && <LoadingState action="start" />}
      </form>
    </section>
  );
}

function LoadingState({ action }: { action: Exclude<PendingAction, null> }) {
  const copy = {
    start: "Building repository evidence and generating a grounded repair plan. Local inference may take several minutes.",
    refresh: "Reading the durable workflow checkpoint. No workflow stage is being rerun.",
    plan: "Generating the scoped patch and running tests. A genuine first-attempt failure may invoke the critic and single allowed retry.",
    final: "Verifying the exact approved patch and successful test evidence, then exporting the patch artifact.",
  }[action];
  return <div className="loading-banner" role="status" aria-live="polite"><span className="spinner" aria-hidden="true" /><span>{copy}</span></div>;
}

function messageFor(error: unknown): string {
  if (error instanceof WorkflowApiError) {
    if (error.code === "stale_plan_hash" || error.code === "stale_patch_hash") {
      return `${error.message} The decision was not retried.`;
    }
    return error.message;
  }
  return error instanceof Error ? error.message : "The workflow request failed safely.";
}

export default App;
