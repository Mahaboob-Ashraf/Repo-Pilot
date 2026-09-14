import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { DiffViewer, parseUnifiedDiff } from "./DiffViewer";

describe("canonical diff presentation", () => {
  it("counts changes and numbers multiple hunks/files without counting file headers", () => {
    const files = parseUnifiedDiff("--- a/a.py\n+++ b/a.py\n@@ -3,2 +3,2 @@\n keep\n-old\n+new\n@@ -9,0 +10,1 @@\n+extra\n--- a/b.py\n+++ b/b.py\n@@ -1 +1 @@\n-before\n+after\n");
    expect(files.map(({ path, added, removed }) => ({ path, added, removed }))).toEqual([
      { path: "a.py", added: 2, removed: 1 }, { path: "b.py", added: 1, removed: 1 },
    ]);
    expect(files[0].lines.find((line) => line.text === "+extra")).toMatchObject({ old: null, next: 10 });
  });
  it("keeps header-like source lines inside their hunk", () => {
    const files = parseUnifiedDiff("--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n--- text\n+++ text\n");
    expect(files).toHaveLength(1); expect(files[0]).toMatchObject({ added: 1, removed: 1 });
  });
  it("exposes the unmodified raw diff including trailing newlines", async () => {
    const raw = "--- a/a.py\n+++ b/a.py\n@@ -1 +1 @@\n-<script>bad()</script>\n+fixed\n";
    const user = userEvent.setup(); const view = render(<DiffViewer raw={raw} />);
    await user.click(screen.getByRole("button", { name: "Raw diff" }));
    expect(screen.getByLabelText("Canonical unified diff").textContent).toBe(raw);
    expect(view.container.querySelector("script")).toBeNull();
  });
});
