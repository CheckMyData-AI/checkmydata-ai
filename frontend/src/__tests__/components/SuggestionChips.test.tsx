import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("SuggestionChips and FollowupChips", async () => {
  const { SuggestionChips, FollowupChips } = await import(
    "@/components/chat/SuggestionChips"
  );

  it("shows loading skeletons when loading=true", () => {
    const { container } = render(
      <SuggestionChips loading suggestions={[]} onSelect={vi.fn()} />,
    );
    const pulse = container.querySelector(".animate-pulse");
    expect(pulse).toBeInTheDocument();
    expect(pulse?.children.length).toBe(3);
  });

  it("renders suggestion text", () => {
    render(
      <SuggestionChips
        suggestions={[{ text: "Try this query", source: "schema" }]}
        onSelect={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Try this query" })).toBeInTheDocument();
  });

  it("truncates long text to 60 chars", () => {
    const long = "a".repeat(61);
    const expected = "a".repeat(57) + "...";
    render(
      <SuggestionChips suggestions={[{ text: long, source: "schema" }]} onSelect={vi.fn()} />,
    );
    expect(screen.getByRole("button")).toHaveTextContent(expected);
  });

  it("calls onSelect when chip clicked", async () => {
    const onSelect = vi.fn();
    render(
      <SuggestionChips
        suggestions={[{ text: "pick me", source: "schema" }]}
        onSelect={onSelect}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "pick me" }));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith("pick me");
  });

  it("returns null when suggestions empty", () => {
    const { container } = render(
      <SuggestionChips suggestions={[]} onSelect={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("renders followup buttons", () => {
    render(
      <FollowupChips followups={["More A", "More B"]} onSelect={vi.fn()} />,
    );
    expect(screen.getByRole("button", { name: "More A" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "More B" })).toBeInTheDocument();
  });

  it("calls onSelect when clicked", async () => {
    const onSelect = vi.fn();
    render(<FollowupChips followups={["next"]} onSelect={onSelect} />);
    await userEvent.click(screen.getByRole("button", { name: "next" }));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(onSelect).toHaveBeenCalledWith("next");
  });

  it("returns null when followups empty", () => {
    const { container } = render(
      <FollowupChips followups={[]} onSelect={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
