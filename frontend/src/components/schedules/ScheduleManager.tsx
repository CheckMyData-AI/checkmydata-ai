"use client";

import { useState, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { ScheduledQuery, ScheduleRun } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { useConfirmStore } from "@/components/ui/ConfirmModal";
import { toast } from "@/stores/toast-store";
import { Icon } from "@/components/ui/Icon";

const CRON_PRESETS: { label: string; value: string }[] = [
  { label: "Every hour", value: "0 * * * *" },
  { label: "Every day at 9 AM", value: "0 9 * * *" },
  { label: "Every Monday at 9 AM", value: "0 9 * * 1" },
  { label: "Every 6 hours", value: "0 */6 * * *" },
  { label: "Every day at midnight", value: "0 0 * * *" },
];

const OPERATOR_LABELS: Record<string, string> = {
  gt: ">",
  lt: "<",
  eq: "=",
  gte: ">=",
  lte: "<=",
  pct_change: "% change >=",
};

function cronToHuman(cron: string): string {
  const preset = CRON_PRESETS.find((p) => p.value === cron);
  if (preset) return preset.label;
  const parts = cron.split(" ");
  if (parts.length !== 5) return cron;
  const [min, hour, dom, , dow] = parts;
  if (min === "0" && hour === "*") return "Every hour";
  if (min === "0" && dom === "*" && dow === "*") return `Daily at ${hour}:00`;
  if (min === "0" && dom === "*" && dow !== "*") {
    const days = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
    return `${days[Number(dow)] ?? dow} at ${hour}:00`;
  }
  return cron;
}

function timeAgo(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

function statusDot(schedule: ScheduledQuery) {
  if (!schedule.is_active) return "bg-gray-500";
  if (!schedule.last_run_at) return "bg-blue-400";
  return "bg-emerald-400";
}

interface AlertCondition {
  column: string;
  operator: string;
  threshold: string;
}

interface ScheduleManagerProps {
  createRequested?: boolean;
  onCreateHandled?: () => void;
}

export function ScheduleManager({ createRequested, onCreateHandled }: ScheduleManagerProps) {
  const activeProject = useAppStore((s) => s.activeProject);
  const connections = useAppStore((s) => s.connections);
  const activeConnection = useAppStore((s) => s.activeConnection);

  const [schedules, setSchedules] = useState<ScheduledQuery[]>([]);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [history, setHistory] = useState<ScheduleRun[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);

  const [title, setTitle] = useState("");
  const [sqlQuery, setSqlQuery] = useState("");
  const [cronMode, setCronMode] = useState<"preset" | "custom">("preset");
  const [cronPreset, setCronPreset] = useState(CRON_PRESETS[0].value);
  const [cronCustom, setCronCustom] = useState("");
  const [connectionId, setConnectionId] = useState("");
  const [isActive, setIsActive] = useState(true);
  const [conditions, setConditions] = useState<AlertCondition[]>([]);
  const [saving, setSaving] = useState(false);
  const [runningId, setRunningId] = useState<string | null>(null);

  const confirm = useConfirmStore((s) => s.show);

  const load = useCallback(async (signal?: { cancelled: boolean }) => {
    if (!activeProject) return;
    setLoading(true);
    try {
      const data = await api.schedules.list(activeProject.id);
      if (signal?.cancelled) return;
      setSchedules(data);
    } catch (err) {
      if (signal?.cancelled) return;
      toast(err instanceof Error ? err.message : "Failed to load schedules", "error");
    } finally {
      if (!signal?.cancelled) setLoading(false);
    }
  }, [activeProject]);

  useEffect(() => {
    const signal = { cancelled: false };
    load(signal);
    return () => { signal.cancelled = true; };
  }, [load]);

  const resetForm = () => {
    setTitle("");
    setSqlQuery("");
    setCronMode("preset");
    setCronPreset(CRON_PRESETS[0].value);
    setCronCustom("");
    setConnectionId(activeConnection?.id || connections[0]?.id || "");
    setIsActive(true);
    setConditions([]);
    setEditingId(null);
  };

  const openCreate = () => {
    resetForm();
    setConnectionId(activeConnection?.id || connections[0]?.id || "");
    setShowForm(true);
  };

  useEffect(() => {
    if (createRequested) {
      openCreate();
      onCreateHandled?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [createRequested]);

  const openEdit = (s: ScheduledQuery) => {
    setTitle(s.title);
    setSqlQuery(s.sql_query);
    setConnectionId(s.connection_id);
    setIsActive(s.is_active);
    const presetMatch = CRON_PRESETS.find((p) => p.value === s.cron_expression);
    if (presetMatch) {
      setCronMode("preset");
      setCronPreset(presetMatch.value);
    } else {
      setCronMode("custom");
      setCronCustom(s.cron_expression);
    }
    try {
      const parsed = s.alert_conditions ? JSON.parse(s.alert_conditions) : [];
      setConditions(
        parsed.map((c: { column: string; operator: string; threshold: number }) => ({
          column: c.column,
          operator: c.operator,
          threshold: String(c.threshold),
        })),
      );
    } catch {
      setConditions([]);
    }
    setEditingId(s.id);
    setShowForm(true);
  };

  const handleSave = async () => {
    if (!activeProject) return;
    if (!title.trim()) {
      toast("Please enter a schedule title", "error");
      return;
    }
    const trimmedSql = sqlQuery.trim();
    if (!trimmedSql) {
      toast("Please enter a SQL query", "error");
      return;
    }
    if (trimmedSql.length < 7) {
      toast("SQL query is too short", "error");
      return;
    }
    const cron = cronMode === "preset" ? cronPreset : cronCustom.trim();
    if (!cron) {
      toast("Please enter a cron expression", "error");
      return;
    }
    const connId = connectionId || activeConnection?.id || "";
    if (!connId) {
      toast("Please select a connection", "error");
      return;
    }

    const alertConditions =
      conditions.length > 0
        ? JSON.stringify(
            conditions.map((c) => ({
              column: c.column,
              operator: c.operator,
              threshold: parseFloat(c.threshold),
            })),
          )
        : null;

    setSaving(true);
    try {
      if (editingId) {
        const updated = await api.schedules.update(editingId, {
          title: title.trim(),
          sql_query: sqlQuery.trim(),
          cron_expression: cron,
          alert_conditions: alertConditions,
          is_active: isActive,
        });
        setSchedules((prev) => prev.map((s) => (s.id === editingId ? updated : s)));
        toast("Schedule updated", "info");
      } else {
        const created = await api.schedules.create({
          project_id: activeProject.id,
          connection_id: connId,
          title: title.trim(),
          sql_query: sqlQuery.trim(),
          cron_expression: cron,
          alert_conditions: alertConditions,
        });
        setSchedules((prev) => [created, ...prev]);
        toast("Schedule created", "info");
      }
      setShowForm(false);
      resetForm();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to save", "error");
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async (id: string) => {
    const ok = await confirm("Delete this schedule?", { destructive: true });
    if (!ok) return;
    try {
      await api.schedules.delete(id);
      setSchedules((prev) => prev.filter((s) => s.id !== id));
      toast("Schedule deleted", "info");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to delete", "error");
    }
  };

  const handleRunNow = async (id: string) => {
    setRunningId(id);
    try {
      const run = await api.schedules.runNow(id);
      if (run.status === "failed") {
        toast("Scheduled query failed", "error");
      } else if (run.status === "alert_triggered") {
        toast("Query ran - alerts triggered", "info");
      } else {
        toast("Query executed successfully", "info");
      }
      load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Run failed", "error");
    } finally {
      setRunningId(null);
    }
  };

  const handleToggleActive = async (s: ScheduledQuery) => {
    try {
      const updated = await api.schedules.update(s.id, { is_active: !s.is_active });
      setSchedules((prev) => prev.map((item) => (item.id === s.id ? updated : item)));
    } catch (err) {
      toast(err instanceof Error ? err.message : "Toggle failed", "error");
    }
  };

  const loadHistory = async (id: string) => {
    if (expandedId === id) {
      setExpandedId(null);
      return;
    }
    setExpandedId(id);
    setHistoryLoading(true);
    try {
      const runs = await api.schedules.history(id);
      setHistory(runs);
    } catch {
      setHistory([]);
      toast("Failed to load run history", "error");
    } finally {
      setHistoryLoading(false);
    }
  };

  const addCondition = () => {
    setConditions((prev) => [...prev, { column: "", operator: "gt", threshold: "" }]);
  };

  const removeCondition = (idx: number) => {
    setConditions((prev) => prev.filter((_, i) => i !== idx));
  };

  const updateCondition = (idx: number, field: keyof AlertCondition, value: string) => {
    setConditions((prev) =>
      prev.map((c, i) => (i === idx ? { ...c, [field]: value } : c)),
    );
  };

  if (!activeProject) return null;

  return (
    <div className="space-y-2 px-1">
      {loading && schedules.length === 0 && (
        <div className="space-y-1.5">
          {[1, 2].map((i) => (
            <div key={i} className="h-10 rounded bg-surface-2 animate-pulse" />
          ))}
        </div>
      )}

      {!loading && schedules.length === 0 && !showForm && (
        <p className="text-[11px] text-text-muted px-1 py-1">
          No scheduled queries yet.
        </p>
      )}

      {schedules.map((s) => (
        <div key={s.id} className="bg-surface-1 border border-border-subtle rounded-lg overflow-hidden">
          <div className="px-2.5 py-2 flex items-center gap-2">
            <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${statusDot(s)}`} />
            <div className="flex-1 min-w-0">
              <p className="text-[11px] font-medium text-text-primary truncate">{s.title}</p>
              <p className="text-[10px] text-text-muted">
                {cronToHuman(s.cron_expression)}
                {s.last_run_at && <> &middot; {timeAgo(s.last_run_at)}</>}
              </p>
            </div>
            <div className="flex items-center gap-0.5 shrink-0">
              <button
                onClick={() => handleToggleActive(s)}
                title={s.is_active ? "Pause" : "Activate"}
                className="p-1 rounded text-text-muted hover:text-text-secondary hover:bg-surface-2 transition-colors"
              >
                <Icon name={s.is_active ? "pause" : "play"} size={11} />
              </button>
              <button
                onClick={() => handleRunNow(s.id)}
                disabled={runningId === s.id}
                title="Run now"
                className="p-1 rounded text-text-muted hover:text-accent hover:bg-accent-muted transition-colors disabled:opacity-40"
              >
                <Icon
                  name="refresh-cw"
                  size={11}
                  className={runningId === s.id ? "animate-spin" : ""}
                />
              </button>
              <button
                onClick={() => loadHistory(s.id)}
                title="History"
                className="p-1 rounded text-text-muted hover:text-text-secondary hover:bg-surface-2 transition-colors"
              >
                <Icon name="clock" size={11} />
              </button>
              <button
                onClick={() => openEdit(s)}
                title="Edit"
                className="p-1 rounded text-text-muted hover:text-text-secondary hover:bg-surface-2 transition-colors"
              >
                <Icon name="edit" size={11} />
              </button>
              <button
                onClick={() => handleDelete(s.id)}
                title="Delete"
                className="p-1 rounded text-text-muted hover:text-error hover:bg-red-900/20 transition-colors"
              >
                <Icon name="trash" size={11} />
              </button>
            </div>
          </div>

          {expandedId === s.id && (
            <div className="border-t border-border-subtle px-2.5 py-2 space-y-1">
              {historyLoading ? (
                <p className="text-[10px] text-text-muted">Loading...</p>
              ) : history.length === 0 ? (
                <p className="text-[10px] text-text-muted">No runs yet</p>
              ) : (
                history.slice(0, 10).map((run) => (
                  <div
                    key={run.id}
                    className="flex items-center gap-2 text-[10px]"
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                        run.status === "success"
                          ? "bg-emerald-400"
                          : run.status === "alert_triggered"
                            ? "bg-amber-400"
                            : "bg-red-400"
                      }`}
                    />
                    <span className="text-text-secondary">{run.status}</span>
                    {run.duration_ms != null && (
                      <span className="text-text-muted">{(run.duration_ms / 1000).toFixed(1)}s</span>
                    )}
                    {run.executed_at && (
                      <span className="text-text-muted ml-auto">{timeAgo(run.executed_at)}</span>
                    )}
                  </div>
                ))
              )}
            </div>
          )}
        </div>
      ))}

      {showForm && (
        <div className="bg-surface-1 border border-accent/30 rounded-lg p-2.5 space-y-2">
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Schedule title"
            className="w-full text-[11px] bg-surface-0 border border-border-default rounded px-2 py-1.5 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent"
          />

          <textarea
            value={sqlQuery}
            onChange={(e) => setSqlQuery(e.target.value)}
            placeholder="SQL query"
            rows={3}
            className="w-full text-[11px] font-mono bg-surface-0 border border-border-default rounded px-2 py-1.5 text-text-primary placeholder:text-text-muted resize-none focus:outline-none focus:border-accent"
          />

          {connections.length > 1 && (
            <select
              value={connectionId}
              onChange={(e) => setConnectionId(e.target.value)}
              className="w-full text-[11px] bg-surface-0 border border-border-default rounded px-2 py-1.5 text-text-primary focus:outline-none focus:border-accent"
            >
              {connections.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          )}

          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <button
                onClick={() => setCronMode("preset")}
                className={`text-[10px] px-2 py-0.5 rounded ${
                  cronMode === "preset"
                    ? "bg-accent text-white"
                    : "bg-surface-2 text-text-secondary hover:bg-surface-3"
                }`}
              >
                Preset
              </button>
              <button
                onClick={() => setCronMode("custom")}
                className={`text-[10px] px-2 py-0.5 rounded ${
                  cronMode === "custom"
                    ? "bg-accent text-white"
                    : "bg-surface-2 text-text-secondary hover:bg-surface-3"
                }`}
              >
                Custom
              </button>
            </div>
            {cronMode === "preset" ? (
              <select
                value={cronPreset}
                onChange={(e) => setCronPreset(e.target.value)}
                className="w-full text-[11px] bg-surface-0 border border-border-default rounded px-2 py-1.5 text-text-primary focus:outline-none focus:border-accent"
              >
                {CRON_PRESETS.map((p) => (
                  <option key={p.value} value={p.value}>
                    {p.label}
                  </option>
                ))}
              </select>
            ) : (
              <input
                value={cronCustom}
                onChange={(e) => setCronCustom(e.target.value)}
                placeholder="e.g. 0 */2 * * *"
                className="w-full text-[11px] font-mono bg-surface-0 border border-border-default rounded px-2 py-1.5 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent"
              />
            )}
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-[10px] text-text-tertiary">Alert Conditions</span>
              <button
                onClick={addCondition}
                className="text-[10px] text-accent hover:text-accent-hover"
              >
                + Add
              </button>
            </div>
            {conditions.map((cond, idx) => (
              <div key={idx} className="flex items-center gap-1">
                <input
                  value={cond.column}
                  onChange={(e) => updateCondition(idx, "column", e.target.value)}
                  placeholder="column"
                  className="flex-1 text-[10px] bg-surface-0 border border-border-default rounded px-1.5 py-1 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent"
                />
                <select
                  value={cond.operator}
                  onChange={(e) => updateCondition(idx, "operator", e.target.value)}
                  className="text-[10px] bg-surface-0 border border-border-default rounded px-1 py-1 text-text-primary focus:outline-none focus:border-accent"
                >
                  {Object.entries(OPERATOR_LABELS).map(([k, v]) => (
                    <option key={k} value={k}>
                      {v}
                    </option>
                  ))}
                </select>
                <input
                  value={cond.threshold}
                  onChange={(e) => updateCondition(idx, "threshold", e.target.value)}
                  placeholder="value"
                  type="number"
                  className="w-16 text-[10px] bg-surface-0 border border-border-default rounded px-1.5 py-1 text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent"
                />
                <button
                  onClick={() => removeCondition(idx)}
                  className="p-0.5 text-text-muted hover:text-error"
                >
                  <Icon name="x" size={10} />
                </button>
              </div>
            ))}
          </div>

          {editingId && (
            <label className="flex items-center gap-2 text-[11px] text-text-secondary cursor-pointer">
              <input
                type="checkbox"
                checked={isActive}
                onChange={(e) => setIsActive(e.target.checked)}
                className="rounded border-border-default text-accent focus:ring-accent"
              />
              Active
            </label>
          )}

          <div className="flex gap-1.5 justify-end pt-1">
            <button
              onClick={() => {
                setShowForm(false);
                resetForm();
              }}
              className="text-[10px] px-2.5 py-1 rounded text-text-muted hover:text-text-secondary"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={saving || !title.trim() || !sqlQuery.trim()}
              className="text-[10px] px-2.5 py-1 rounded bg-accent text-white hover:bg-accent-hover disabled:opacity-50"
            >
              {saving ? "Saving..." : editingId ? "Update" : "Create"}
            </button>
          </div>
        </div>
      )}

    </div>
  );
}
