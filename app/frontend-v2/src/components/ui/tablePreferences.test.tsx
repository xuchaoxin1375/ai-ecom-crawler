import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";
import type { DataTableColumn } from "./DataTable";
import { useTablePreferences } from "./tablePreferences";

interface Row {
  id: string;
  name: string;
  market: string;
}

const rows: Row[] = [
  { id: "a", name: "Beta", market: "FR" },
  { id: "b", name: "Alpha", market: "DE" },
  { id: "c", name: "Gamma", market: "FR" },
];

const columns: DataTableColumn<Row>[] = [
  {
    key: "name",
    header: "名称",
    sortable: true,
    sortValue: (row) => row.name,
    cell: (row) => row.name,
  },
  {
    key: "market",
    header: "市场",
    hideable: true,
    cell: (row) => row.market,
  },
];

function Harness() {
  const table = useTablePreferences({
    tableKey: "prefs-test",
    columns,
    defaultDensity: "default",
  });
  return (
    <div>
      <p data-testid="visible">
        {table.visibleColumns.map((column) => column.key).join(",")}
      </p>
      <p data-testid="density">{table.density}</p>
      <p data-testid="sort">
        {table.sort ? `${table.sort.key}:${table.sort.direction}` : "none"}
      </p>
      <button type="button" onClick={() => table.toggleColumn("market")}>
        切换市场
      </button>
      <button type="button" onClick={() => table.toggleSort("name")}>
        按名称排序
      </button>
      <button type="button" onClick={() => table.setDensity("compact")}>
        紧凑
      </button>
      <ul>
        {table.sortRows(rows).map((row) => (
          <li key={row.id}>{row.name}</li>
        ))}
      </ul>
    </div>
  );
}

beforeEach(() => {
  localStorage.clear();
});

describe("useTablePreferences", () => {
  it("hides a column, persists it and keeps essential columns visible", () => {
    render(<Harness />);
    expect(screen.getByTestId("visible")).toHaveTextContent("name,market");

    fireEvent.click(screen.getByRole("button", { name: "切换市场" }));

    expect(screen.getByTestId("visible")).toHaveTextContent("name");
    expect(
      JSON.parse(localStorage.getItem("ecom.table.prefs-test.visible.v1") ?? "{}"),
    ).toMatchObject({ name: true, market: false });
  });

  it("cycles ascending, descending and unsorted", () => {
    render(<Harness />);
    const rowsBefore = screen.getAllByRole("listitem").map((item) => item.textContent);
    expect(rowsBefore).toEqual(["Beta", "Alpha", "Gamma"]);

    fireEvent.click(screen.getByRole("button", { name: "按名称排序" }));
    expect(screen.getByTestId("sort")).toHaveTextContent("name:asc");
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Alpha",
      "Beta",
      "Gamma",
    ]);

    fireEvent.click(screen.getByRole("button", { name: "按名称排序" }));
    expect(screen.getByTestId("sort")).toHaveTextContent("name:desc");
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Gamma",
      "Beta",
      "Alpha",
    ]);

    fireEvent.click(screen.getByRole("button", { name: "按名称排序" }));
    expect(screen.getByTestId("sort")).toHaveTextContent("none");
    expect(screen.getAllByRole("listitem").map((item) => item.textContent)).toEqual(
      rowsBefore,
    );
  });

  it("clears the sort when its column is hidden", () => {
    function SortAndHideHarness() {
      const table = useTablePreferences({
        tableKey: "prefs-test-hide-sort",
        columns: columns.map((column) => ({ ...column, hideable: true })),
      });
      return (
        <div>
          <p data-testid="sort">
            {table.sort ? `${table.sort.key}:${table.sort.direction}` : "none"}
          </p>
          <button type="button" onClick={() => table.toggleSort("name")}>
            按名称排序
          </button>
          <button type="button" onClick={() => table.toggleColumn("name")}>
            隐藏名称
          </button>
        </div>
      );
    }
    render(<SortAndHideHarness />);
    fireEvent.click(screen.getByRole("button", { name: "按名称排序" }));
    expect(screen.getByTestId("sort")).toHaveTextContent("name:asc");

    fireEvent.click(screen.getByRole("button", { name: "隐藏名称" }));
    expect(screen.getByTestId("sort")).toHaveTextContent("none");
  });

  it("restores density and visibility preferences", () => {
    localStorage.setItem("ecom.table.prefs-test.density.v1", "compact");
    localStorage.setItem(
      "ecom.table.prefs-test.visible.v1",
      JSON.stringify({ market: false }),
    );
    render(<Harness />);
    expect(screen.getByTestId("density")).toHaveTextContent("compact");
    expect(screen.getByTestId("visible")).toHaveTextContent("name");
  });
});
