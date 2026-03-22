import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("@/stores/app-store", () => ({
  useAppStore: vi.fn((sel: (s: Record<string, unknown>) => unknown) =>
    sel({
      activeProject: { id: "p1", name: "Test" },
      connections: [
        { id: "c1", name: "DB1", db_type: "postgres" },
        { id: "c2", name: "DB2", db_type: "mysql" },
      ],
    }),
  ),
}));

vi.mock("@/stores/notes-store", () => ({
  useNotesStore: vi.fn((sel: (s: Record<string, unknown>) => unknown) =>
    sel({ notes: [] }),
  ),
}));

vi.mock("@/lib/api", () => ({
  api: {
    batch: {
      execute: vi.fn().mockResolvedValue({ batch_id: "b1" }),
      get: vi.fn().mockResolvedValue({ status: "completed", results_json: "[]" }),
    },
  },
}));

vi.mock("@/stores/toast-store", () => ({
  toast: vi.fn(),
}));

vi.mock("@/components/ui/Icon", () => ({
  Icon: (p: { name: string }) => <span data-testid={`icon-${p.name}`} />,
}));

vi.mock("./BatchResults", () => ({
  BatchResults: () => <div data-testid="batch-results" />,
}));

const { BatchRunner } = await import("@/components/batch/BatchRunner");

describe("BatchRunner", () => {
  const onClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders header", () => {
    render(<BatchRunner onClose={onClose} />);
    expect(screen.getByText("Batch Query Runner")).toBeTruthy();
  });

  it("renders batch title input with default value", () => {
    render(<BatchRunner onClose={onClose} />);
    const input = screen.getByPlaceholderText("Batch title...");
    expect((input as HTMLInputElement).value).toBe("Batch Run");
  });

  it("renders connection selector with options", () => {
    render(<BatchRunner onClose={onClose} />);
    expect(screen.getByText("DB1 (postgres)")).toBeTruthy();
    expect(screen.getByText("DB2 (mysql)")).toBeTruthy();
  });

  it("shows Add Query button", () => {
    render(<BatchRunner onClose={onClose} />);
    expect(screen.getByText("Add Query")).toBeTruthy();
  });

  it("shows From Saved Notes button", () => {
    render(<BatchRunner onClose={onClose} />);
    expect(screen.getByText("From Saved Notes")).toBeTruthy();
  });

  it("has a default empty query row", () => {
    render(<BatchRunner onClose={onClose} />);
    const textarea = screen.getByPlaceholderText("SELECT ...");
    expect(textarea).toBeTruthy();
  });

  it("Run All button shows count of valid queries", () => {
    render(<BatchRunner onClose={onClose} />);
    expect(screen.getByText("Run All (0)")).toBeTruthy();
  });

  it("Run All enabled after entering a query", async () => {
    render(<BatchRunner onClose={onClose} />);
    const textarea = screen.getByPlaceholderText("SELECT ...");
    await userEvent.type(textarea, "SELECT 1");
    expect(screen.getByText("Run All (1)")).toBeTruthy();
  });

  it("Add Query adds another query row", async () => {
    render(<BatchRunner onClose={onClose} />);
    await userEvent.click(screen.getByText("Add Query"));
    const textareas = screen.getAllByPlaceholderText("SELECT ...");
    expect(textareas.length).toBe(2);
  });

  it("close button calls onClose", async () => {
    render(<BatchRunner onClose={onClose} />);
    const closeBtn = screen.getByTestId("icon-x").closest("button");
    if (closeBtn) await userEvent.click(closeBtn);
    expect(onClose).toHaveBeenCalled();
  });

  it("pre-selects connectionId when provided", () => {
    render(<BatchRunner onClose={onClose} connectionId="c2" />);
    const select = screen.getByDisplayValue("DB2 (mysql)");
    expect(select).toBeTruthy();
  });
});
