"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import type { Dashboard, DashboardCard, SavedNote } from "@/lib/api";
import { api } from "@/lib/api";
import { Icon } from "@/components/ui/Icon";
import { toast } from "@/stores/toast-store";
import { DashboardBuilder } from "@/components/dashboards/DashboardBuilder";
import { SectionErrorBoundary } from "@/components/ui/SectionErrorBoundary";
import { AuthGate } from "@/components/auth/AuthGate";

function parseCards(json: string | null): DashboardCard[] {
  if (!json) return [];
  try {
    return JSON.parse(json);
  } catch {
    return [];
  }
}

function parseLayout(json: string | null): { columns: number } {
  if (!json) return { columns: 2 };
  try {
    return JSON.parse(json);
  } catch {
    return { columns: 2 };
  }
}

function parseResult(json: string | null): { columns: string[]; rows: unknown[][]; total_rows: number } | null {
  if (!json) return null;
  try {
    return JSON.parse(json);
  } catch {
    return null;
  }
}

function timeAgo(iso: string | null): string {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function ageMs(iso: string | null): number | null {
  if (!iso) return null;
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return null;
  return Date.now() - t;
}

// A card that declares a refresh interval has promised how old its data may get.
// One missed tick is normal (the interval only runs while the tab is open), so the
// marker waits for the second before calling the promise broken.
const LATE_TOLERANCE = 2;

function isLate(card: DashboardCard, note: SavedNote): boolean {
  const ms = (card.refresh_interval ?? 0) * 1000;
  if (ms <= 0) return false;
  const age = ageMs(note.last_executed_at);
  return age === null || age > ms * LATE_TOLERANCE;
}

function ResultTable({ data }: { data: { columns: string[]; rows: unknown[][]; total_rows: number } }) {
  return (
    <div className="overflow-x-auto max-h-64 overflow-y-auto">
      <table className="text-kicker border-collapse w-full" aria-label="Query results">
        <thead className="sticky top-0 bg-surface-1">
          <tr className="border-b border-border-subtle">
            {data.columns.map((col, idx) => (
              <th key={`${idx}-${col}`} scope="col" className="text-left px-1.5 py-1 text-text-tertiary font-medium whitespace-nowrap">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {data.rows.slice(0, 50).map((row, i) => (
            <tr key={i} className="border-b border-border-subtle/50">
              {row.map((cell, j) => (
                <td key={j} className="px-1.5 py-0.5 text-text-secondary whitespace-nowrap max-w-[200px] truncate">
                  {cell == null ? <span className="text-text-muted italic">null</span> : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {data.total_rows > 50 && (
        <p className="text-kicker text-text-muted mt-1 px-1.5">
          Showing 50 of {data.total_rows} rows
        </p>
      )}
    </div>
  );
}

export default function DashboardPage() {
  return (
    <AuthGate>
      <DashboardPageContent />
    </AuthGate>
  );
}

function DashboardPageContent() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [notes, setNotes] = useState<Map<string, SavedNote>>(new Map());
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [cardErrors, setCardErrors] = useState<Map<string, string>>(new Map());
  const intervalRefs = useRef<Map<string, ReturnType<typeof setInterval>>>(new Map());
  // Every refresh — on open, on a tick, or from Refresh All — goes through here, so
  // a failure is recorded in one place instead of being swallowed at three call sites.
  const refreshCard = useCallback(async (noteId: string): Promise<boolean> => {
    const fail = (msg: string) => {
      setCardErrors((prev) => new Map(prev).set(noteId, msg));
      return false;
    };
    try {
      const res = await api.notes.execute(noteId);
      if (res.error) return fail(res.error);
      const n = await api.notes.get(noteId);
      setNotes((prev) => new Map(prev).set(noteId, n));
      setCardErrors((prev) => {
        if (!prev.has(noteId)) return prev;
        const next = new Map(prev);
        next.delete(noteId);
        return next;
      });
      return true;
    } catch (err) {
      return fail(err instanceof Error ? err.message : "Refresh failed");
    }
  }, []);

  // Cards that declared an interval and are already past due are run on open, one at
  // a time. `setInterval` fires first only after a full period and the load path only
  // reads the stored snapshot, so without this a card promising hourly data can show
  // a days-old number for an hour with that promise attached. Only cards that opted
  // into a schedule are touched — opening a dashboard never executes anything else.
  const refreshDue = useCallback(
    async (ids: string[], signal: { stale: boolean }) => {
      for (const id of ids) {
        if (signal.stale) return;
        await refreshCard(id);
      }
    },
    [refreshCard],
  );

  const loadDashboard = useCallback(async (signal: { stale: boolean }) => {
    try {
      const d = await api.dashboards.get(id);
      if (signal.stale) return;
      setDashboard(d);
      const cards = parseCards(d.cards_json);
      const noteIds = cards.map((c) => c.note_id);
      const noteEntries = await Promise.all(
        noteIds.map(async (nid) => {
          try {
            const n = await api.notes.get(nid);
            return [nid, n] as [string, SavedNote];
          } catch {
            return null;
          }
        }),
      );
      if (signal.stale) return;
      const map = new Map<string, SavedNote>();
      for (const entry of noteEntries) {
        if (entry) map.set(entry[0], entry[1]);
      }
      setNotes(map);
      const due = cards
        .filter((c) => {
          const ms = (c.refresh_interval ?? 0) * 1000;
          const n = map.get(c.note_id);
          if (ms <= 0 || !n) return false;
          const age = ageMs(n.last_executed_at);
          return age === null || age >= ms;
        })
        .map((c) => c.note_id);
      // Deliberately not awaited: cards paint their stored snapshot with its honest
      // age immediately, then update as each refresh lands.
      if (due.length > 0) void refreshDue(due, signal);
    } catch (err) {
      if (!signal.stale) toast(err instanceof Error ? err.message : "Failed to load dashboard", "error");
    } finally {
      if (!signal.stale) setLoading(false);
    }
  }, [id, refreshDue]);

  useEffect(() => {
    const signal = { stale: false };
    loadDashboard(signal);
    return () => { signal.stale = true; };
  }, [loadDashboard]);

  useEffect(() => {
    if (!dashboard) return;
    const cards = parseCards(dashboard.cards_json);
    const refs = intervalRefs.current;

    for (const [key, interval] of refs) {
      if (!cards.some((c) => c.note_id === key)) {
        clearInterval(interval);
        refs.delete(key);
      }
    }

    for (const card of cards) {
      const ms = (card.refresh_interval ?? 0) * 1000;
      if (ms > 0 && !refs.has(card.note_id)) {
        const interval = setInterval(() => {
          void refreshCard(card.note_id);
        }, ms);
        refs.set(card.note_id, interval);
      }
    }

    return () => {
      for (const interval of refs.values()) clearInterval(interval);
      refs.clear();
    };
  }, [dashboard, refreshCard]);

  const handleRefreshAll = useCallback(async () => {
    if (!dashboard || refreshing) return;
    const cards = parseCards(dashboard.cards_json);
    if (cards.length === 0) return;
    setRefreshing(true);
    let ok = 0;
    let fail = 0;
    try {
      for (const card of cards) {
        if (await refreshCard(card.note_id)) ok++;
        else fail++;
      }
    } finally {
      setRefreshing(false);
    }
    toast(`Refreshed: ${ok} succeeded${fail ? `, ${fail} failed` : ""}`, fail ? "error" : "info");
  }, [dashboard, refreshing, refreshCard]);

  const handleSaveEdit = (updated: Dashboard) => {
    setDashboard(updated);
    setEditing(false);
    loadDashboard({ stale: false });
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-0 flex items-center justify-center">
        <Icon name="loader" className="h-6 w-6 text-accent animate-spin" aria-hidden />
      </div>
    );
  }

  if (!dashboard) {
    return (
      <div className="min-h-screen bg-surface-0 flex flex-col items-center justify-center gap-3">
        <p className="text-sm text-text-muted">Dashboard not found</p>
        <button
          onClick={() => router.push("/app")}
          className="text-xs text-accent hover:text-accent-hover transition-colors"
        >
          Back to app
        </button>
      </div>
    );
  }

  const cards = parseCards(dashboard.cards_json);
  const layout = parseLayout(dashboard.layout_json);
  const canEditDashboard = dashboard.user_role === "owner" || dashboard.user_role === "editor";

  if (editing && canEditDashboard) {
    return (
      <div className="min-h-screen bg-surface-0 p-6">
        <DashboardBuilder
          dashboard={dashboard}
          onSave={handleSaveEdit}
          onCancel={() => setEditing(false)}
        />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-surface-0 flex flex-col">
      <header className="shrink-0 border-b border-border-subtle px-6 py-3 flex items-center justify-between bg-surface-0">
        <div className="flex items-center gap-3">
          <Link
            href="/app"
            className="p-1.5 rounded text-text-muted hover:text-text-secondary hover:bg-surface-2 transition-colors min-w-[36px] min-h-[36px] flex items-center justify-center"
            aria-label="Back to app"
          >
            <Icon name="arrow-left" size={16} />
          </Link>
          <div>
            <h1 className="text-sm font-semibold text-text-primary">{dashboard.title}</h1>
            {dashboard.updated_at && (
              <p className="text-kicker text-text-muted">Updated {timeAgo(dashboard.updated_at)}</p>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleRefreshAll}
            disabled={refreshing}
            className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-surface-2 text-text-secondary rounded-lg hover:bg-surface-3 hover:text-text-primary disabled:opacity-40 transition-colors"
          >
            <Icon name="refresh-cw" size={12} className={refreshing ? "animate-spin" : ""} />
            Refresh All
          </button>
          {canEditDashboard && (
            <button
              onClick={() => setEditing(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-primary text-primary-foreground rounded-lg hover:bg-primary/92 transition-colors"
            >
              <Icon name="edit" size={12} />
              Edit
            </button>
          )}
        </div>
      </header>

      <div className="flex-1 p-6">
        {cards.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-20">
            <Icon name="layout" size={32} className="text-text-muted mb-3" />
            <p className="text-sm text-text-muted">This dashboard has no cards yet.</p>
            {canEditDashboard && (
              <button
                onClick={() => setEditing(true)}
                className="mt-3 text-xs text-accent hover:text-accent-hover transition-colors"
              >
                Add cards
              </button>
            )}
          </div>
        ) : (
          <div
            className="grid gap-4"
            style={{ gridTemplateColumns: `repeat(${layout.columns}, minmax(0, 1fr))` }}
          >
            {cards.map((card) => {
              const note = notes.get(card.note_id);
              if (!note) {
                return (
                  <div key={card.note_id} className="bg-surface-1 border border-border-subtle rounded-lg p-4">
                    <p className="text-xs text-text-muted italic">Note not found</p>
                  </div>
                );
              }
              const result = parseResult(note.last_result_json);
              const late = isLate(card, note);
              const cardError = cardErrors.get(card.note_id);
              return (
                <SectionErrorBoundary key={card.note_id} sectionName={note.title}>
                  <div
                    data-note-id={card.note_id}
                    className="bg-surface-1 border border-border-subtle rounded-lg overflow-hidden"
                  >
                    <div className="px-4 py-3 border-b border-border-subtle flex items-center justify-between">
                      <h3 className="text-xs font-medium text-text-primary truncate">{note.title}</h3>
                      {/* The dashboard header says "Updated …" about the dashboard itself.
                          A bare relative age here reads as the same thing, so this one
                          names what it measures: when the data was produced. */}
                      <span className="text-kicker text-text-muted shrink-0 ml-2">
                        {note.last_executed_at
                          ? `Data from ${timeAgo(note.last_executed_at)}`
                          : "Never run"}
                      </span>
                    </div>
                    {late && (
                      <p className="flex items-start gap-1.5 px-4 py-2 text-kicker text-warning bg-warning-muted/12 border-b border-border-subtle">
                        <Icon name="alert-triangle" size={11} className="shrink-0 mt-px" aria-hidden />
                        <span>
                          This card is not refreshing on its schedule — the figures below are
                          older than it promises.
                        </span>
                      </p>
                    )}
                    {cardError && (
                      <p className="flex items-start gap-1.5 px-4 py-2 text-kicker text-danger border-b border-border-subtle">
                        <Icon name="alert-triangle" size={11} className="shrink-0 mt-px" aria-hidden />
                        <span>Last refresh failed: {cardError}</span>
                      </p>
                    )}
                    <div className="p-3">
                      {result ? (
                        <ResultTable data={result} />
                      ) : (
                        <p className="text-meta text-text-muted py-4 text-center">No data</p>
                      )}
                    </div>
                  </div>
                </SectionErrorBoundary>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
