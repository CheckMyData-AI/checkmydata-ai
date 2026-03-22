"use client";

import { useEffect, useState } from "react";
import { useNotesStore } from "@/stores/notes-store";
import { useAppStore } from "@/stores/app-store";
import { NoteCard } from "./NoteCard";
import { Icon } from "@/components/ui/Icon";
import { BatchRunner } from "@/components/batch/BatchRunner";

const SCOPE_OPTIONS = [
  { value: "all" as const, label: "All" },
  { value: "mine" as const, label: "Mine" },
  { value: "shared" as const, label: "Shared" },
] as const;

export function NotesPanel() {
  const { notes, isOpen, isLoading, scope, setOpen, setScope, loadNotes } = useNotesStore();
  const activeProject = useAppStore((s) => s.activeProject);
  const projectId = activeProject?.id;
  const [showBatchRunner, setShowBatchRunner] = useState(false);

  useEffect(() => {
    if (projectId) {
      loadNotes(projectId);
    } else {
      useNotesStore.getState().clear();
    }
  }, [projectId, loadNotes]);

  if (!activeProject || !isOpen) return null;

  return (
    <aside className="shrink-0 w-full md:w-80 max-w-[100vw] border-l border-border-subtle bg-surface-0 flex flex-col h-full overflow-hidden transition-all duration-200 ease-out">
      {/* Header */}
      <div className="shrink-0 px-4 py-3 border-b border-border-subtle flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Icon name="bookmark" size={14} className="text-text-tertiary" />
          <h3 className="text-sm font-medium text-text-primary">
            Saved Queries
          </h3>
          {notes.length > 0 && (
            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-surface-2 text-text-muted">
              {notes.length}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          {notes.length >= 2 && (
            <button
              onClick={() => setShowBatchRunner(true)}
              title="Batch run all saved queries"
              className="flex items-center gap-1 px-2 py-1 rounded text-[10px] text-text-muted hover:text-accent hover:bg-accent-muted transition-colors"
            >
              <Icon name="layers" size={11} />
              <span>Batch</span>
            </button>
          )}
          <button
            onClick={() => setOpen(false)}
            aria-label="Close notes panel"
            className="p-1 rounded text-text-muted hover:text-text-secondary hover:bg-surface-2 transition-colors"
          >
            <Icon name="x" size={14} />
          </button>
        </div>
      </div>

      {showBatchRunner && (
        <BatchRunner
          onClose={() => setShowBatchRunner(false)}
          preselectedNoteIds={notes.map((n) => n.id)}
        />
      )}

      {/* Scope tabs */}
      <div className="shrink-0 px-3 pt-2 pb-1 flex gap-1">
        {SCOPE_OPTIONS.map((opt) => (
          <button
            key={opt.value}
            onClick={() => setScope(opt.value)}
            className={`px-2.5 py-1 rounded text-[10px] font-medium transition-colors ${
              scope === opt.value
                ? "bg-accent-muted text-accent"
                : "text-text-muted hover:text-text-secondary hover:bg-surface-2"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>

      {/* Content */}
      <div className="flex-1 overflow-y-auto overflow-x-hidden sidebar-scroll p-3 space-y-2">
        {isLoading ? (
          <div className="flex items-center justify-center py-8">
            <div className="w-5 h-5 border-2 border-accent border-t-transparent rounded-full animate-spin" />
          </div>
        ) : notes.length === 0 ? (
          <div className="text-center py-8 px-4">
            <div className="w-10 h-10 rounded-full bg-surface-2 flex items-center justify-center mx-auto mb-3">
              <Icon name="bookmark" size={18} className="text-text-muted" />
            </div>
            <p className="text-xs text-text-secondary mb-1">
              {scope === "shared" ? "No shared queries yet" : "No saved queries yet"}
            </p>
            <p className="text-[11px] text-text-muted leading-relaxed">
              {scope === "shared"
                ? "When team members share their queries, they will appear here."
                : "When the agent returns SQL results, click the bookmark icon to save them here for quick access."}
            </p>
          </div>
        ) : (
          notes.map((note) => <NoteCard key={note.id} note={note} />)
        )}
      </div>
    </aside>
  );
}
