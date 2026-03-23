"use client";

import { useState, useEffect, useCallback } from "react";
import type { Dashboard, DashboardCard, SavedNote } from "@/lib/api";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { toast } from "@/stores/toast-store";
import { Icon } from "@/components/ui/Icon";

function parseCards(json: string | null): DashboardCard[] {
  if (!json) return [];
  try {
    return JSON.parse(json);
  } catch {
    return [];
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

interface DashboardBuilderProps {
  dashboard?: Dashboard | null;
  onSave?: (dashboard: Dashboard) => void;
  onCancel?: () => void;
}

export function DashboardBuilder({ dashboard, onSave, onCancel }: DashboardBuilderProps) {
  const activeProject = useAppStore((s) => s.activeProject);
  const [title, setTitle] = useState(dashboard?.title ?? "");
  const [cards, setCards] = useState<DashboardCard[]>(parseCards(dashboard?.cards_json ?? null));
  const [columns, setColumns] = useState<2 | 3>(2);
  const [saving, setSaving] = useState(false);
  const [notes, setNotes] = useState<SavedNote[]>([]);
  const [showPicker, setShowPicker] = useState(false);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    if (!activeProject) return;
    let cancelled = false;
    api.notes
      .list(activeProject.id, "all")
      .then((data) => { if (!cancelled) setNotes(data); })
      .catch((err) => { if (!cancelled) toast(err instanceof Error ? err.message : "Failed to load notes", "error"); });
    return () => { cancelled = true; };
  }, [activeProject]);

  const noteMap = Object.fromEntries(notes.map((n) => [n.id, n]));

  const handleAddCard = (noteId: string) => {
    if (cards.some((c) => c.note_id === noteId)) {
      toast("Note already on dashboard", "info");
      return;
    }
    setCards((prev) => [...prev, { note_id: noteId }]);
    setShowPicker(false);
  };

  const handleRemoveCard = (noteId: string) => {
    setCards((prev) => prev.filter((c) => c.note_id !== noteId));
  };

  const handleSave = async () => {
    if (!activeProject) return;
    if (!title.trim()) {
      toast("Title is required", "error");
      return;
    }
    setSaving(true);
    try {
      const layoutJson = JSON.stringify({ columns });
      const cardsJson = JSON.stringify(cards);

      if (dashboard) {
        const updated = await api.dashboards.update(dashboard.id, {
          title: title.trim(),
          layout_json: layoutJson,
          cards_json: cardsJson,
        });
        toast("Dashboard saved", "info");
        onSave?.(updated);
      } else {
        const created = await api.dashboards.create({
          project_id: activeProject.id,
          title: title.trim(),
          layout_json: layoutJson,
          cards_json: cardsJson,
        });
        toast("Dashboard created", "info");
        onSave?.(created);
      }
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to save", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleRefreshAll = useCallback(async () => {
    const noteIds = cards.map((c) => c.note_id).filter((id) => noteMap[id]?.connection_id);
    if (!noteIds.length) return;
    setRefreshing(true);
    let ok = 0;
    let fail = 0;
    for (const id of noteIds) {
      try {
        const res = await api.notes.execute(id);
        if (res.error) fail++;
        else ok++;
      } catch {
        fail++;
      }
    }
    setRefreshing(false);
    if (activeProject) {
      api.notes.list(activeProject.id, "all").then(setNotes).catch((err) => toast(err instanceof Error ? err.message : "Failed to reload notes", "error"));
    }
    toast(`Refreshed: ${ok} succeeded${fail ? `, ${fail} failed` : ""}`, fail ? "error" : "info");
  }, [cards, noteMap, activeProject]);

  const availableNotes = notes.filter((n) => !cards.some((c) => c.note_id === n.id));

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-3">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Dashboard title..."
          className="flex-1 text-sm bg-surface-1 border border-border-default rounded-lg px-3 py-2 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent"
        />
        <div className="flex items-center gap-1 bg-surface-1 border border-border-subtle rounded-lg p-0.5">
          {([2, 3] as const).map((n) => (
            <button
              key={n}
              onClick={() => setColumns(n)}
              className={`px-2 py-1 text-[10px] font-medium rounded transition-colors ${
                columns === n
                  ? "bg-accent-muted text-accent"
                  : "text-text-muted hover:text-text-secondary"
              }`}
            >
              {n}-col
            </button>
          ))}
        </div>
      </div>

      <div className="flex items-center gap-2">
        <button
          onClick={() => setShowPicker(true)}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-surface-2 text-text-secondary rounded-lg hover:bg-surface-3 hover:text-text-primary transition-colors"
        >
          <Icon name="plus" size={12} />
          Add Card
        </button>
        <button
          onClick={handleRefreshAll}
          disabled={refreshing || cards.length === 0}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs bg-surface-2 text-text-secondary rounded-lg hover:bg-surface-3 hover:text-text-primary disabled:opacity-40 transition-colors"
        >
          <Icon name="refresh-cw" size={12} className={refreshing ? "animate-spin" : ""} />
          Refresh All
        </button>
        <div className="flex-1" />
        {onCancel && (
          <button
            onClick={onCancel}
            className="px-3 py-1.5 text-xs text-text-muted hover:text-text-secondary transition-colors"
          >
            Cancel
          </button>
        )}
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-1.5 px-4 py-1.5 text-xs bg-accent text-white rounded-lg hover:bg-accent-hover disabled:opacity-50 transition-colors"
        >
          <Icon name="save" size={12} />
          {saving ? "Saving..." : "Save Dashboard"}
        </button>
      </div>

      {/* Card picker modal */}
      {showPicker && (
        <div className="border border-border-default rounded-lg bg-surface-1 p-3 space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-text-primary">Select a saved query</span>
            <button
              onClick={() => setShowPicker(false)}
              aria-label="Close picker"
              className="p-1.5 rounded text-text-muted hover:text-text-secondary hover:bg-surface-2 transition-colors min-w-[28px] min-h-[28px] flex items-center justify-center"
            >
              <Icon name="x" size={12} />
            </button>
          </div>
          {availableNotes.length === 0 ? (
            <p className="text-[11px] text-text-muted py-2">No more queries available to add.</p>
          ) : (
            <div className="max-h-48 overflow-y-auto space-y-1">
              {availableNotes.map((n) => (
                <button
                  key={n.id}
                  onClick={() => handleAddCard(n.id)}
                  className="w-full text-left px-2.5 py-1.5 rounded text-xs text-text-secondary hover:bg-surface-2 hover:text-text-primary transition-colors truncate"
                >
                  {n.title}
                </button>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Cards grid */}
      {cards.length === 0 ? (
        <div className="text-center py-12 px-4 border border-dashed border-border-subtle rounded-lg">
          <Icon name="layout" size={24} className="text-text-muted mx-auto mb-2" />
          <p className="text-xs text-text-muted">
            Add cards from your saved queries to build a dashboard.
          </p>
        </div>
      ) : (
        <div
          className="grid gap-3 grid-cols-1 md:grid-cols-2"
          style={columns > 2 ? { gridTemplateColumns: `repeat(${columns}, minmax(0, 1fr))` } : undefined}
        >
          {cards.map((card) => {
            const note = noteMap[card.note_id];
            if (!note) {
              return (
                <div
                  key={card.note_id}
                  className="bg-surface-1 border border-dashed border-border-subtle rounded-lg p-3 space-y-2 opacity-60"
                >
                  <div className="flex items-center justify-between">
                    <p className="text-xs text-text-muted italic truncate flex-1">
                      This query was deleted
                    </p>
                    <button
                      onClick={() => handleRemoveCard(card.note_id)}
                      title="Remove card"
                      className="p-1 rounded text-text-muted hover:text-error hover:bg-red-900/20 transition-colors shrink-0"
                    >
                      <Icon name="x" size={11} />
                    </button>
                  </div>
                </div>
              );
            }
            let viz = null;
            try { viz = note.visualization_json ? JSON.parse(note.visualization_json) : null; } catch { /* malformed viz JSON */ }
            return (
              <div
                key={card.note_id}
                className="bg-surface-1 border border-border-subtle rounded-lg p-3 space-y-2"
              >
                <div className="flex items-center justify-between">
                  <h4 className="text-xs font-medium text-text-primary truncate flex-1">
                    {note.title}
                  </h4>
                  <button
                    onClick={() => handleRemoveCard(card.note_id)}
                    title="Remove card"
                    className="p-1 rounded text-text-muted hover:text-error hover:bg-red-900/20 transition-colors shrink-0"
                  >
                    <Icon name="x" size={11} />
                  </button>
                </div>
                <div className="flex items-center gap-2 text-[10px] text-text-muted">
                  {viz?.type && viz.type !== "text" && (
                    <span className="px-1 py-0.5 rounded bg-surface-2">{viz.type as string}</span>
                  )}
                  <span>Last: {timeAgo(note.last_executed_at)}</span>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
