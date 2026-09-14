import { useEffect, useRef, useState } from "react";
import type { EvidenceItem, WorkflowView } from "../api/workflows";
export function citationLabel(item: EvidenceItem) { return `${item.path}:${item.start_line}–${item.end_line}`; }
export function SourceContext({ item }: { item: EvidenceItem }) {
  const sourceLines = item.source_text?.split("\n") || [];
  if (sourceLines.at(-1) === "") sourceLines.pop();
  return <>
    <div className="source-path"><span className="source-file-mark" aria-hidden="true" /><div><span>Selected source</span><code>{item.path}</code></div><small>{item.start_line}–{item.end_line}</small></div>
    <dl className="inspector-facts">
      <div><dt>Symbol</dt><dd><code>{item.symbol || "Unavailable"}</code></dd></div>
      <div><dt>Lines</dt><dd>{item.start_line}–{item.end_line} · {item.chunk_type}</dd></div>
      <div><dt>Origin</dt><dd>{item.origin === "retrieved" ? "Retrieved" : "Structural expansion"}{item.retrieval_rank !== null ? ` · rank ${item.retrieval_rank}` : ""}</dd></div>
    </dl>
    {item.source_text === null ? <p className="empty-state">Source context is unavailable for this citation.</p>
      : <div className="source-code" tabIndex={0} role="region" aria-label={`Source context for ${citationLabel(item)}`}>
        <pre>{sourceLines.map((line, index) => <span className="source-line" key={index}><span className="line-number" aria-hidden="true">{item.start_line + index}</span><code>{line}{index < sourceLines.length - 1 || item.source_text?.endsWith("\n") ? "\n" : ""}</code></span>)}</pre>
      </div>}
    <details className="provenance" open><summary>Exact provenance</summary><dl className="inspector-facts"><div><dt>Chunk ID</dt><dd><code>{item.chunk_id}</code></dd></div>
      {item.structural_causes.length > 0 && <div><dt>Expansion causes</dt><dd>{item.structural_causes.join(", ")}</dd></div>}
    </dl></details>
  </>;
}
export function ContextInspector({ workflow, selected, open, onClose }: {
  workflow: WorkflowView | null; selected: EvidenceItem | null; open: boolean; onClose: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [wide, setWide] = useState(() => window.matchMedia("(min-width: 1280px)").matches);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    const media = window.matchMedia("(min-width: 1280px)");
    const update = () => setWide(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  const modal = (open && !wide) || expanded;
  useEffect(() => {
    const node = dialog.current;
    if (!node || !modal) return;
    const trigger = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    node.showModal();
    return () => { node.close(); if (trigger?.isConnected) trigger.focus(); };
  }, [modal]);
  function close() { setExpanded(false); onClose(); }
  const body = selected ? <SourceContext item={selected} /> : <div className={`inspector-empty ${workflow ? "" : "initial-inspector-content"}`}>
    {!workflow && <div className="inspector-orbit" aria-hidden="true"><span /><span /><span /></div>}
    <p className="inspector-eyebrow">{workflow ? "Context" : "Workspace"}</p>
    <h3>{workflow ? "Context, within reach" : "Controlled repair environment"}</h3>
    <p>{workflow ? "Select an evidence citation to inspect its exact repository source." : "A bounded review path from local source to an exported patch."}</p>
    {!workflow && <>
      <dl className="workspace-specs">
        <div><dt>Language</dt><dd><code>Python 3.11+</code></dd></div>
        <div><dt>Execution</dt><dd>Docker sandbox</dd></div>
        <div><dt>Authority</dt><dd>Human controlled</dd></div>
      </dl>
      <div className="repair-policy"><p>Repair policy</p><ol>
        <li><span>01</span><strong>Evidence-grounded plan</strong></li>
        <li><span>02</span><strong>Approve plan + scope</strong></li>
        <li><span>03</span><strong>Verify in Docker</strong></li>
        <li><span>04</span><strong>Approve tested patch</strong></li>
      </ol></div>
      <div className="export-boundary"><span className="boundary-mark" aria-hidden="true" />
        <div><strong>Export boundary</strong><p><code>.patch</code> file only</p></div>
      </div>
    </>}
    {workflow && <dl className="inspector-facts"><div><dt>Evidence</dt><dd>{workflow.retrieval.evidence_count} chunks</dd></div><div><dt>Retrieval</dt><dd>{workflow.retrieval.mode || "Unavailable"}</dd></div><div><dt>Thread</dt><dd><code>{workflow.thread_id}</code></dd></div></dl>}
    <p className="muted">RepoPilot does not commit, merge, or open a PR.</p>
  </div>;
  return <>
    <aside className={`context-inspector ${workflow ? "" : "initial-context-inspector"}`} aria-label={workflow ? "Context inspector" : "Workspace context"}><header className="inspector-header"><h2>{workflow ? "Source context" : "Workspace context"}</h2>{selected && <button type="button" className="text-button" onClick={() => setExpanded(true)}>Expand source</button>}</header>{wide && !modal && body}</aside>
    <dialog ref={dialog} className={`context-drawer ${expanded ? "expanded-source" : ""}`} aria-labelledby="drawer-title" onCancel={(event) => { event.preventDefault(); close(); }}>
      <header className="inspector-header"><h2 id="drawer-title">{workflow ? "Source context" : "Workspace context"}</h2><button type="button" className="secondary" onClick={close} autoFocus>Close context</button></header>{modal && body}
    </dialog>
  </>;
}
