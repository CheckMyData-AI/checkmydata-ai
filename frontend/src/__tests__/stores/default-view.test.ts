import { describe, it, expect, beforeEach } from "vitest";
import { useAppStore } from "@/stores/app-store";

describe("default view persistence", () => {
  beforeEach(() => {
    useAppStore.setState({ lastViewByProject: {} });
  });

  it("remembers the last view per project", () => {
    useAppStore.getState().setLastView("p1", "chat");
    expect(useAppStore.getState().lastViewByProject["p1"]).toBe("chat");
    useAppStore.getState().setLastView("p2", "overview");
    expect(useAppStore.getState().lastViewByProject["p2"]).toBe("overview");
    // p1 unchanged
    expect(useAppStore.getState().lastViewByProject["p1"]).toBe("chat");
  });
});
