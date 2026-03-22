import { describe, it, expect, beforeEach, vi, afterEach } from "vitest";
import { useToastStore, toast } from "@/stores/toast-store";

describe("useToastStore", () => {
  beforeEach(() => {
    useToastStore.setState({ toasts: [] });
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("starts with empty toasts", () => {
    expect(useToastStore.getState().toasts).toEqual([]);
  });

  it("addToast adds a toast with default type info", () => {
    useToastStore.getState().addToast("hello");
    const toasts = useToastStore.getState().toasts;
    expect(toasts).toHaveLength(1);
    expect(toasts[0].message).toBe("hello");
    expect(toasts[0].type).toBe("info");
    expect(toasts[0].id).toBeTruthy();
  });

  it("addToast respects explicit type", () => {
    useToastStore.getState().addToast("err", "error");
    expect(useToastStore.getState().toasts[0].type).toBe("error");
  });

  it("removeToast removes by id", () => {
    useToastStore.getState().addToast("one");
    useToastStore.getState().addToast("two");
    const id = useToastStore.getState().toasts[0].id;
    useToastStore.getState().removeToast(id);
    const remaining = useToastStore.getState().toasts;
    expect(remaining).toHaveLength(1);
    expect(remaining[0].message).toBe("two");
  });

  it("info toast auto-removes after 4000ms", () => {
    useToastStore.getState().addToast("auto", "info");
    expect(useToastStore.getState().toasts).toHaveLength(1);
    vi.advanceTimersByTime(4000);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("success toast auto-removes after 4000ms", () => {
    useToastStore.getState().addToast("ok", "success");
    vi.advanceTimersByTime(3999);
    expect(useToastStore.getState().toasts).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("error toast auto-removes after 10000ms", () => {
    useToastStore.getState().addToast("fail", "error");
    vi.advanceTimersByTime(9999);
    expect(useToastStore.getState().toasts).toHaveLength(1);
    vi.advanceTimersByTime(1);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("multiple toasts accumulate", () => {
    useToastStore.getState().addToast("a");
    useToastStore.getState().addToast("b");
    useToastStore.getState().addToast("c");
    expect(useToastStore.getState().toasts).toHaveLength(3);
  });

  it("each toast gets a unique id", () => {
    useToastStore.getState().addToast("a");
    useToastStore.getState().addToast("b");
    const [a, b] = useToastStore.getState().toasts;
    expect(a.id).not.toBe(b.id);
  });
});

describe("toast() helper", () => {
  beforeEach(() => {
    useToastStore.setState({ toasts: [] });
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("adds toast via helper", () => {
    toast("msg");
    expect(useToastStore.getState().toasts).toHaveLength(1);
    expect(useToastStore.getState().toasts[0].message).toBe("msg");
  });

  it("defaults to info type", () => {
    toast("x");
    expect(useToastStore.getState().toasts[0].type).toBe("info");
  });

  it("accepts explicit type", () => {
    toast("e", "error");
    expect(useToastStore.getState().toasts[0].type).toBe("error");
  });
});
