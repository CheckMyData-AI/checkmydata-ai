import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useConfirmStore, confirmAction, ConfirmModal } from "@/components/ui/ConfirmModal";

describe("useConfirmStore", () => {
  beforeEach(() => {
    useConfirmStore.setState({
      open: false,
      message: "",
      destructive: true,
      detail: null,
      severity: "normal",
      confirmText: null,
      resolve: null,
    });
  });

  it("starts closed", () => {
    expect(useConfirmStore.getState().open).toBe(false);
  });

  it("show() opens with message", async () => {
    const p = useConfirmStore.getState().show("Delete?");
    expect(useConfirmStore.getState().open).toBe(true);
    expect(useConfirmStore.getState().message).toBe("Delete?");
    useConfirmStore.getState().close(false);
    expect(await p).toBe(false);
  });

  it("show() applies options", async () => {
    const p = useConfirmStore
      .getState()
      .show("Sure?", { destructive: false, detail: "detail", severity: "warning", confirmText: "yes" });
    const s = useConfirmStore.getState();
    expect(s.destructive).toBe(false);
    expect(s.detail).toBe("detail");
    expect(s.severity).toBe("warning");
    expect(s.confirmText).toBe("yes");
    s.close(true);
    expect(await p).toBe(true);
  });

  it("close(true) resolves true and resets", async () => {
    const p = useConfirmStore.getState().show("Ok?");
    useConfirmStore.getState().close(true);
    expect(await p).toBe(true);
    expect(useConfirmStore.getState().open).toBe(false);
    expect(useConfirmStore.getState().message).toBe("");
  });

  it("close(false) resolves false", async () => {
    const p = useConfirmStore.getState().show("Cancel?");
    useConfirmStore.getState().close(false);
    expect(await p).toBe(false);
  });

  it("opening a new dialog resolves previous with false", async () => {
    const p1 = useConfirmStore.getState().show("First?");
    const p2 = useConfirmStore.getState().show("Second?");
    expect(await p1).toBe(false);
    useConfirmStore.getState().close(true);
    expect(await p2).toBe(true);
  });
});

describe("confirmAction helper", () => {
  beforeEach(() => {
    useConfirmStore.setState({
      open: false,
      message: "",
      destructive: true,
      detail: null,
      severity: "normal",
      confirmText: null,
      resolve: null,
    });
  });

  it("calls show on the store", async () => {
    const p = confirmAction("Proceed?");
    expect(useConfirmStore.getState().open).toBe(true);
    useConfirmStore.getState().close(true);
    expect(await p).toBe(true);
  });
});

describe("ConfirmModal component", () => {
  beforeEach(() => {
    useConfirmStore.setState({
      open: false,
      message: "",
      destructive: true,
      detail: null,
      severity: "normal",
      confirmText: null,
      resolve: null,
    });
  });

  it("renders nothing when closed", () => {
    const { container } = render(<ConfirmModal />);
    expect(container.innerHTML).toBe("");
  });

  it("renders message when open", () => {
    useConfirmStore.setState({ open: true, message: "Are you sure?", resolve: vi.fn() });
    render(<ConfirmModal />);
    expect(screen.getByText("Are you sure?")).toBeTruthy();
  });

  it("renders detail when provided", () => {
    useConfirmStore.setState({
      open: true,
      message: "Delete?",
      detail: "Cannot undo",
      resolve: vi.fn(),
    });
    render(<ConfirmModal />);
    expect(screen.getByText("Cannot undo")).toBeTruthy();
  });

  it("Cancel button calls close(false)", async () => {
    const resolveFn = vi.fn();
    useConfirmStore.setState({ open: true, message: "Test", resolve: resolveFn });
    render(<ConfirmModal />);
    await userEvent.click(screen.getByText("Cancel"));
    expect(resolveFn).toHaveBeenCalledWith(false);
  });

  it("Confirm button calls close(true)", async () => {
    const resolveFn = vi.fn();
    useConfirmStore.setState({ open: true, message: "Test", resolve: resolveFn });
    render(<ConfirmModal />);
    await userEvent.click(screen.getByText("Confirm"));
    expect(resolveFn).toHaveBeenCalledWith(true);
  });

  it("shows warning icon when severity=warning", () => {
    useConfirmStore.setState({
      open: true,
      message: "Watch out",
      severity: "warning",
      resolve: vi.fn(),
    });
    const { container } = render(<ConfirmModal />);
    const svg = container.querySelector("svg");
    expect(svg).toBeTruthy();
    expect(svg?.className.baseVal).toContain("text-yellow-400");
  });

  it("shows critical icon when severity=critical", () => {
    useConfirmStore.setState({
      open: true,
      message: "Danger",
      severity: "critical",
      resolve: vi.fn(),
    });
    const { container } = render(<ConfirmModal />);
    const svg = container.querySelector("svg");
    expect(svg?.className.baseVal).toContain("text-red-400");
  });

  it("Confirm disabled when confirmText required and not typed", () => {
    useConfirmStore.setState({
      open: true,
      message: "Delete?",
      confirmText: "DELETE",
      resolve: vi.fn(),
    });
    render(<ConfirmModal />);
    const btn = screen.getByText("Confirm");
    expect(btn).toHaveProperty("disabled", true);
  });

  it("Confirm enabled after typing confirmText", async () => {
    useConfirmStore.setState({
      open: true,
      message: "Delete?",
      confirmText: "DELETE",
      resolve: vi.fn(),
    });
    render(<ConfirmModal />);
    const input = screen.getByPlaceholderText("DELETE");
    await userEvent.type(input, "DELETE");
    const btn = screen.getByText("Confirm");
    expect(btn).toHaveProperty("disabled", false);
  });

  it("destructive mode shows red confirm button", () => {
    useConfirmStore.setState({
      open: true,
      message: "Delete?",
      destructive: true,
      resolve: vi.fn(),
    });
    render(<ConfirmModal />);
    const btn = screen.getByText("Confirm");
    expect(btn.className).toContain("bg-red-600");
  });

  it("non-destructive mode shows accent confirm button", () => {
    useConfirmStore.setState({
      open: true,
      message: "Continue?",
      destructive: false,
      resolve: vi.fn(),
    });
    render(<ConfirmModal />);
    const btn = screen.getByText("Confirm");
    expect(btn.className).toContain("bg-accent");
  });
});
