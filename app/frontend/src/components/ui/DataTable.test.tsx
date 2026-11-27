import { useRef } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DataTable, type DataTableColumn } from "./DataTable";

interface Row {
  id: string;
  name: string;
  count: number;
}

const rows: Row[] = [
  { id: "a", name: "Alpha", count: 3 },
  { id: "b", name: "Beta", count: 8 },
];

const columns: DataTableColumn<Row>[] = [
  {
    key: "name",
    header: "名称",
    width: 200,
    minWidth: 120,
    maxWidth: 300,
    cell: (row) => row.name,
  },
  {
    key: "count",
    header: "数量",
    width: 100,
    minWidth: 80,
    maxWidth: 160,
    align: "right",
    cell: (row) => row.count,
  },
  {
    key: "actions",
    header: "操作",
    width: 52,
    resizable: false,
    sticky: "right",
    cell: () => <button type="button">查看</button>,
  },
];

const storageKey = "ecom.table.test-table.columns.v1";

function renderTable(resizeKey: string | null = "test-table") {
  return render(
    <DataTable
      caption="测试列表"
      columns={columns}
      rows={rows}
      rowKey={(row) => row.id}
      resizeKey={resizeKey ?? undefined}
    />,
  );
}

beforeEach(() => {
  localStorage.clear();
});

describe("DataTable column resizing", () => {
  it("adds one resize handle per resizable column and a filler before the sticky actions", () => {
    renderTable();
    expect(screen.getAllByRole("separator")).toHaveLength(2);
    expect(
      screen.queryByRole("separator", { name: "调整「操作」列宽" }),
    ).not.toBeInTheDocument();
    const headers = Array.from(document.querySelectorAll("thead th"));
    expect(headers.map((header) => header.textContent)).toEqual([
      "名称",
      "数量",
      "",
      "操作",
    ]);
  });

  it("changes width with the keyboard and persists the committed value", () => {
    renderTable();
    const handle = screen.getByRole("separator", { name: "调整「名称」列宽" });

    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(handle).toHaveAttribute("aria-valuenow", "208");

    fireEvent.keyDown(handle, { key: "ArrowRight", shiftKey: true });
    expect(handle).toHaveAttribute("aria-valuenow", "240");

    expect(JSON.parse(localStorage.getItem(storageKey) ?? "{}")).toMatchObject({
      name: 240,
    });
  });

  it("supports Home, End, Enter and double-click reset", () => {
    renderTable();
    const handle = screen.getByRole("separator", { name: "调整「名称」列宽" });

    fireEvent.keyDown(handle, { key: "Home" });
    expect(handle).toHaveAttribute("aria-valuenow", "120");
    fireEvent.keyDown(handle, { key: "End" });
    expect(handle).toHaveAttribute("aria-valuenow", "300");
    fireEvent.keyDown(handle, { key: "Enter" });
    expect(handle).toHaveAttribute("aria-valuenow", "200");

    fireEvent.keyDown(handle, { key: "ArrowLeft" });
    expect(handle).toHaveAttribute("aria-valuenow", "192");
    fireEvent.doubleClick(handle);
    expect(handle).toHaveAttribute("aria-valuenow", "200");
    expect(localStorage.getItem(storageKey)).toBeNull();
  });

  it("clamps stored widths and ignores invalid entries", () => {
    localStorage.setItem(
      storageKey,
      JSON.stringify({ name: 9999, count: "wide", unknown: 300 }),
    );
    renderTable();
    expect(screen.getByRole("separator", { name: "调整「名称」列宽" })).toHaveAttribute(
      "aria-valuenow",
      "300",
    );
    expect(screen.getByRole("separator", { name: "调整「数量」列宽" })).toHaveAttribute(
      "aria-valuenow",
      "100",
    );
  });

  it("resets every column through the table API", () => {
    function ResetHarness() {
      const resetRef = useRef<(() => void) | null>(null);
      return (
        <>
          <button type="button" onClick={() => resetRef.current?.()}>
            重置列宽
          </button>
          <DataTable
            caption="测试列表"
            columns={columns}
            rows={rows}
            rowKey={(row) => row.id}
            resizeKey="test-table"
            onResetWidthsReady={(reset) => {
              resetRef.current = reset;
            }}
          />
        </>
      );
    }
    render(<ResetHarness />);
    const handle = screen.getByRole("separator", { name: "调整「名称」列宽" });
    fireEvent.keyDown(handle, { key: "ArrowRight" });
    expect(localStorage.getItem(storageKey)).not.toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "重置列宽" }));

    expect(handle).toHaveAttribute("aria-valuenow", "200");
    expect(localStorage.getItem(storageKey)).toBeNull();
  });

  it("keeps the old fixed-width table when resizeKey is absent", () => {
    renderTable(null);
    expect(screen.queryByRole("separator")).not.toBeInTheDocument();
    const headers = Array.from(document.querySelectorAll("thead th"));
    expect(headers.map((header) => header.textContent)).toEqual([
      "名称",
      "数量",
      "操作",
    ]);
  });
});

describe("DataTable sorting affordance", () => {
  it("marks the sorted column and reports clicks", () => {
    const onSort = vi.fn();
    const sortableColumns = columns.map((column) =>
      column.key === "name" ? { ...column, sortable: true } : column,
    );
    render(
      <DataTable
        caption="测试列表"
        columns={sortableColumns}
        rows={rows}
        rowKey={(row) => row.id}
        sort={{ key: "name", direction: "asc" }}
        onSort={onSort}
      />,
    );
    const firstHeader = document.querySelector("thead th");
    expect(firstHeader).toHaveAttribute("aria-sort", "ascending");
    fireEvent.click(screen.getByRole("button", { name: "按「名称」排序" }));
    expect(onSort).toHaveBeenCalledWith("name");
  });
});

describe("DataTable mobile cards", () => {
  function withNarrowContainer(test: () => void) {
    const descriptor = Object.getOwnPropertyDescriptor(
      HTMLElement.prototype,
      "clientWidth",
    );
    Object.defineProperty(HTMLElement.prototype, "clientWidth", {
      configurable: true,
      get: () => 680,
    });
    try {
      test();
    } finally {
      if (descriptor) {
        Object.defineProperty(HTMLElement.prototype, "clientWidth", descriptor);
      } else {
        delete (HTMLElement.prototype as { clientWidth?: number }).clientWidth;
      }
    }
  }

  it("renders rows as cards and keeps the sort control", () => {
    const onSortChange = vi.fn();
    withNarrowContainer(() => {
      render(
        <DataTable
          caption="测试列表"
          columns={columns.map((column) =>
            column.key === "name" ? { ...column, sortable: true } : column,
          )}
          rows={rows}
          rowKey={(row) => row.id}
          resizeKey="test-table"
          mobileCards
          sort={{ key: "name", direction: "asc" }}
          onSortChange={onSortChange}
        />,
      );

      expect(screen.queryByRole("table")).not.toBeInTheDocument();
      expect(screen.getAllByRole("listitem")).toHaveLength(2);
      expect(screen.getAllByText("数量")).toHaveLength(2);
      expect(screen.getAllByRole("button", { name: "查看" })).toHaveLength(2);

      const sort = screen.getByRole("combobox", { name: "排序" });
      expect(sort).toHaveValue("name:asc");
      fireEvent.change(sort, { target: { value: "name:desc" } });
      expect(onSortChange).toHaveBeenCalledWith({
        key: "name",
        direction: "desc",
      });
      fireEvent.change(sort, { target: { value: "" } });
      expect(onSortChange).toHaveBeenCalledWith(null);
    });
  });

  it("keeps the table with horizontal scrolling when there are many columns", () => {
    const manyColumns: DataTableColumn<Row>[] = [
      ...columns,
      ...Array.from({ length: 5 }, (_, index) => ({
        key: `extra-${index}`,
        header: `扩展 ${index + 1}`,
        width: 90,
        cell: (row: Row) => `${row.name}-${index + 1}`,
      })),
    ];
    withNarrowContainer(() => {
      render(
        <DataTable
          caption="测试列表"
          columns={manyColumns}
          rows={rows}
          rowKey={(row) => row.id}
          resizeKey="test-table-many"
          mobileCards
        />,
      );
      expect(screen.getByRole("table")).toBeInTheDocument();
      expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
    });
  });
});

describe("DataTable compact view", () => {
  const compactColumns: DataTableColumn<Row>[] = [
    {
      key: "name",
      header: "名称／ID",
      compactHeader: "名称",
      cell: (row, { compact }) => (compact ? row.name : `${row.name}-${row.id}`),
    },
  ];

  it("passes compact to cells and uses the compact header", () => {
    const { rerender } = render(
      <DataTable
        caption="测试列表"
        columns={compactColumns}
        rows={rows}
        rowKey={(row) => row.id}
        density="compact"
      />,
    );
    expect(screen.getByRole("columnheader", { name: "名称" })).toBeInTheDocument();
    expect(screen.getByText("Alpha")).toBeInTheDocument();
    expect(screen.queryByText("Alpha-a")).not.toBeInTheDocument();

    rerender(
      <DataTable
        caption="测试列表"
        columns={compactColumns}
        rows={rows}
        rowKey={(row) => row.id}
        density="default"
      />,
    );
    expect(screen.getByRole("columnheader", { name: "名称／ID" })).toBeInTheDocument();
    expect(screen.getByText("Alpha-a")).toBeInTheDocument();
  });
});
