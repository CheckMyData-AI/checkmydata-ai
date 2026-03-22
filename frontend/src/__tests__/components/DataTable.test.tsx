import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/lib/api", () => ({
  api: {
    viz: {
      export: vi.fn().mockResolvedValue(new Blob(["data"], { type: "text/csv" })),
    },
  },
}));

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

const { DataTable } = await import("@/components/viz/DataTable");

describe("DataTable", () => {
  const baseData = {
    columns: ["id", "name", "email"],
    rows: [
      { id: 1, name: "Alice", email: "alice@test.com" },
      { id: 2, name: "Bob", email: "bob@test.com" },
    ],
    total_rows: 2,
  };

  it("renders column headers", () => {
    render(<DataTable data={baseData} />);
    expect(screen.getByText("id")).toBeTruthy();
    expect(screen.getByText("name")).toBeTruthy();
    expect(screen.getByText("email")).toBeTruthy();
  });

  it("renders row data", () => {
    render(<DataTable data={baseData} />);
    expect(screen.getByText("Alice")).toBeTruthy();
    expect(screen.getByText("Bob")).toBeTruthy();
    expect(screen.getByText("alice@test.com")).toBeTruthy();
  });

  it("shows row count", () => {
    render(<DataTable data={baseData} />);
    expect(screen.getByText("2 rows")).toBeTruthy();
  });

  it("shows singular row for 1 row", () => {
    const oneRow = { ...baseData, rows: [baseData.rows[0]], total_rows: 1 };
    render(<DataTable data={oneRow} />);
    expect(screen.getByText("1 row")).toBeTruthy();
  });

  it("shows execution time when provided", () => {
    const withTime = { ...baseData, execution_time_ms: 42.5 };
    render(<DataTable data={withTime} />);
    expect(screen.getByText(/43ms/)).toBeTruthy();
  });

  it("renders NULL for null values", () => {
    const withNull = {
      columns: ["a"],
      rows: [{ a: null }],
      total_rows: 1,
    };
    render(<DataTable data={withNull} />);
    expect(screen.getByText("NULL")).toBeTruthy();
  });

  it("renders export buttons CSV, JSON, XLSX", () => {
    render(<DataTable data={baseData} />);
    expect(screen.getByLabelText("Export as CSV")).toBeTruthy();
    expect(screen.getByLabelText("Export as JSON")).toBeTruthy();
    expect(screen.getByLabelText("Export as XLSX")).toBeTruthy();
  });

  it("handles empty columns gracefully", () => {
    const empty = { columns: [], rows: [], total_rows: 0 };
    render(<DataTable data={empty} />);
    expect(screen.getByText("0 rows")).toBeTruthy();
  });

  it("handles missing data fields gracefully", () => {
    const minimal = {};
    render(<DataTable data={minimal} />);
    expect(screen.getByText("0 rows")).toBeTruthy();
  });
});
