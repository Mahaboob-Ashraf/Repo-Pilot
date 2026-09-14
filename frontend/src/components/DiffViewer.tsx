import { useId, useState } from "react";

export interface DiffLine { text: string; kind: "add" | "remove" | "hunk" | "meta" | "context"; old: number | null; next: number | null; }
export interface DiffFile { path: string; lines: DiffLine[]; added: number; removed: number; }

// Presentation only: the original diff stays intact for review/export identity.
export function parseUnifiedDiff(raw: string): DiffFile[] {
  const files: DiffFile[] = [];
  let file: DiffFile | undefined;
  let old = 0, next = 0, oldRemaining = 0, nextRemaining = 0;
  const lines = raw.split("\n");
  if (lines.at(-1) === "") lines.pop();
  lines.forEach((text, index) => {
    const inHunk = oldRemaining > 0 || nextRemaining > 0;
    if (!file || (!inHunk && text.startsWith("--- ") && lines[index + 1]?.startsWith("+++ "))) {
      file = { path: text.startsWith("--- ") ? text.slice(4).replace(/^a\//, "") : "Patch", lines: [], added: 0, removed: 0 };
      files.push(file);
    }
    const hunk = /^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@/.exec(text);
    const line: DiffLine = { text, kind: "meta", old: null, next: null };
    if (hunk) { old = Number(hunk[1]); oldRemaining = Number(hunk[2] ?? 1); next = Number(hunk[3]); nextRemaining = Number(hunk[4] ?? 1); line.kind = "hunk"; }
    else if (inHunk && text.startsWith("+")) { line.kind = "add"; line.next = next++; nextRemaining--; file.added++; }
    else if (inHunk && text.startsWith("-")) { line.kind = "remove"; line.old = old++; oldRemaining--; file.removed++; }
    else if (inHunk && text.startsWith(" ")) { line.kind = "context"; line.old = old++; line.next = next++; oldRemaining--; nextRemaining--; }
    file.lines.push(line);
  });
  return files;
}

export function DiffViewer({ raw }: { raw: string }) {
  const files = parseUnifiedDiff(raw);
  const id = useId();
  const [rawMode, setRawMode] = useState(false);
  const [wrap, setWrap] = useState(false);
  return <div className="diff-viewer">
    <div className="console-toolbar diff-toolbar"><div className="console-title"><span className="diff-glyph" aria-hidden="true">±</span><span>Unified diff</span></div><div className="toolbar-actions">
      <button type="button" className="text-button" aria-pressed={wrap} onClick={() => setWrap(!wrap)}>Wrap lines</button>
      <button type="button" className="text-button" aria-pressed={rawMode} onClick={() => setRawMode(!rawMode)}>{rawMode ? "Formatted diff" : "Raw diff"}</button>
    </div></div>
    {rawMode ? <pre className={`raw-diff ${wrap ? "wrap-code" : ""}`} tabIndex={0} aria-label="Canonical unified diff">{raw}</pre>
      : <>
        {files.length > 1 && <nav className="diff-files" aria-label="Changed file navigation"><span>Files</span>{files.map((file, index) => <a key={index} href={`#${id}-${index}`}><code>{file.path}</code><small>+{file.added} −{file.removed}</small></a>)}</nav>}
        <div aria-label="Canonical unified diff">{files.map((file, index) => <section className="diff-file" id={`${id}-${index}`} key={index} aria-label={`Diff for ${file.path}`}>
          <header><div className="diff-file-name"><span aria-hidden="true" /><code>{file.path}</code></div><span className="diff-counts"><span className="added">+{file.added}</span><span className="removed">−{file.removed}</span></span></header>
          <div className={`diff-scroll ${wrap ? "wrap-code" : ""}`} tabIndex={0} role="region" aria-label={`${file.path} changes`}>
            <pre>{file.lines.map((line, lineIndex) => <span key={lineIndex} className={`diff-line diff-${line.kind}`}><span className="line-number" aria-hidden="true">{line.old}</span><span className="line-number" aria-hidden="true">{line.next}</span><code>{line.text}{"\n"}</code></span>)}</pre>
          </div>
        </section>)}</div>
      </>}
  </div>;
}
