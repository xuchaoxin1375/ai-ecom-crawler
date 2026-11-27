import { afterEach, describe, expect, it, vi } from "vitest";

import { pauseTask, resumeBatch, startTask } from "./api";

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status < 400,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as Response;
}

describe("task control API", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reads the full task back after pausing", async () => {
    const task = {
      task_id: "task-1",
      state: "PAUSING",
      counts: { valid_products: 3, pending_products: 77 },
    };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ accepted: true, state: "PAUSING" }, 202))
      .mockResolvedValueOnce(jsonResponse(task));
    vi.stubGlobal("fetch", fetchMock);

    await expect(pauseTask("task-1")).resolves.toEqual(task);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/tasks/task-1/pause");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/tasks/task-1");
  });

  it("starts a draft task through the task start endpoint", async () => {
    const task = { task_id: "task-1", state: "QUEUED", counts: {} };
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse({ accepted: true, state: "QUEUED" }, 202))
      .mockResolvedValueOnce(jsonResponse(task));
    vi.stubGlobal("fetch", fetchMock);

    await expect(startTask("task-1")).resolves.toEqual(task);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/tasks/task-1/start");
    expect(fetchMock.mock.calls[1][0]).toBe("/api/tasks/task-1");
  });

  it("resumes a batch through the batch resume endpoint", async () => {
    const response = { accepted: [], skipped: [], batch: { batch_id: "b-1" } };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(response, 202));
    vi.stubGlobal("fetch", fetchMock);

    await expect(resumeBatch("b-1")).resolves.toEqual(response);
    expect(fetchMock.mock.calls[0][0]).toBe("/api/batches/b-1/resume");
  });
});
