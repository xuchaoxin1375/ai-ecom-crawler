import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SearchInput } from "./SearchInput";

function Harness({ initial = "abc" }: { initial?: string }) {
  const [value, setValue] = useState(initial);
  return (
    <SearchInput
      value={value}
      onChange={(event) => setValue(event.target.value)}
      onClear={() => setValue("")}
      clearLabel="清除测试搜索"
      aria-label="搜索测试"
      placeholder="搜索"
    />
  );
}

describe("SearchInput", () => {
  it("shows a clear button only when there is a value", () => {
    const onClear = vi.fn();
    const { rerender } = render(
      <SearchInput
        value=""
        onChange={() => undefined}
        onClear={onClear}
        clearLabel="清除测试搜索"
        aria-label="搜索测试"
      />,
    );
    expect(screen.queryByRole("button", { name: "清除测试搜索" })).toBeNull();
    rerender(
      <SearchInput
        value="abc"
        onChange={() => undefined}
        onClear={onClear}
        clearLabel="清除测试搜索"
        aria-label="搜索测试"
      />,
    );
    expect(screen.getByRole("button", { name: "清除测试搜索" })).toBeInTheDocument();
  });

  it("clears the value and keeps focus in the search box", () => {
    render(<Harness />);
    const input = screen.getByRole("searchbox", { name: "搜索测试" });
    const clear = screen.getByRole("button", { name: "清除测试搜索" });
    clear.focus();
    fireEvent.click(clear);
    expect(input).toHaveValue("");
    expect(input).toHaveFocus();
    expect(screen.queryByRole("button", { name: "清除测试搜索" })).toBeNull();
  });

  it("supports Escape as an equivalent clear shortcut", () => {
    render(<Harness />);
    const input = screen.getByRole("searchbox", { name: "搜索测试" });
    fireEvent.keyDown(input, { key: "Escape" });
    expect(input).toHaveValue("");
    expect(input).toHaveFocus();
  });
});
