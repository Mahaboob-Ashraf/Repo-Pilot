import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createWorkflow,
  fetchWorkflow,
  submitFinalDecision,
  submitPlanDecision,
  WorkflowApiError,
} from "./workflows";

const planHash = "a".repeat(64);
const patchHash = "b".repeat(64);

afterEach(() => vi.unstubAllGlobals());

describe("typed workflow API client", () => {
  it("sends create workflow as one explicit JSON POST", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ thread_id: "thread-1" }), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await createWorkflow({ repository_path: "C:\\repo", issue: "Fix bug" });
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(fetchMock.mock.calls[0][1]).toMatchObject({
      method: "POST",
      body: JSON.stringify({ repository_path: "C:\\repo", issue: "Fix bug" }),
    });
  });

  it("binds decision payloads to caller-supplied exact hashes", async () => {
    const fetchMock = vi.fn().mockImplementation(() =>
      Promise.resolve(
        new Response(JSON.stringify({ status: "ok" }), { status: 200 }),
      ),
    );
    vi.stubGlobal("fetch", fetchMock);
    await submitPlanDecision("thread-1", { decision: "approve" }, planHash);
    await submitFinalDecision("thread-1", { decision: "reject" }, patchHash);
    expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({
      decision: "approve",
      plan_hash: planHash,
    });
    expect(JSON.parse(fetchMock.mock.calls[1][1].body)).toEqual({
      decision: "reject",
      patch_hash: patchHash,
    });
  });

  it("parses bounded non-2xx error payloads", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            detail: { code: "stale_plan_hash", message: "Refresh first." },
          }),
          { status: 409 },
        ),
      ),
    );
    await expect(
      submitPlanDecision("thread-1", { decision: "approve" }, planHash),
    ).rejects.toMatchObject({
      code: "stale_plan_hash",
      status: 409,
      message: "Refresh first.",
    });
  });

  it("does not retry a failed state-changing request and supports GET cancellation", async () => {
    const fetchMock = vi.fn().mockRejectedValue(new TypeError("network down"));
    vi.stubGlobal("fetch", fetchMock);
    await expect(
      createWorkflow({ repository_path: "repo", issue: "issue" }),
    ).rejects.toMatchObject({ code: "network_error" });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    const controller = new AbortController();
    fetchMock.mockResolvedValueOnce(
      new Response(JSON.stringify({ thread_id: "thread-1" }), { status: 200 }),
    );
    await fetchWorkflow("thread-1", controller.signal);
    expect(fetchMock.mock.calls[1][1].signal).toBe(controller.signal);
  });
});
