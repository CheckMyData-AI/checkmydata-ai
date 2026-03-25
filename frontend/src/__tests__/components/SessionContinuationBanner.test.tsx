import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SessionContinuationBanner } from "@/components/chat/SessionContinuationBanner";

describe("SessionContinuationBanner", () => {
  it("renders with message count", () => {
    render(
      <SessionContinuationBanner messageCount={42} />,
    );
    expect(screen.getByText(/42 messages summarized/)).toBeTruthy();
  });

  it("expands to show summary on click", async () => {
    const user = userEvent.setup();
    render(
      <SessionContinuationBanner
        messageCount={10}
        summaryPreview="User asked about revenue trends."
        topics={["revenue", "Q1 analysis"]}
      />,
    );

    expect(screen.queryByText("User asked about revenue trends.")).toBeNull();

    const button = screen.getByRole("button");
    await user.click(button);

    expect(screen.getByText("User asked about revenue trends.")).toBeTruthy();
    expect(screen.getByText("revenue")).toBeTruthy();
    expect(screen.getByText("Q1 analysis")).toBeTruthy();
  });

  it("collapses summary on second click", async () => {
    const user = userEvent.setup();
    render(
      <SessionContinuationBanner
        messageCount={5}
        summaryPreview="Some summary"
      />,
    );

    const button = screen.getByRole("button");
    await user.click(button);
    expect(screen.getByText("Some summary")).toBeTruthy();

    await user.click(button);
    expect(screen.queryByText("Some summary")).toBeNull();
  });

  it("renders without optional props", () => {
    render(<SessionContinuationBanner messageCount={0} />);
    expect(screen.getByText(/0 messages summarized/)).toBeTruthy();
  });
});
