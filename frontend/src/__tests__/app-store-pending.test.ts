import { describe, expect, it, beforeEach } from "vitest";
import { useAppStore } from "@/stores/app-store";

describe("app-store pendingQuestion", () => {
  beforeEach(() => useAppStore.setState({ pendingQuestion: null }));

  it("defaults to null", () => {
    expect(useAppStore.getState().pendingQuestion).toBeNull();
  });

  it("setPendingQuestion sets then clears the value", () => {
    useAppStore.getState().setPendingQuestion("how many orders this month?");
    expect(useAppStore.getState().pendingQuestion).toBe("how many orders this month?");
    useAppStore.getState().setPendingQuestion(null);
    expect(useAppStore.getState().pendingQuestion).toBeNull();
  });
});
