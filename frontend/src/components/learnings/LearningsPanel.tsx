"use client";

import { useEffect, useState } from "react";
import { api, type AgentLearningDTO } from "@/lib/api";
import { Icon } from "@/components/ui/Icon";
import { confirmAction } from "@/components/ui/ConfirmModal";
import { toast } from "@/stores/toast-store";

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

interface LearningsPanelProps {
  connectionId: string;
  onClose: () => void;
  onCountChange?: (count: number) => void;
}

export function LearningsPanel({ connectionId, onClose, onCountChange }: LearningsPanelProps) {
  const [learnings, setLearnings] = useState<AgentLearningDTO[]>([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editLesson, setEditLesson] = useState("");

  const load = async () => {
    setLoading(true);
    try {
      const data = await api.connections.listLearnings(connectionId);
      setLearnings(data);
      onCountChange?.(data.filter((l) => l.is_active).length);
    } catch {
      toast("Failed to load learnings", "error");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [connectionId]);

  const handleDelete = async (learningId: string) => {
    if (!(await confirmAction("Delete this learning?"))) return;
    try {
      await api.connections.deleteLearning(connectionId, learningId);
      setLearnings((prev) => prev.filter((l) => l.id !== learningId));
      onCountChange?.(learnings.filter((l) => l.is_active && l.id !== learningId).length);
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
      onCountChange?.(
        learnings.filter((x) => (x.id === l.id ? !x.is_active : x.is_active)).length
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

  const handleClearAll = async () => {
    if (!(await confirmAction("Clear ALL learnings for this connection? This cannot be undone."))) return;
    try {
      const result = await api.connections.clearLearnings(connectionId);
      setLearnings([]);
      onCountChange?.(0);
      toast(`Cleared ${result.deleted} learnings`, "success");
    } catch {
      toast("Failed to clear", "error");
    }
  };

  const grouped = learnings.reduce<Record<string, AgentLearningDTO[]>>((acc, l) => {
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
            <button
              onClick={handleClearAll}
              className="text-[10px] px-2 py-0.5 rounded text-red-400 hover:bg-red-900/20 transition-colors"
            >
              Clear all
            </button>
          )}
          <button
            onClick={onClose}
            className="p-0.5 rounded hover:bg-surface-3 transition-colors text-text-muted hover:text-text-primary"
          >
            <Icon name="x" size={14} />
          </button>
        </div>
      </div>

      <div className="max-h-80 overflow-y-auto overflow-x-hidden sidebar-scroll">
        {loading ? (
          <div className="p-4 text-center text-text-muted text-xs">Loading...</div>
        ) : learnings.length === 0 ? (
          <div className="p-4 text-center text-text-muted text-xs">
            No learnings yet. The agent will automatically learn from query outcomes.
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
                              <button
                                onClick={() => handleDelete(l.id)}
                                className="p-0.5 rounded hover:bg-red-900/30 text-text-muted hover:text-red-400"
                                title="Delete"
                              >
                                <Icon name="trash" size={11} />
                              </button>
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
