import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DataTableColumn } from "./DataTable";
import { TableDisplayOptions } from "./TableDisplayOptions";

interface Row {
  id: string;
  name: string;
  market: string;
}

const columns: DataTableColumn<Row>[] = [
  { key: "name", header: "名称", label: "名称", cell: (row) => row.name },
  {
    key: "market",
    header: "市场",
    label: "市场",
    hideable: true,
    cell: (row) => row.market,
  },
];

describe("TableDisplayOptions", () => {
  it("toggles columns and width reset", async () => {
    const onToggleColumn = vi.fn();
    const onResetWidths = vi.fn();
    render(
      <TableDisplayOptions
        columns={columns}
        visible={{ name: true, market: true }}
        onToggleColumn={onToggleColumn}
        onResetWidths={onResetWidths}
        widthsDefault={false}
      />,
    );

    fireEvent.pointerDown(screen.getByRole("button", { name: "显示选项" }), {
      button: 0,
    });
    const market = await screen.findByRole("menuitemcheckbox", { name: "市场" });
    expect(market).toHaveAttribute("aria-checked", "true");
    fireEvent.click(market);
    expect(onToggleColumn).toHaveBeenCalledWith("market");
    expect(screen.getByRole("menu")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("menuitem", { name: "重置列宽" }));
    expect(onResetWidths).toHaveBeenCalled();
  });

  it("disables width reset when widths are default", async () => {
    render(
      <TableDisplayOptions
        columns={columns}
        visible={{ name: true, market: true }}
        onToggleColumn={() => {}}
        onResetWidths={() => {}}
        widthsDefault
      />,
    );
    fireEvent.pointerDown(screen.getByRole("button", { name: "显示选项" }), {
      button: 0,
    });
    const reset = await screen.findByRole("menuitem", { name: "重置列宽" });
    expect(reset).toHaveAttribute("data-disabled");
  });
});
