import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { VerificationBadge } from "@/components/chat/VerificationBadge";

describe("VerificationBadge", () => {
  it("renders 'Verified' for verified status", () => {
    render(<VerificationBadge status="verified" />);
    expect(screen.getByText("Verified")).toBeTruthy();
  });

  it("renders 'Unverified' for unverified status", () => {
    render(<VerificationBadge status="unverified" />);
    expect(screen.getByText("Unverified")).toBeTruthy();
  });

  it("renders 'Flagged' for flagged status", () => {
    render(<VerificationBadge status="flagged" />);
    expect(screen.getByText("Flagged")).toBeTruthy();
  });

  it("has correct styling for verified", () => {
    const { container } = render(<VerificationBadge status="verified" />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain("emerald");
  });

  it("has correct styling for flagged", () => {
    const { container } = render(<VerificationBadge status="flagged" />);
    const badge = container.firstChild as HTMLElement;
    expect(badge.className).toContain("red");
  });
});
