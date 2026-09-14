# Task 022B — Graphite review notes

## Status

Frontend implementation and automated checks are complete. **Task acceptance is
still pending browser visual review and one real controlled workflow through
the UI.** The browser connector returned an empty browser inventory;
`getBrowser` reported no browser and the in-app browser was unavailable.
No real workflow was submitted, and this is not a repair success or failure.

Starting repository: `C:\Users\Admin\Desktop\Ashraf\Repo-Pilot`, branch `main`,
clean `git status --short`. Git warned that its user-level ignore file was
unreadable. No backend/API code, dependencies, benchmark data, or lockfiles
changed. No commit or push occurred.

## Implemented surface

- Semantic dark/light tokens, system-safe UI/monospace stacks, 6/8/12px radii,
  static shell grid/glow, and Dark/Light/System preference persistence. A head
  bootstrap applies the theme before the application mounts.
- A 56px topbar and 208px / flexible / 320px workbench at 1280px and above.
  Below 1280px context becomes a native modal drawer; below 960px a stage
  selector replaces the rail; below 640px the drawer is full-screen and actions
  stack. Short viewports put approval strips in document flow.
- Seven reviewable stages, distinct viewed/current states, meaningful rejected
  and failed labels, and critic/retry within Tests. No fake progress or health.
- Exact source citations, line numbers, chunk provenance, read-only proposed
  scope, suggested tests, reviewer comments, explicit checkpoint labels/actions.
- Unified diff file navigation, hunk/line markers, derived change counts,
  subtle green additions/red removals, wrap toggle, and unchanged raw diff.
- Structured Docker results, separate stdout/stderr, bounded-output notices,
  and no invented test counts. Final approval checks passing evidence/hash and
  attempt consistency and still submits only the existing exact-hash decision.
- Export receipt, artifact-detail copy, and no unsupported download or Git UI.
- Synchronous request guards, read-only recovery after ambiguous/stale requests,
  safe default error copy, associated form errors, keyboard citations, focus
  return, status summaries, and reduced-motion overrides.
- Glass only on topbar, drawer, and approval strip; code/test/source stay solid.
  Control transitions are 150ms, content fade 180ms, drawer entry 220ms/12px.

## Code-level design audit

The forest-green branding, warm civic palette, editorial hero, and marketing
form card have been replaced. Dark and light define complete surface/status
tokens. The central review remains dominant; context has quieter metadata.
Final approval was refined to keep the exact diff above expandable test logs.
No animated background, new product scope, or large design dependency was added.

These are code-level findings, not screenshot-verified visual claims. Actual
light/dark rendering, small-screen reflow, zoom, and native focus trapping remain
unverified. Do not call the dark theme presentation-grade until reviewed live.

Static WCAG relative-luminance calculations on the declared opaque pairs:

| Pair | Dark | Light |
|---|---:|---:|
| Muted text / surface | 8.27:1 | 6.15:1 |
| Muted text / hover | 6.42:1 | 5.24:1 |
| Control border / surface | 3.72:1 | 3.63:1 |
| Success text / success background | 10.00:1 | 6.57:1 |
| Warning text / warning background | 10.21:1 | 6.05:1 |
| Danger text / danger background | 8.29:1 | 5.85:1 |

White text on the indigo primary button is 6.29:1. These calculations do not
verify every rendered pair, translucent compositing, or full WCAG conformance.

## Automated verification — 2026-09-14

| Check | Measured result |
|---|---|
| `npm.cmd test` | 34 passed across 3 files |
| `npm.cmd run build` | `tsc --noEmit` passed; Vite 7.3.6 built 36 modules |
| API tests (`test_workflow_api.py`, `test_api.py`) | 18 passed |
| Focused plan approval, patch/workspace, Docker, critic/export workflow tests | 118 passed |
| `uv run --locked --offline pytest -q` | 350 passed in 7.49 seconds |
| `git diff --check` | Passed |
| Backend `/health` | `ok`, `repopilot-backend` |
| Real browser smoke / screenshots | Not run: no connected browser |

The first frontend invocation was blocked by PowerShell's `npm.ps1` policy;
`npm.cmd` avoids that wrapper. Sandboxed esbuild/uv commands also encountered
ancestor/cache permissions; the same project scripts subsequently ran with
approved dependency and temporary-directory access. No policy, installation,
or machine configuration change was made. Unit tests use simulated browser APIs
and deterministic workflow fixtures; their passing results are not a real
workflow smoke. Existing benchmark files and fixture bytes remain unchanged.

## One controlled manual demo

Use the ordinary servers documented in `setup.md`; generation selection stays
server-side. Do not edit `.env`, download models/images, or run benchmark CLIs.

Repository:

```text
C:\Users\Admin\Desktop\Ashraf\Repo-Pilot\fixtures\toy-repo
```

Exact issue:

```text
apply_discount increases the price for a positive discount. A 20 percent discount on 100 should return 80, and a zero percent discount should keep the original price. Fix the arithmetic while preserving the public function signature.
```

Run once through Start analysis. Inspect retrieval and a source citation, then
review the proposed plan/scope before clicking **Approve plan and file scope**.
Inspect the canonical diff and Docker evidence. If the backend reaches the
second checkpoint, review the exact tested identity before clicking **Approve
tested patch for export**. Record whatever actually happens; do not repeat a
failed run to obtain a better screenshot. Critic/retry runs only if naturally
triggered by the unchanged backend. Canonical fixture tests must never run on
the host.

Pre-smoke SHA-256 values (no real smoke has run):

- `pricing.py`: `84b9630522b0d5996b6083fc0d1385d704bdf4ce243b4ca2c44bf41c7113434d`
- `tests/test_pricing.py`: `1f40c4ddcd16874bbc126b5327c5e02eb9bf8f3e091cf79188a9f52d48aa2247`

## Screenshot sequence

Prefer Dark. Capture only actual states reached in the single run:

1. New repair before submission.
2. Plan review with a cited source open in the inspector.
3. Patch view with its unified diff and passing Docker result, if reached.
4. Final approval before deciding; include checkpoint wording and exact diff.
5. Export receipt after successful export, if reached.

Completed stages can be revisited read-only. Approval controls disappear after
their decision, so capture those before continuing. If the workflow fails,
capture the honest failure state instead of fabricating later states.

Manual accessibility review should cover Tab/Shift+Tab, Enter on citations,
Escape/Close on the drawer, focus return, both themes, System switching,
375px/640px/960px/1280px widths, 200%/400% zoom, and reduced motion.

## Task 022D workflow surfaces

The approved Graphite shell now continues through Evidence, Plan Review,
both approval checkpoints, unified diff review, Docker test output, bounded
critic/retry history, and the export receipt. Evidence selection exposes an
explicit selected state and opens the existing focus-managed source inspector.
Code, diff, and console bodies remain solid; glass remains limited to chrome,
drawers, and decision strips. No workflow or API contract changed.

The screenshot sequence above remains the intended Dark-mode review set. The
connected automation environment still exposes no browser, so no real UI smoke
or screenshot claim was added. Use the documented repository and exact issue
once, preserve both approvals, and record the actual result without rerunning.

Task 022D verification on 2026-09-14: 34 frontend tests passed; the production
build passed its TypeScript check and transformed 36 modules; 136 focused
backend API/workflow/approval/patch/workspace/Docker/critic/export tests passed;
the complete backend suite passed 350 tests in 8.34 seconds; and
`git diff --check` passed.
