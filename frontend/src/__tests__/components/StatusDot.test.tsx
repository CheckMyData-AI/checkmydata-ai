import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";
import { StatusDot } from "@/components/ui/StatusDot";

describe("StatusDot", () => {
  it("renders with success status", () => {
    render(<StatusDot status="success" />);
    const dot = screen.getByRole("img", { name: "Connected" });
    expect(dot).toBeInTheDocument();
    expect(dot.className).toContain("bg-success");
  });

  it("renders with error status", () => {
    render(<StatusDot status="error" />);
    const dot = screen.getByRole("img", { name: "Error" });
    expect(dot).toBeInTheDocument();
    expect(dot.className).toContain("bg-error");
  });

  it("renders with warning status", () => {
    render(<StatusDot status="warning" />);
    const dot = screen.getByRole("img", { name: "Warning" });
    expect(dot).toBeInTheDocument();
  });

  it("renders idle status", () => {
    render(<StatusDot status="idle" />);
    const dot = screen.getByRole("img", { name: "Not checked" });
    expect(dot).toBeInTheDocument();
  });

  it("renders loading with pulse animation", () => {
    render(<StatusDot status="loading" />);
    const dot = screen.getByRole("img", { name: "Loading" });
    expect(dot.className).toContain("animate-pulse-dot");
  });

  it("respects custom title", () => {
    render(<StatusDot status="success" title="Custom title" />);
    const dot = screen.getByRole("img", { name: "Custom title" });
    expect(dot).toBeInTheDocument();
  });

  it("uses md size when specified", () => {
    render(<StatusDot status="info" size="md" />);
    const dot = screen.getByRole("img", { name: "Info" });
    expect(dot.className).toContain("w-2");
  });

  it("uses sm size by default", () => {
    render(<StatusDot status="info" />);
    const dot = screen.getByRole("img", { name: "Info" });
    expect(dot.className).toContain("w-1.5");
  });

  it("does not pulse by default for non-loading status", () => {
    render(<StatusDot status="success" />);
    const dot = screen.getByRole("img", { name: "Connected" });
    expect(dot.className).not.toContain("animate-pulse-dot");
  });

  it("respects explicit pulse override", () => {
    render(<StatusDot status="success" pulse={true} />);
    const dot = screen.getByRole("img", { name: "Connected" });
    expect(dot.className).toContain("animate-pulse-dot");
  });
});
