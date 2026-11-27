import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TableViewToggle, type TableViewOption } from "./TableViewToggle";

const options: TableViewOption<"standard" | "fields">[] = [
  { value: "standard", label: "标准", title: "标准视图" },
  { value: "fields", label: "字段", title: "字段视图" },
];

describe("TableViewToggle", () => {
  it("marks the active view and switches to fields", () => {
    const onChange = vi.fn();
    render(<TableViewToggle value="standard" options={options} onChange={onChange} />);

    const standard = screen.getByRole("button", { name: "标准" });
    const fields = screen.getByRole("button", { name: "字段" });
    expect(standard).toHaveAttribute("aria-pressed", "true");
    expect(fields).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(fields);
    expect(onChange).toHaveBeenCalledWith("fields");
  });
});
