"use client";

import { useState, useRef, useEffect } from "react";
import type { SavedNote } from "@/lib/api";
import { api } from "@/lib/api";
import { useNotesStore } from "@/stores/notes-store";
import { useConfirmStore } from "@/components/ui/ConfirmModal";
import { toast } from "@/stores/toast-store";
import { Icon } from "@/components/ui/Icon";
import type { RawResult } from "@/stores/app-store";

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

function parseResult(json: string | null): RawResult | null {
  if (!json) return null;
  try {
    return JSON.parse(json);
  } catch {
    return null;
  }
}

interface NoteCardProps {
  note: SavedNote;
}

export function NoteCard({ note }: NoteCardProps) {
  const { removeNote, updateNote } = useNotesStore();
  const confirm = useConfirmStore((s) => s.show);

  const [showSql, setShowSql] = useState(false);
  const [showResult, setShowResult] = useState(false);
  const [executing, setExecuting] = useState(false);
  const [editingComment, setEditingComment] = useState(false);
  const [commentDraft, setCommentDraft] = useState(note.comment ?? "");
  const commentRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    if (editingComment && commentRef.current) {
      commentRef.current.focus();
      commentRef.current.selectionStart = commentRef.current.value.length;
    }
  }, [editingComment]);

  const result = parseResult(note.last_result_json);

  const handleDelete = async () => {
    const ok = await confirm("Delete this saved query?", { destructive: true });
    if (!ok) return;
    try {
      await api.notes.delete(note.id);
      removeNote(note.id);
      toast("Note deleted", "info");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to delete", "error");
    }
  };

  const handleExecute = async () => {
    setExecuting(true);
    try {
      const res = await api.notes.execute(note.id);
      if (res.error) {
        toast(`Query error: ${res.error}`, "error");
      } else {
        updateNote(note.id, {
          last_result_json: res.last_result_json,
          last_executed_at: res.last_executed_at,
        });
        setShowResult(true);
        toast("Query executed successfully", "info");
      }
    } catch (err) {
      toast(err instanceof Error ? err.message : "Execution failed", "error");
    } finally {
      setExecuting(false);
    }
  };

  const handleSaveComment = async () => {
    const trimmed = commentDraft.trim();
    try {
      await api.notes.update(note.id, { comment: trimmed || null });
      updateNote(note.id, { comment: trimmed || null });
      setEditingComment(false);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to save comment", "error");
    }
  };

  const handleCopySql = () => {
    navigator.clipboard.writeText(note.sql_query);
    toast("SQL copied to clipboard", "info");
  };

  return (
    <div className="bg-surface-1 border border-border-subtle rounded-lg overflow-hidden">
      {/* Header */}
      <div className="px-3 py-2.5 flex items-start gap-2">
        <div className="flex-1 min-w-0">
          <h4 className="text-xs font-medium text-text-primary truncate" title={note.title}>
            {note.title}
          </h4>
          {note.last_executed_at && (
            <span className="text-[10px] text-text-muted">
              {timeAgo(note.last_executed_at)}
            </span>
          )}
        </div>
        <div className="flex items-center gap-0.5 shrink-0">
          <button
            onClick={handleExecute}
            disabled={executing || !note.connection_id}
            title={note.connection_id ? "Run again" : "No connection"}
            className="p-1 rounded text-text-muted hover:text-accent hover:bg-accent-muted transition-colors disabled:opacity-40"
          >
            <Icon name="play" size={12} className={executing ? "animate-pulse" : ""} />
          </button>
          <button
            onClick={handleDelete}
            title="Delete"
            className="p-1 rounded text-text-muted hover:text-error hover:bg-red-900/20 transition-colors"
          >
            <Icon name="trash" size={12} />
          </button>
        </div>
      </div>

      {/* Comment */}
      <div className="px-3 pb-2">
        {editingComment ? (
          <div className="flex flex-col gap-1">
            <textarea
              ref={commentRef}
              value={commentDraft}
              onChange={(e) => setCommentDraft(e.target.value)}
              rows={2}
              className="w-full text-[11px] bg-surface-0 border border-border-default rounded px-2 py-1.5 text-text-secondary resize-none focus:outline-none focus:border-accent"
              placeholder="Add a comment..."
            />
            <div className="flex gap-1 justify-end">
              <button
                onClick={() => { setEditingComment(false); setCommentDraft(note.comment ?? ""); }}
                className="text-[10px] px-2 py-0.5 rounded text-text-muted hover:text-text-secondary"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveComment}
                className="text-[10px] px-2 py-0.5 rounded bg-accent text-white hover:bg-accent-hover"
              >
                Save
              </button>
            </div>
          </div>
        ) : (
          <button
            onClick={() => { setCommentDraft(note.comment ?? ""); setEditingComment(true); }}
            className="text-[11px] text-text-muted hover:text-text-secondary transition-colors text-left w-full"
          >
            {note.comment || "Add comment..."}
          </button>
        )}
      </div>

      {/* SQL toggle */}
      <div className="border-t border-border-subtle">
        <div className="flex items-center px-3 py-1.5 text-[10px] text-text-tertiary">
          <button
            onClick={() => setShowSql((v) => !v)}
            className="flex items-center gap-1.5 hover:text-text-secondary transition-colors"
          >
            <Icon name={showSql ? "chevron-down" : "chevron-right"} size={10} />
            SQL Query
          </button>
          <button
            onClick={handleCopySql}
            title="Copy SQL"
            className="ml-auto p-0.5 rounded hover:bg-surface-2 hover:text-text-secondary transition-colors"
          >
            <Icon name="copy" size={10} />
          </button>
        </div>
        {showSql && (
          <pre className="px-3 pb-2 text-[10px] font-mono text-text-secondary overflow-x-auto max-h-32 overflow-y-auto whitespace-pre-wrap">
            {note.sql_query}
          </pre>
        )}
      </div>

      {/* Result toggle */}
      {result && (
        <div className="border-t border-border-subtle">
          <button
            onClick={() => setShowResult((v) => !v)}
            className="w-full flex items-center gap-1.5 px-3 py-1.5 text-[10px] text-text-tertiary hover:text-text-secondary transition-colors"
          >
            <Icon name={showResult ? "chevron-down" : "chevron-right"} size={10} />
            Result ({result.total_rows} row{result.total_rows !== 1 ? "s" : ""}, {result.columns.length} col{result.columns.length !== 1 ? "s" : ""})
          </button>
          {showResult && (
            <div className="px-2 pb-2 overflow-x-auto">
              <table className="text-[10px] border-collapse w-full">
                <thead>
                  <tr className="border-b border-border-subtle">
                    {result.columns.map((col) => (
                      <th key={col} className="text-left px-1.5 py-1 text-text-tertiary font-medium whitespace-nowrap">
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {result.rows.slice(0, 20).map((row, i) => (
                    <tr key={i} className="border-b border-border-subtle/50">
                      {row.map((cell, j) => (
                        <td key={j} className="px-1.5 py-0.5 text-text-secondary whitespace-nowrap max-w-[150px] truncate">
                          {cell == null ? <span className="text-text-muted italic">null</span> : String(cell)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {result.total_rows > 20 && (
                <p className="text-[9px] text-text-muted mt-1 px-1.5">
                  Showing 20 of {result.total_rows} rows
                </p>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
