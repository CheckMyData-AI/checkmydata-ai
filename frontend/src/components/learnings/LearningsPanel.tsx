"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type AgentLearningDTO } from "@/lib/api";
import { Icon } from "@/components/ui/Icon";
import { confirmAction } from "@/components/ui/ConfirmModal";
import { toast } from "@/stores/toast-store";
import { usePermission } from "@/hooks/usePermission";

const CATEGORY_LABELS: Record<string, string> = {
  table_preference: "Table Preferences",
  column_usage: "Column Usage",
  data_format: "Data Formats",
  query_pattern: "Query Patterns",
  schema_gotcha: "Schema Gotchas",
  performance_hint: "Performance Hints",
};

const CATEGORY_COLORS: Record<string, string> = {
  table_preference: "text-purple-400 bg-purple-900/20",
  column_usage: "text-blue-400 bg-blue-900/20",
  data_format: "text-emerald-400 bg-emerald-900/20",
  query_pattern: "text-amber-400 bg-amber-900/20",
  schema_gotcha: "text-red-400 bg-red-900/20",
  performance_hint: "text-cyan-400 bg-cyan-900/20",
};

type SortKey = "confidence" | "date" | "confirmed" | "applied";

interface LearningsPanelProps {
  connectionId: string;
  onClose: () => void;
  onCountChange?: (count: number) => void;
}

export function LearningsPanel({ connectionId, onClose, onCountChange }: LearningsPanelProps) {
  const { canDelete } = usePermission();
  const [learnings, setLearnings] = useState<AgentLearningDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editLesson, setEditLesson] = useState("");
  const [filterCategory, setFilterCategory] = useState<string | null>(null);
  const [sortKey, setSortKey] = useState<SortKey>("confidence");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.connections
      .listLearnings(connectionId)
      .then((data) => { if (!cancelled) setLearnings(data); })
      .catch(() => { if (!cancelled) toast("Failed to load learnings", "error"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [connectionId]);

  useEffect(() => {
    onCountChange?.(learnings.filter((l) => l.is_active).length);
  }, [learnings, onCountChange]);

  const handleDelete = async (learningId: string) => {
    if (!(await confirmAction("Delete this learning?"))) return;
    try {
      await api.connections.deleteLearning(connectionId, learningId);
      setLearnings((prev) => prev.filter((l) => l.id !== learningId));
      toast("Learning deleted", "success");
    } catch {
      toast("Failed to delete", "error");
    }
  };

  const handleToggleActive = async (l: AgentLearningDTO) => {
    try {
      await api.connections.updateLearning(connectionId, l.id, { is_active: !l.is_active });
      setLearnings((prev) =>
        prev.map((x) => (x.id === l.id ? { ...x, is_active: !x.is_active } : x))
      );
    } catch {
      toast("Failed to update", "error");
    }
  };

  const handleSaveEdit = async (learningId: string) => {
    if (!editLesson.trim()) return;
    try {
      await api.connections.updateLearning(connectionId, learningId, { lesson: editLesson.trim() });
      setLearnings((prev) =>
        prev.map((l) => (l.id === learningId ? { ...l, lesson: editLesson.trim() } : l))
      );
      setEditingId(null);
      toast("Learning updated", "success");
    } catch {
      toast("Failed to update", "error");
    }
  };

  const handleRecompile = async () => {
    try {
      await api.connections.recompileLearnings(connectionId);
      toast("Learnings prompt recompiled", "success");
    } catch {
      toast("Failed to recompile", "error");
    }
  };

  const handleClearAll = async () => {
    if (
      !(await confirmAction("Clear ALL learnings for this connection?", {
        severity: "critical",
        detail:
          "The agent will lose all accumulated knowledge about your database patterns. This cannot be undone.",
        confirmText: "DELETE",
      }))
    ) return;
    try {
      const result = await api.connections.clearLearnings(connectionId);
      setLearnings([]);
      toast(`Cleared ${result.deleted} learnings`, "success");
    } catch {
      toast("Failed to clear", "error");
    }
  };

  const sortFn = useCallback(
    (a: AgentLearningDTO, b: AgentLearningDTO) => {
      switch (sortKey) {
        case "confidence":
          return b.confidence - a.confidence;
        case "date":
          return new Date(b.created_at ?? 0).getTime() - new Date(a.created_at ?? 0).getTime();
        case "confirmed":
          return b.times_confirmed - a.times_confirmed;
        case "applied":
          return b.times_applied - a.times_applied;
        default:
          return 0;
      }
    },
    [sortKey]
  );

  const filtered = useMemo(() => {
    const base = filterCategory ? learnings.filter((l) => l.category === filterCategory) : learnings;
    return [...base].sort(sortFn);
  }, [learnings, filterCategory, sortFn]);

  const categoryCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const l of learnings) {
      counts[l.category] = (counts[l.category] || 0) + 1;
    }
    return counts;
  }, [learnings]);

  const presentCategories = useMemo(
    () => Object.keys(categoryCounts).sort(),
    [categoryCounts]
  );

  const MAX_VISIBLE = 200;
  const capped = filtered.length > MAX_VISIBLE ? filtered.slice(0, MAX_VISIBLE) : filtered;
  const grouped = capped.reduce<Record<string, AgentLearningDTO[]>>((acc, l) => {
    (acc[l.category] ??= []).push(l);
    return acc;
  }, {});

  return (
    <div className="bg-surface-1 border border-border-subtle rounded-lg overflow-hidden">
      <div className="flex items-center justify-between px-3 py-2 bg-surface-2 border-b border-border-subtle">
        <div className="flex items-center gap-2">
          <Icon name="settings" size={14} className="text-blue-400" />
          <span className="text-xs font-medium text-text-primary">Agent Learnings</span>
          <span className="text-[10px] text-text-muted">({learnings.length})</span>
        </div>
        <div className="flex items-center gap-1">
          {learnings.length > 0 && (
            <>
              <button
                onClick={handleRecompile}
                className="text-[10px] px-2 py-0.5 rounded text-text-muted hover:text-accent hover:bg-accent/10 transition-colors"
                title="Recompile learnings prompt"
              >
                <Icon name="refresh-cw" size={11} />
              </button>
              {canDelete && (
                <button
                  onClick={handleClearAll}
                  className="text-[10px] px-2 py-0.5 rounded text-red-400 hover:bg-red-900/20 transition-colors"
                >
                  Clear all
                </button>
              )}
            </>
          )}
          <button
            onClick={onClose}
            className="p-0.5 rounded hover:bg-surface-3 transition-colors text-text-muted hover:text-text-primary"
          >
            <Icon name="x" size={14} />
          </button>
        </div>
      </div>

      {/* Category filter pills + sort dropdown */}
      {learnings.length > 0 && (
        <div className="flex items-center gap-1.5 px-3 py-1.5 border-b border-border-subtle overflow-x-auto">
          <button
            onClick={() => setFilterCategory(null)}
            className={`text-[9px] px-2 py-0.5 rounded-full font-medium transition-colors whitespace-nowrap ${
              filterCategory === null
                ? "bg-accent/20 text-accent"
                : "text-text-muted hover:text-text-primary hover:bg-surface-3"
            }`}
          >
            All ({learnings.length})
          </button>
          {presentCategories.map((cat) => (
            <button
              key={cat}
              onClick={() => setFilterCategory(filterCategory === cat ? null : cat)}
              className={`text-[9px] px-2 py-0.5 rounded-full font-medium transition-colors whitespace-nowrap ${
                filterCategory === cat
                  ? CATEGORY_COLORS[cat] || "bg-surface-3 text-text-primary"
                  : "text-text-muted hover:text-text-primary hover:bg-surface-3"
              }`}
            >
              {CATEGORY_LABELS[cat] || cat} ({categoryCounts[cat]})
            </button>
          ))}
          <div className="ml-auto shrink-0">
            <select
              value={sortKey}
              onChange={(e) => setSortKey(e.target.value as SortKey)}
              className="text-[9px] bg-surface-1 border border-border-subtle rounded px-1.5 py-0.5 text-text-muted focus:outline-none focus:ring-1 focus:ring-accent"
            >
              <option value="confidence">Sort: Confidence</option>
              <option value="date">Sort: Newest</option>
              <option value="confirmed">Sort: Most confirmed</option>
              <option value="applied">Sort: Most applied</option>
            </select>
          </div>
        </div>
      )}

      <div className="max-h-80 overflow-y-auto overflow-x-hidden sidebar-scroll">
        {loading ? (
          <div className="p-4 space-y-3">
            {[...Array(4)].map((_, i) => (
              <div key={i} className="animate-pulse space-y-2">
                <div className="h-3 bg-surface-2 rounded w-1/3" />
                <div className="h-2.5 bg-surface-2 rounded w-full" />
                <div className="h-2.5 bg-surface-2 rounded w-2/3" />
              </div>
            ))}
          </div>
        ) : learnings.length === 0 ? (
          <div className="p-4 text-center text-text-muted text-xs">
            No learnings yet. The agent will automatically learn from query outcomes.
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-4 text-center text-text-muted text-xs">
            No learnings in this category.
          </div>
        ) : (
          <div className="divide-y divide-border-subtle">
            {Object.entries(grouped).map(([category, items]) => (
              <div key={category} className="px-3 py-2">
                <div className="flex items-center gap-2 mb-1.5">
                  <span
                    className={`text-[9px] px-1.5 py-0.5 rounded-full font-medium ${
                      CATEGORY_COLORS[category] || "text-text-muted bg-surface-3"
                    }`}
                  >
                    {CATEGORY_LABELS[category] || category}
                  </span>
                  <span className="text-[9px] text-text-muted">{items.length}</span>
                </div>
                <div className="space-y-1.5">
                  {items.map((l) => (
                    <div
                      key={l.id}
                      className={`group relative rounded-md px-2.5 py-1.5 text-xs transition-colors ${
                        l.is_active
                          ? "bg-surface-2/50 hover:bg-surface-2"
                          : "bg-surface-1 opacity-50"
                      }`}
                    >
                      {editingId === l.id ? (
                        <div className="space-y-1.5">
                          <textarea
                            value={editLesson}
                            onChange={(e) => setEditLesson(e.target.value)}
                            rows={2}
                            className="w-full bg-surface-1 border border-border-subtle rounded px-2 py-1.5 text-xs text-text-primary resize-y focus:outline-none focus:ring-1 focus:ring-accent"
                          />
                          <div className="flex gap-1">
                            <button
                              onClick={() => handleSaveEdit(l.id)}
                              className="text-[10px] px-2 py-0.5 rounded bg-accent text-white hover:bg-accent-hover"
                            >
                              Save
                            </button>
                            <button
                              onClick={() => setEditingId(null)}
                              className="text-[10px] px-2 py-0.5 rounded text-text-muted hover:text-text-primary"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <div className="flex items-start gap-2">
                            <div className="flex-1 min-w-0">
                              <span className="text-[10px] font-mono text-text-tertiary">
                                {l.subject}
                              </span>
                              <p className="text-text-secondary leading-snug mt-0.5">
                                {l.lesson}
                              </p>
                            </div>
                            <div className="hidden group-hover:flex items-center gap-0.5 shrink-0">
                              <button
                                onClick={() => {
                                  setEditingId(l.id);
                                  setEditLesson(l.lesson);
                                }}
                                className="p-0.5 rounded hover:bg-surface-3 text-text-muted hover:text-text-primary"
                                title="Edit"
                              >
                                <Icon name="pencil" size={11} />
                              </button>
                              <button
                                onClick={() => handleToggleActive(l)}
                                className="p-0.5 rounded hover:bg-surface-3 text-text-muted hover:text-text-primary"
                                title={l.is_active ? "Deactivate" : "Activate"}
                              >
                                <Icon name={l.is_active ? "x" : "check"} size={11} />
                              </button>
                              {canDelete && (
                                <button
                                  onClick={() => handleDelete(l.id)}
                                  className="p-0.5 rounded hover:bg-red-900/30 text-text-muted hover:text-red-400"
                                  title="Delete"
                                >
                                  <Icon name="trash" size={11} />
                                </button>
                              )}
                            </div>
                          </div>
                          <div className="flex items-center gap-2 mt-1 text-[9px] text-text-muted">
                            <span className="flex items-center gap-0.5">
                              <span
                                className="inline-block w-8 h-1 rounded-full bg-surface-3 overflow-hidden"
                                title={`${Math.round(l.confidence * 100)}% confidence`}
                              >
                                <span
                                  className="block h-full rounded-full bg-accent"
                                  style={{ width: `${l.confidence * 100}%` }}
                                />
                              </span>
                              {Math.round(l.confidence * 100)}%
                            </span>
                            {l.times_confirmed > 0 && (
                              <span>{l.times_confirmed}x confirmed</span>
                            )}
                            {l.times_applied > 0 && (
                              <span>{l.times_applied}x applied</span>
                            )}
                          </div>
                        </>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
