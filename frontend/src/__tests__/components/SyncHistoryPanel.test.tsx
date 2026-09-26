/**
 * SCN-064 / B-28. The row comes from `fixtures/sync-history-run.json`, the same file the
 * backend test checks `SyncHistoryService` against. This test used to mock the retired
 * KnowledgeSyncRun row (`status: "success"`, `error_message`, `created_at`) — a shape the
 * API had stopped returning — so it passed while the real page showed no icon, "NaNd
 * ago", and never an error.
 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { SyncHistoryPanel } from "@/components/knowledge/SyncHistoryPanel";
import contract from "../fixtures/sync-history-run.json";

const syncHistory = vi.fn();
vi.mock("@/lib/api", () => ({
  api: { projects: { syncHistory: (...a: unknown[]) => syncHistory(...a) } },
}));

function row(overrides: Record<string, unknown> = {}) {
  const r = Object.fromEntries(
    Object.entries(contract as Record<string, unknown>).filter(([k]) => !k.startsWith("_")),
  );
  return { ...r, started_at: new Date(Date.now() - 3 * 3600_000).toISOString(), ...overrides };
}

beforeEach(() => syncHistory.mockReset());

describe("SyncHistoryPanel", () => {
  it("shows the run's own verdict, when it ran, and how many connections finished", async () => {
    syncHistory.mockResolvedValue({ runs: [row()] });
    render(<SyncHistoryPanel projectId="p1" />);
    await waitFor(() => expect(screen.getAllByText(/partial/).length).toBeGreaterThan(0));
    expect(screen.getAllByText(/3h ago/).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/1\/2 connections/).length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toMatch(/NaN|Invalid Date/);
  });

  it("shows the error a failed run recorded", async () => {
    syncHistory.mockResolvedValue({
      runs: [row({ status: "failed", outcome: "failed", error: "repo index timed out", steps: null })],
    });
    render(<SyncHistoryPanel projectId="p1" />);
    expect(await screen.findByText("repo index timed out")).toBeInTheDocument();
  });

  it("falls back to the lifecycle status when the run reported no outcome", async () => {
    syncHistory.mockResolvedValue({ runs: [row({ status: "running", outcome: null, steps: null })] });
    render(<SyncHistoryPanel projectId="p1" />);
    await waitFor(() => expect(screen.getAllByText(/running/).length).toBeGreaterThan(0));
  });

  it("labels an analytics collection as one", async () => {
    syncHistory.mockResolvedValue({
      runs: [row(), row({ id: "r2", kind: "analytics_collect", outcome: "ok", steps: null })],
    });
    render(<SyncHistoryPanel projectId="p1" />);
    expect(await screen.findByText(/Analytics collection/)).toBeInTheDocument();
  });

  it("shows empty state when there are no runs", async () => {
    syncHistory.mockResolvedValue({ runs: [] });
    render(<SyncHistoryPanel projectId="p1" />);
    expect(await screen.findByText(/No scheduled syncs yet/i)).toBeInTheDocument();
  });
});
