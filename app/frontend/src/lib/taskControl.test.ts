import { describe, expect, it } from "vitest";
import { taskPrimaryControl } from "./taskControl";

describe("task primary control", () => {
  it("maps state to one inline control", () => {
    expect(taskPrimaryControl("DRAFT")).toBe("start");
    expect(taskPrimaryControl("QUEUED")).toBe("pause");
    expect(taskPrimaryControl("RUNNING")).toBe("pause");
    expect(taskPrimaryControl("PAUSED")).toBe("resume");
    expect(taskPrimaryControl("PAUSING")).toBeNull();
    expect(taskPrimaryControl("CANCELLING")).toBeNull();
    expect(taskPrimaryControl("CANCELLED")).toBeNull();
    expect(taskPrimaryControl("FINISHED")).toBeNull();
    expect(taskPrimaryControl(undefined)).toBeNull();
  });

  it("can suppress draft starts where the caller has no start path", () => {
    expect(taskPrimaryControl("DRAFT", { allowDraftStart: false })).toBeNull();
    expect(taskPrimaryControl("QUEUED", { allowDraftStart: false })).toBe("pause");
  });
});
