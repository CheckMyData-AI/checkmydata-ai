"use client";

import { useEffect } from "react";
import { useNotesStore } from "@/stores/notes-store";
import { useAppStore } from "@/stores/app-store";
import { NoteCard } from "./NoteCard";
import { Icon } from "@/components/ui/Icon";

export function NotesPanel() {
  const { notes, isOpen, isLoading, setOpen, loadNotes } = useNotesStore();
  const activeProject = useAppStore((s) => s.activeProject);

  useEffect(() => {
    if (activeProject) {
      loadNotes(activeProject.id);
    } else {
      useNotesStore.getState().clear();
    }
  }, [activeProject?.id, loadNotes]);

  if (!activeProject || !isOpen) return null;

  return (
    <aside className="shrink-0 w-80 border-l border-border-subtle bg-surface-0 flex flex-col h-full overflow-hidden transition-all duration-200 ease-out">
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
        <button
          onClick={() => setOpen(false)}
          aria-label="Close notes panel"
          className="p-1 rounded text-text-muted hover:text-text-secondary hover:bg-surface-2 transition-colors"
        >
          <Icon name="x" size={14} />
        </button>
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
              No saved queries yet
            </p>
            <p className="text-[11px] text-text-muted leading-relaxed">
              When the agent returns SQL results, click the bookmark icon to save them here for quick access.
            </p>
          </div>
        ) : (
          notes.map((note) => <NoteCard key={note.id} note={note} />)
        )}
      </div>
    </aside>
  );
}
