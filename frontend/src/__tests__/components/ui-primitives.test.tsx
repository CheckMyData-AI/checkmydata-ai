import { describe, expect, it, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";

import { ProgressBar } from "@/components/ui/ProgressBar";
import { StatusBadge } from "@/components/ui/StatusBadge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { StageRow } from "@/components/chat/StageRow";
import { CheckpointCard } from "@/components/chat/CheckpointCard";

describe("ProgressBar", () => {
  it("clamps value and exposes aria attributes", () => {
    render(<ProgressBar value={3} max={5} label="Stage progress" />);
    const bar = screen.getByRole("progressbar");
    expect(bar).toHaveAttribute("aria-valuenow", "3");
    expect(bar).toHaveAttribute("aria-valuemax", "5");
  });

  it("handles zero max safely", () => {
    render(<ProgressBar value={1} max={0} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuemax", "1");
  });
});

describe("StatusBadge", () => {
  it("renders accessible label for passed status", () => {
    render(<StatusBadge status="passed" />);
    expect(screen.getByRole("img", { name: /passed/i })).toBeInTheDocument();
  });

  it("renders loader for running status", () => {
    render(<StatusBadge status="running" />);
    expect(screen.getByRole("img", { name: /running/i })).toBeInTheDocument();
  });
});

describe("Button", () => {
  it("fires click and supports variants", () => {
    const onClick = vi.fn();
    render(
      <Button variant="primary" onClick={onClick}>
        Continue
      </Button>,
    );
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(onClick).toHaveBeenCalledOnce();
  });
});

describe("Input", () => {
  it("marks invalid state for assistive tech", () => {
    render(<Input invalid aria-label="Project name" />);
    expect(screen.getByRole("textbox")).toHaveAttribute("aria-invalid", "true");
  });
});

describe("StageRow", () => {
  it("shows description with line clamp when expanded", () => {
    render(
      <StageRow
        stage={{
          id: "s1",
          description: "Load customer orders from the warehouse database for analysis",
          tool: "query_database",
          checkpoint: false,
          status: "running",
        }}
        index={0}
        isCurrent
        expanded
        showConnector={false}
      />,
    );
    expect(screen.getByText(/Load customer orders/)).toBeInTheDocument();
  });
});

describe("CheckpointCard", () => {
  it("renders preview table and action buttons", () => {
    const onContinue = vi.fn();
    render(
      <CheckpointCard
        stage={{
          id: "s1",
          description: "Review query output",
          tool: "query_database",
          checkpoint: true,
          status: "checkpoint",
        }}
        preview={{
          columns: ["id", "name"],
          sampleRows: [[1, "Ada"]],
        }}
        onContinue={onContinue}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /continue pipeline/i }));
    expect(onContinue).toHaveBeenCalledOnce();
    expect(screen.getByText("Ada")).toBeInTheDocument();
  });
});
