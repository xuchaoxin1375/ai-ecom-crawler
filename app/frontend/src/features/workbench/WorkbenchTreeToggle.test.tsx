import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { WorkbenchTreeToggle } from "./WorkbenchTreeToggle";
import {
  getWorkbenchTreeCollapsed,
  setWorkbenchTreeCollapsed,
} from "./workbenchTreeState";

afterEach(() => {
  cleanup();
  setWorkbenchTreeCollapsed(false);
});

it("toggles the workbench tree from the panel edge control", () => {
  render(<WorkbenchTreeToggle />);

  const collapse = screen.getByRole("button", { name: "收起任务目录" });
  expect(collapse).toHaveAttribute("aria-expanded", "true");
  fireEvent.click(collapse);

  const expand = screen.getByRole("button", { name: "展开任务目录" });
  expect(expand).toHaveAttribute("aria-expanded", "false");
  expect(getWorkbenchTreeCollapsed()).toBe(true);

  fireEvent.click(expand);
  expect(getWorkbenchTreeCollapsed()).toBe(false);
  expect(screen.getByRole("button", { name: "收起任务目录" })).toHaveAttribute(
    "aria-expanded",
    "true",
  );
});
