import { render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { HomeAsk } from "@/components/home/HomeAsk";
import { useAppStore } from "@/stores/app-store";

const setPanel = vi.fn();
vi.mock("@/hooks/useAppPanel", () => ({
  useAppPanel: () => ({ panel: null, setPanel }),
}));

afterEach(cleanup);
beforeEach(() => {
  setPanel.mockClear();
  useAppStore.setState({
    activeProject: { id: "p1", name: "Proj" },
    activeConnection: { id: "c1", name: "db" },
    chatMode: "auto",
    pendingQuestion: null,
  } as never);
});

describe("HomeAsk", () => {
  it("hands the question to the store and switches to the chat panel", () => {
    render(<HomeAsk />);
    fireEvent.change(screen.getByLabelText(/ask your data/i), {
      target: { value: "revenue last 30 days" },
    });
    fireEvent.click(screen.getByRole("button", { name: /^ask$/i }));
    expect(useAppStore.getState().pendingQuestion).toBe("revenue last 30 days");
    expect(setPanel).toHaveBeenCalledWith("chat");
  });

  it("is disabled when there is no connection and not in knowledge mode", () => {
    useAppStore.setState({ activeConnection: null, chatMode: "auto" } as never);
    render(<HomeAsk />);
    expect(screen.getByLabelText(/ask your data/i)).toBeDisabled();
  });
});
