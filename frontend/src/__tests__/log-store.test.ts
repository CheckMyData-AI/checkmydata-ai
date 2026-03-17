import { describe, it, expect, beforeEach } from "vitest";
import { useLogStore } from "@/stores/log-store";

function makeEntry(overrides: Partial<Parameters<typeof useLogStore.getState>["0"]["addEntry"]> = {}) {
  return {
    timestamp: Date.now() / 1000,
    pipeline: "index_repo",
    workflowId: "abc12345",
    step: "clone_or_pull",
    status: "completed",
    detail: "OK",
    elapsedMs: 100,
    ...overrides,
  };
}

beforeEach(() => {
  useLogStore.setState({ entries: [], isOpen: false, isConnected: false, unreadCount: 0 });
});

describe("log-store", () => {
  it("addEntry appends to entries", () => {
    useLogStore.getState().addEntry(makeEntry());
    expect(useLogStore.getState().entries).toHaveLength(1);
    expect(useLogStore.getState().entries[0].step).toBe("clone_or_pull");
  });

  it("addEntry assigns unique ids", () => {
    useLogStore.getState().addEntry(makeEntry());
    useLogStore.getState().addEntry(makeEntry());
    const ids = useLogStore.getState().entries.map((e) => e.id);
    expect(new Set(ids).size).toBe(2);
  });

  it("addEntry caps at 500 entries", () => {
    for (let i = 0; i < 510; i++) {
      useLogStore.getState().addEntry(makeEntry({ step: `step_${i}` }));
    }
    expect(useLogStore.getState().entries).toHaveLength(500);
    expect(useLogStore.getState().entries[0].step).toBe("step_10");
    expect(useLogStore.getState().entries[499].step).toBe("step_509");
  });

  it("clear empties entries and resets unread", () => {
    useLogStore.getState().addEntry(makeEntry());
    useLogStore.getState().addEntry(makeEntry());
    useLogStore.getState().clear();
    expect(useLogStore.getState().entries).toHaveLength(0);
    expect(useLogStore.getState().unreadCount).toBe(0);
  });

  it("toggle flips isOpen", () => {
    expect(useLogStore.getState().isOpen).toBe(false);
    useLogStore.getState().toggle();
    expect(useLogStore.getState().isOpen).toBe(true);
    useLogStore.getState().toggle();
    expect(useLogStore.getState().isOpen).toBe(false);
  });

  it("tracks unread count when panel is closed", () => {
    useLogStore.getState().addEntry(makeEntry());
    useLogStore.getState().addEntry(makeEntry());
    expect(useLogStore.getState().unreadCount).toBe(2);
  });

  it("resets unread when panel opens", () => {
    useLogStore.getState().addEntry(makeEntry());
    useLogStore.getState().addEntry(makeEntry());
    useLogStore.getState().toggle();
    expect(useLogStore.getState().unreadCount).toBe(0);
  });

  it("does not increment unread when panel is open", () => {
    useLogStore.getState().toggle();
    useLogStore.getState().addEntry(makeEntry());
    expect(useLogStore.getState().unreadCount).toBe(0);
  });

  it("setConnected updates connection status", () => {
    useLogStore.getState().setConnected(true);
    expect(useLogStore.getState().isConnected).toBe(true);
    useLogStore.getState().setConnected(false);
    expect(useLogStore.getState().isConnected).toBe(false);
  });
});
