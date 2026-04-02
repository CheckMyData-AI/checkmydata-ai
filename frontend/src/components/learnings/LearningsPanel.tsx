"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { api, type AgentLearningDTO } from "@/lib/api";
import { Icon } from "@/components/ui/Icon";
import { FormModal } from "@/components/ui/FormModal";
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
  pipeline_pattern: "Pipeline Patterns",
  data_quality_hint: "Data Quality Hints",
  replan_recovery: "Replan Recoveries",
};

const CATEGORY_COLORS: Record<string, string> = {
  table_preference: "text-accent bg-accent-muted",
  column_usage: "text-accent bg-accent-muted",
  data_format: "text-success bg-success-muted",
  query_pattern: "text-warning bg-warning-muted",
  schema_gotcha: "text-error bg-error-muted",
  performance_hint: "text-info bg-info-muted",
  pipeline_pattern: "text-warning bg-warning-muted",
  data_quality_hint: "text-error bg-error-muted",
  replan_recovery: "text-success bg-success-muted",
};

type SortKey = "confidence" | "date" | "confirmed" | "applied";

interface LearningsPanelProps {
  connectionId: string;
  onClose: () => void;
  onCountChange?: (count: number) => void;
}

export function LearningsPanel({ connectionId, onClose, onCountChange }: LearningsPanelProps) {
  const { canDelete, canEdit } = usePermission();
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

  const handleConfirm = async (learningId: string) => {
    try {
      const result = await api.connections.confirmLearning(connectionId, learningId);
      setLearnings((prev) =>
        prev.map((l) =>
          l.id === learningId
            ? { ...l, confidence: result.confidence, times_confirmed: result.times_confirmed }
            : l
        )
      );
    } catch {
      toast("Failed to confirm", "error");
    }
  };

  const handleContradict = async (learningId: string) => {
    try {
      const result = await api.connections.contradictLearning(connectionId, learningId);
      setLearnings((prev) =>
        prev.map((l) =>
          l.id === learningId
            ? { ...l, confidence: result.confidence, is_active: result.is_active }
            : l
        )
      );
    } catch {
      toast("Failed to contradict", "error");
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

  const titleWithCount = `Agent Learnings (${learnings.length})`;

  return (
    <FormModal
      open={true}
      onClose={onClose}
      title={titleWithCount}
      maxWidth="max-w-3xl"
    >
      {/* Toolbar: recompile / clear all */}
      {learnings.length > 0 && (
        <div className="flex items-center gap-2 mb-3">
          {canEdit && (
            <button
              onClick={handleRecompile}
              className="text-xs px-2.5 py-1 rounded text-text-muted hover:text-accent hover:bg-accent/10 transition-colors flex items-center gap-1"
              title="Recompile learnings prompt"
              aria-label="Recompile learnings"
            >
              <Icon name="refresh-cw" size={12} />
              Recompile
            </button>
          )}
          {canDelete && (
            <button
              onClick={handleClearAll}
              className="text-xs px-2.5 py-1 rounded text-error hover:bg-error-muted transition-colors"
            >
              Clear all
            </button>
          )}
        </div>
      )}

      {/* Category filter pills + sort dropdown */}
      {learnings.length > 0 && (
        <div className="flex items-center gap-1.5 pb-2 mb-2 border-b border-border-subtle overflow-x-auto">
          <button
            onClick={() => setFilterCategory(null)}
            className={`text-[11px] px-2.5 py-1 rounded-full font-medium transition-colors whitespace-nowrap ${
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
              className={`text-[11px] px-2.5 py-1 rounded-full font-medium transition-colors whitespace-nowrap ${
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
              className="text-[11px] bg-surface-1 border border-border-subtle rounded-lg px-2 py-1 text-text-muted focus:outline-none focus:ring-1 focus:ring-accent"
            >
              <option value="confidence">Sort: Confidence</option>
              <option value="date">Sort: Newest</option>
              <option value="confirmed">Sort: Most confirmed</option>
              <option value="applied">Sort: Most applied</option>
            </select>
          </div>
        </div>
      )}

      <div className="max-h-[60vh] overflow-y-auto overflow-x-hidden sidebar-scroll">
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
          <div className="p-6 text-center text-text-muted text-sm">
            No learnings yet. The agent will automatically learn from query outcomes.
          </div>
        ) : filtered.length === 0 ? (
          <div className="p-6 text-center text-text-muted text-sm">
            No learnings in this category.
          </div>
        ) : (
          <div className="divide-y divide-border-subtle">
            {Object.entries(grouped).map(([category, items]) => (
              <div key={category} className="px-1 py-2.5">
                <div className="flex items-center gap-2 mb-2">
                  <span
                    className={`text-[11px] px-2 py-0.5 rounded-full font-medium ${
                      CATEGORY_COLORS[category] || "text-text-muted bg-surface-3"
                    }`}
                  >
                    {CATEGORY_LABELS[category] || category}
                  </span>
                  <span className="text-[11px] text-text-muted">{items.length}</span>
                </div>
                <div className="space-y-2">
                  {items.map((l) => (
                    <div
                      key={l.id}
                      className={`group relative rounded-lg px-3 py-2 text-sm transition-colors ${
                        l.is_active
                          ? "bg-surface-2/50 hover:bg-surface-2"
                          : "bg-surface-1 opacity-50"
                      }`}
                    >
                      {editingId === l.id ? (
                        <div className="space-y-2">
                          <textarea
                            value={editLesson}
                            onChange={(e) => setEditLesson(e.target.value)}
                            rows={3}
                            aria-label="Edit learning"
                            className="w-full bg-surface-1 border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary resize-y min-h-[60px] focus:outline-none focus:ring-1 focus:ring-accent"
                          />
                          <div className="flex gap-1.5">
                            <button
                              onClick={() => handleSaveEdit(l.id)}
                              className="text-xs px-3 py-1 rounded bg-accent text-white hover:bg-accent-hover"
                            >
                              Save
                            </button>
                            <button
                              onClick={() => setEditingId(null)}
                              className="text-xs px-3 py-1 rounded text-text-muted hover:text-text-primary"
                            >
                              Cancel
                            </button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <div className="flex items-start gap-2">
                            <div className="flex-1 min-w-0">
                              <span className="text-[11px] font-mono text-text-tertiary">
                                {l.subject}
                              </span>
                              <p className="text-text-secondary leading-snug mt-0.5">
                                {l.lesson}
                              </p>
                            </div>
                            {canEdit && (
                              <div className="hidden group-hover:flex items-center gap-0.5 shrink-0">
                                <button
                                  onClick={() => handleConfirm(l.id)}
                                  className="p-1 rounded hover:bg-success-muted text-text-muted hover:text-success"
                                  title="Confirm (upvote)"
                                  aria-label="Confirm"
                                >
                                  <Icon name="thumbs-up" size={12} />
                                </button>
                                <button
                                  onClick={() => handleContradict(l.id)}
                                  className="p-1 rounded hover:bg-error-muted text-text-muted hover:text-error"
                                  title="Contradict (downvote)"
                                  aria-label="Contradict"
                                >
                                  <Icon name="thumbs-down" size={12} />
                                </button>
                                <button
                                  onClick={() => {
                                    setEditingId(l.id);
                                    setEditLesson(l.lesson);
                                  }}
                                  className="p-1 rounded hover:bg-surface-3 text-text-muted hover:text-text-primary"
                                  title="Edit"
                                  aria-label="Edit"
                                >
                                  <Icon name="pencil" size={12} />
                                </button>
                                <button
                                  onClick={() => handleToggleActive(l)}
                                  className="p-1 rounded hover:bg-surface-3 text-text-muted hover:text-text-primary"
                                  title={l.is_active ? "Deactivate" : "Activate"}
                                  aria-label={l.is_active ? "Deactivate" : "Activate"}
                                >
                                  <Icon name={l.is_active ? "x" : "check"} size={12} />
                                </button>
                                <button
                                  onClick={() => handleDelete(l.id)}
                                  className="p-1 rounded hover:bg-error-muted text-text-muted hover:text-error"
                                  title="Delete"
                                  aria-label="Delete"
                                >
                                  <Icon name="trash" size={12} />
                                </button>
                              </div>
                            )}
                          </div>
                          <div className="flex items-center gap-2.5 mt-1.5 text-[11px] text-text-muted">
                            <span className="flex items-center gap-1">
                              <span
                                className="inline-block w-10 h-1.5 rounded-full bg-surface-3 overflow-hidden"
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
    </FormModal>
  );
}
