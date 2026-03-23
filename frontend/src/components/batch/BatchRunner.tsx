"use client";

import { useState, useCallback, useRef, useEffect } from "react";
import { Icon } from "@/components/ui/Icon";
import { api, type SavedNote } from "@/lib/api";
import { useNotesStore } from "@/stores/notes-store";
import { toast } from "@/stores/toast-store";
import { useAppStore } from "@/stores/app-store";
import { BatchResults } from "./BatchResults";

interface QueryRow {
  id: string;
  sql: string;
  title: string;
}

interface BatchRunnerProps {
  onClose: () => void;
  connectionId?: string | null;
  preselectedNoteIds?: string[];
}

function generateId(): string {
  return Math.random().toString(36).slice(2, 10);
}

export function BatchRunner({ onClose, connectionId, preselectedNoteIds }: BatchRunnerProps) {
  const activeProject = useAppStore((s) => s.activeProject);
  const connections = useAppStore((s) => s.connections);
  const notes = useNotesStore((s) => s.notes);

  const [selectedConnId, setSelectedConnId] = useState(connectionId || "");
  const [batchTitle, setBatchTitle] = useState("Batch Run");
  const [queries, setQueries] = useState<QueryRow[]>(() => {
    if (preselectedNoteIds?.length) {
      return preselectedNoteIds
        .map((nid) => notes.find((n) => n.id === nid))
        .filter((n): n is SavedNote => !!n)
        .map((n) => ({ id: generateId(), sql: n.sql_query, title: n.title }));
    }
    return [{ id: generateId(), sql: "", title: "" }];
  });
  const [isRunning, setIsRunning] = useState(false);
  const [progress, setProgress] = useState({ current: 0, total: 0 });
  const [batchId, setBatchId] = useState<string | null>(null);
  const [showNotePicker, setShowNotePicker] = useState(false);
  const [showResults, setShowResults] = useState(false);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    return () => {
      mountedRef.current = false;
      if (pollRef.current) clearInterval(pollRef.current);
    };
  }, []);

  const addQuery = useCallback(() => {
    setQueries((prev) => [...prev, { id: generateId(), sql: "", title: "" }]);
  }, []);

  const removeQuery = useCallback((id: string) => {
    setQueries((prev) => prev.filter((q) => q.id !== id));
  }, []);

  const updateQuery = useCallback((id: string, field: "sql" | "title", value: string) => {
    setQueries((prev) => prev.map((q) => (q.id === id ? { ...q, [field]: value } : q)));
  }, []);

  const moveQuery = useCallback((idx: number, direction: -1 | 1) => {
    setQueries((prev) => {
      const next = [...prev];
      const targetIdx = idx + direction;
      if (targetIdx < 0 || targetIdx >= next.length) return prev;
      [next[idx], next[targetIdx]] = [next[targetIdx], next[idx]];
      return next;
    });
  }, []);

  const addFromNotes = useCallback((selectedNotes: SavedNote[]) => {
    const rows: QueryRow[] = selectedNotes.map((n) => ({
      id: generateId(),
      sql: n.sql_query,
      title: n.title,
    }));
    setQueries((prev) => [...prev, ...rows]);
    setShowNotePicker(false);
  }, []);

  const handleRun = async () => {
    if (!activeProject) return;
    const connId = selectedConnId;
    if (!connId) {
      toast("Select a connection first", "error");
      return;
    }

    const validQueries = queries.filter((q) => q.sql.trim());
    if (validQueries.length === 0) {
      toast("Add at least one query", "error");
      return;
    }

    setIsRunning(true);
    setProgress({ current: 0, total: validQueries.length });

    try {
      const res = await api.batch.execute({
        project_id: activeProject.id,
        connection_id: connId,
        title: batchTitle || "Batch Run",
        queries: validQueries.map((q) => ({ sql: q.sql, title: q.title || "Untitled" })),
      });

      setBatchId(res.batch_id);

      pollRef.current = setInterval(async () => {
        if (!mountedRef.current) return;
        try {
          const batch = await api.batch.get(res.batch_id);
          if (!mountedRef.current) return;
          const results = batch.results_json ? JSON.parse(batch.results_json) : [];
          setProgress({ current: results.length, total: validQueries.length });

          if (batch.status !== "pending" && batch.status !== "running") {
            if (pollRef.current) clearInterval(pollRef.current);
            pollRef.current = null;
            setIsRunning(false);
            setShowResults(true);
            toast(
              batch.status === "completed"
                ? "Batch completed successfully"
                : batch.status === "partially_failed"
                  ? "Batch completed with some failures"
                  : "Batch failed",
              batch.status === "completed" ? "info" : "error",
            );
          }
        } catch {
          // keep polling
        }
      }, 1500);
    } catch (err) {
      setIsRunning(false);
      toast(err instanceof Error ? err.message : "Failed to start batch", "error");
    }
  };

  if (showResults && batchId) {
    return <BatchResults batchId={batchId} onClose={onClose} onBack={() => setShowResults(false)} />;
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={(e) => { if (e.target === e.currentTarget && !isRunning) onClose(); }}>
      <div className="bg-surface-0 border border-border-subtle rounded-lg w-full max-w-2xl max-h-[85vh] flex flex-col mx-4 shadow-xl">
        {/* Header */}
        <div className="shrink-0 px-5 py-4 border-b border-border-subtle flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Icon name="layers" size={16} className="text-accent" />
            <h2 className="text-sm font-semibold text-text-primary">Batch Query Runner</h2>
          </div>
          {!isRunning && (
            <button onClick={onClose} aria-label="Close batch runner" className="p-1.5 rounded text-text-muted hover:text-text-secondary hover:bg-surface-2 transition-colors">
              <Icon name="x" size={14} />
            </button>
          )}
        </div>

        {/* Config row */}
        <div className="shrink-0 px-5 py-3 border-b border-border-subtle flex items-center gap-3">
          <input
            type="text"
            value={batchTitle}
            onChange={(e) => setBatchTitle(e.target.value)}
            placeholder="Batch title..."
            aria-label="Batch title"
            className="flex-1 text-xs bg-surface-1 border border-border-default rounded px-3 py-1.5 text-text-primary focus:outline-none focus:border-accent"
          />
          <select
            value={selectedConnId}
            onChange={(e) => setSelectedConnId(e.target.value)}
            aria-label="Select connection"
            className="text-xs bg-surface-1 border border-border-default rounded px-3 py-1.5 text-text-primary focus:outline-none focus:border-accent"
          >
            <option value="">Select connection...</option>
            {connections.map((c) => (
              <option key={c.id} value={c.id}>{c.name} ({c.db_type})</option>
            ))}
          </select>
        </div>

        {/* Query list */}
        <div className="flex-1 overflow-y-auto p-5 space-y-3 sidebar-scroll">
          {queries.map((q, idx) => (
            <div key={q.id} className="bg-surface-1 border border-border-subtle rounded-lg p-3">
              <div className="flex items-center gap-2 mb-2">
                <span className="text-[10px] font-mono text-text-muted w-5 text-center shrink-0">{idx + 1}</span>
                <input
                  type="text"
                  value={q.title}
                  onChange={(e) => updateQuery(q.id, "title", e.target.value)}
                  placeholder="Query title..."
                  aria-label={`Query ${idx + 1} title`}
                  className="flex-1 text-xs bg-surface-0 border border-border-default rounded px-2 py-1 text-text-primary focus:outline-none focus:border-accent"
                />
                <div className="flex gap-0.5 shrink-0">
                  <button
                    onClick={() => moveQuery(idx, -1)}
                    disabled={idx === 0}
                    className="p-1 rounded text-text-muted hover:text-text-secondary hover:bg-surface-2 transition-colors disabled:opacity-30"
                    title="Move up"
                    aria-label={`Move query ${idx + 1} up`}
                  >
                    <Icon name="arrow-up" size={11} />
                  </button>
                  <button
                    onClick={() => moveQuery(idx, 1)}
                    disabled={idx === queries.length - 1}
                    className="p-1 rounded text-text-muted hover:text-text-secondary hover:bg-surface-2 transition-colors disabled:opacity-30"
                    title="Move down"
                    aria-label={`Move query ${idx + 1} down`}
                  >
                    <Icon name="arrow-down" size={11} />
                  </button>
                  <button
                    onClick={() => removeQuery(q.id)}
                    disabled={queries.length <= 1}
                    className="p-1 rounded text-text-muted hover:text-error hover:bg-red-900/20 transition-colors disabled:opacity-30"
                    title="Remove"
                    aria-label={`Remove query ${idx + 1}`}
                  >
                    <Icon name="trash" size={11} />
                  </button>
                </div>
              </div>
              <textarea
                value={q.sql}
                onChange={(e) => updateQuery(q.id, "sql", e.target.value)}
                placeholder="SELECT ..."
                aria-label={`Query ${idx + 1} SQL`}
                rows={3}
                className="w-full text-[11px] font-mono bg-surface-0 border border-border-default rounded px-2.5 py-2 text-text-secondary resize-y focus:outline-none focus:border-accent leading-relaxed"
              />
            </div>
          ))}
        </div>

        {/* Progress bar */}
        {isRunning && (
          <div className="shrink-0 px-5 py-3 border-t border-border-subtle" aria-live="polite" role="status">
            <div className="flex items-center justify-between mb-1.5">
              <span className="text-[11px] text-text-secondary">
                Running queries...
              </span>
              <span className="text-[11px] font-mono text-text-muted">
                {progress.current}/{progress.total}
              </span>
            </div>
            <div className="h-1.5 bg-surface-2 rounded-full overflow-hidden">
              <div
                className="h-full bg-accent rounded-full transition-all duration-300"
                style={{ width: progress.total > 0 ? `${(progress.current / progress.total) * 100}%` : "0%" }}
              />
            </div>
          </div>
        )}

        {/* Footer actions */}
        <div className="shrink-0 px-5 py-3 border-t border-border-subtle flex items-center justify-between">
          <div className="flex gap-2">
            <button
              onClick={addQuery}
              disabled={isRunning}
              className="flex items-center gap-1 text-[11px] px-3 py-1.5 rounded border border-border-default text-text-secondary hover:text-text-primary hover:bg-surface-2 transition-colors disabled:opacity-40"
            >
              <Icon name="plus" size={11} />
              Add Query
            </button>
            <button
              onClick={() => setShowNotePicker(true)}
              disabled={isRunning || notes.length === 0}
              className="flex items-center gap-1 text-[11px] px-3 py-1.5 rounded border border-border-default text-text-secondary hover:text-text-primary hover:bg-surface-2 transition-colors disabled:opacity-40"
            >
              <Icon name="bookmark" size={11} />
              From Saved Notes
            </button>
          </div>
          <button
            onClick={handleRun}
            disabled={isRunning || queries.every((q) => !q.sql.trim())}
            className="flex items-center gap-1.5 text-xs px-4 py-1.5 rounded bg-accent text-white hover:bg-accent-hover transition-colors disabled:opacity-40"
          >
            {isRunning ? (
              <>
                <Icon name="refresh-cw" size={12} className="animate-spin" />
                Running...
              </>
            ) : (
              <>
                <Icon name="play" size={12} />
                Run All ({queries.filter((q) => q.sql.trim()).length})
              </>
            )}
          </button>
        </div>

        {/* Note picker overlay */}
        {showNotePicker && (
          <NotePicker
            notes={notes}
            onSelect={addFromNotes}
            onClose={() => setShowNotePicker(false)}
          />
        )}
      </div>
    </div>
  );
}

interface NotePickerProps {
  notes: SavedNote[];
  onSelect: (notes: SavedNote[]) => void;
  onClose: () => void;
}

function NotePicker({ notes, onSelect, onClose }: NotePickerProps) {
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const toggle = (id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  };

  const handleAdd = () => {
    const picked = notes.filter((n) => selected.has(n.id));
    onSelect(picked);
  };

  return (
    <div className="absolute inset-0 bg-surface-0/95 rounded-lg flex flex-col z-10">
      <div className="px-5 py-3 border-b border-border-subtle flex items-center justify-between">
        <h3 className="text-xs font-medium text-text-primary">Select Saved Notes</h3>
        <button onClick={onClose} aria-label="Close note picker" className="p-1.5 rounded text-text-muted hover:text-text-secondary hover:bg-surface-2 transition-colors min-w-[28px] min-h-[28px] flex items-center justify-center">
          <Icon name="x" size={14} />
        </button>
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-1.5">
        {notes.length === 0 ? (
          <p className="text-xs text-text-muted text-center py-4">No saved notes</p>
        ) : (
          notes.map((note) => (
            <label
              key={note.id}
              className={`flex items-start gap-2.5 p-2.5 rounded-lg border cursor-pointer transition-colors ${
                selected.has(note.id)
                  ? "border-accent bg-accent/5"
                  : "border-border-subtle hover:border-border-default"
              }`}
            >
              <input
                type="checkbox"
                checked={selected.has(note.id)}
                onChange={() => toggle(note.id)}
                className="mt-0.5 shrink-0 accent-accent"
              />
              <div className="min-w-0">
                <p className="text-xs font-medium text-text-primary truncate">{note.title}</p>
                <p className="text-[10px] font-mono text-text-muted truncate mt-0.5">{note.sql_query}</p>
              </div>
            </label>
          ))
        )}
      </div>
      <div className="px-5 py-3 border-t border-border-subtle flex justify-end gap-2">
        <button onClick={onClose} className="text-[11px] px-3 py-1.5 rounded text-text-muted hover:text-text-secondary">
          Cancel
        </button>
        <button
          onClick={handleAdd}
          disabled={selected.size === 0}
          className="text-[11px] px-4 py-1.5 rounded bg-accent text-white hover:bg-accent-hover disabled:opacity-40"
        >
          Add {selected.size > 0 ? `(${selected.size})` : ""}
        </button>
      </div>
    </div>
  );
}
