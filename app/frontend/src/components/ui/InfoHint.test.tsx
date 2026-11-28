import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { InfoHint } from "./InfoHint";

describe("InfoHint", () => {
  it("shows the explanation on hover and hides it on leave", () => {
    render(<InfoHint content="预算耗尽，可继续采集。" label="查看说明" />);

    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
    fireEvent.mouseEnter(screen.getByRole("button", { name: "查看说明" }));
    expect(screen.getByRole("tooltip")).toHaveTextContent("预算耗尽，可继续采集。");
    expect(screen.getByRole("button", { name: "查看说明" })).toHaveAttribute(
      "aria-describedby",
      screen.getByRole("tooltip").id,
    );

    fireEvent.mouseLeave(screen.getByRole("button", { name: "查看说明" }));
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });

  it("pins the explanation on click and closes it with Escape", () => {
    render(<InfoHint content="完整说明" label="查看说明" />);
    const button = screen.getByRole("button", { name: "查看说明" });

    fireEvent.click(button);
    expect(screen.getByRole("tooltip")).toBeInTheDocument();

    fireEvent.keyDown(button, { key: "Escape" });
    expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
  });
});
