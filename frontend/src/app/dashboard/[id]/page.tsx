"use client";

import { useEffect, useState, useCallback, useRef } from "react";
import { useParams, useRouter } from "next/navigation";
import type { Dashboard, DashboardCard, SavedNote } from "@/lib/api";
import { api } from "@/lib/api";
import { Icon } from "@/components/ui/Icon";
import { toast } from "@/stores/toast-store";
import { DashboardBuilder } from "@/components/dashboards/DashboardBuilder";
import { useAuthStore } from "@/stores/auth-store";

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

function ResultTable({ data }: { data: { columns: string[]; rows: unknown[][]; total_rows: number } }) {
  return (
    <div className="overflow-x-auto max-h-64 overflow-y-auto">
      <table className="text-[10px] border-collapse w-full" aria-label="Query results">
        <thead className="sticky top-0 bg-surface-1">
          <tr className="border-b border-border-subtle">
            {data.columns.map((col) => (
              <th key={col} scope="col" className="text-left px-1.5 py-1 text-text-tertiary font-medium whitespace-nowrap">
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
        <p className="text-[9px] text-text-muted mt-1 px-1.5">
          Showing 50 of {data.total_rows} rows
        </p>
      )}
    </div>
  );
}

export default function DashboardPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const { user } = useAuthStore();
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [notes, setNotes] = useState<Map<string, SavedNote>>(new Map());
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const intervalRefs = useRef<Map<string, ReturnType<typeof setInterval>>>(new Map());

  const loadDashboard = useCallback(async () => {
    try {
      const d = await api.dashboards.get(id);
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
      const map = new Map<string, SavedNote>();
      for (const entry of noteEntries) {
        if (entry) map.set(entry[0], entry[1]);
      }
      setNotes(map);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to load dashboard", "error");
    } finally {
      setLoading(false);
    }
  }, [id]);

  useEffect(() => {
    loadDashboard();
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
        const interval = setInterval(async () => {
          try {
            const res = await api.notes.execute(card.note_id);
            if (!res.error) {
              const n = await api.notes.get(card.note_id);
              setNotes((prev) => new Map(prev).set(card.note_id, n));
            }
          } catch { /* */ }
        }, ms);
        refs.set(card.note_id, interval);
      }
    }

    return () => {
      for (const interval of refs.values()) clearInterval(interval);
      refs.clear();
    };
  }, [dashboard]);

  const handleRefreshAll = useCallback(async () => {
    if (!dashboard || refreshing) return;
    const cards = parseCards(dashboard.cards_json);
    setRefreshing(true);
    try {
      for (const card of cards) {
        try {
          await api.notes.execute(card.note_id);
          const n = await api.notes.get(card.note_id);
          setNotes((prev) => new Map(prev).set(card.note_id, n));
        } catch { /* */ }
      }
      toast("All cards refreshed", "info");
    } finally {
      setRefreshing(false);
    }
  }, [dashboard, refreshing]);

  const handleSaveEdit = (updated: Dashboard) => {
    setDashboard(updated);
    setEditing(false);
    loadDashboard();
  };

  if (loading) {
    return (
      <div className="min-h-screen bg-surface-0 flex items-center justify-center">
        <div className="w-6 h-6 border-2 border-accent border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!dashboard) {
    return (
      <div className="min-h-screen bg-surface-0 flex flex-col items-center justify-center gap-3">
        <p className="text-sm text-text-muted">Dashboard not found</p>
        <button
          onClick={() => router.push("/")}
          className="text-xs text-accent hover:text-accent-hover transition-colors"
        >
          Back to home
        </button>
      </div>
    );
  }

  const cards = parseCards(dashboard.cards_json);
  const layout = parseLayout(dashboard.layout_json);
  const isCreator = user?.id === dashboard.creator_id;

  if (editing && isCreator) {
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
          <button
            onClick={() => router.push("/")}
            aria-label="Back to home"
            className="p-1.5 rounded text-text-muted hover:text-text-secondary hover:bg-surface-2 transition-colors min-w-[36px] min-h-[36px] flex items-center justify-center"
          >
            <Icon name="arrow-left" size={16} />
          </button>
          <div>
            <h1 className="text-sm font-semibold text-text-primary">{dashboard.title}</h1>
            {dashboard.updated_at && (
              <p className="text-[10px] text-text-muted">Updated {timeAgo(dashboard.updated_at)}</p>
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
          {isCreator && (
            <button
              onClick={() => setEditing(true)}
              className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-accent text-white rounded-lg hover:bg-accent-hover transition-colors"
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
            {isCreator && (
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
              return (
                <div key={card.note_id} className="bg-surface-1 border border-border-subtle rounded-lg overflow-hidden">
                  <div className="px-4 py-3 border-b border-border-subtle flex items-center justify-between">
                    <h3 className="text-xs font-medium text-text-primary truncate">{note.title}</h3>
                    <span className="text-[10px] text-text-muted shrink-0 ml-2">
                      {timeAgo(note.last_executed_at)}
                    </span>
                  </div>
                  <div className="p-3">
                    {result ? (
                      <ResultTable data={result} />
                    ) : (
                      <p className="text-[11px] text-text-muted py-4 text-center">No data</p>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
