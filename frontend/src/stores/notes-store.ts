import { create } from "zustand";
import type { SavedNote } from "@/lib/api";
import { api } from "@/lib/api";
import { toast } from "@/stores/toast-store";

function persistOpen(value: boolean) {
  if (typeof window === "undefined") return;
  localStorage.setItem("notes_panel_open", String(value));
}

function getPersistedOpen(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem("notes_panel_open") === "true";
}

type NoteScope = "mine" | "shared" | "all";

interface NotesState {
  notes: SavedNote[];
  isOpen: boolean;
  isLoading: boolean;
  loadedProjectId: string | null;
  scope: NoteScope;

  setOpen: (open: boolean) => void;
  toggleOpen: () => void;
  setScope: (scope: NoteScope) => void;
  setNotes: (notes: SavedNote[]) => void;
  addNote: (note: SavedNote) => void;
  removeNote: (id: string) => void;
  updateNote: (id: string, data: Partial<SavedNote>) => void;
  loadNotes: (projectId: string, scope?: NoteScope) => Promise<void>;
  clear: () => void;
  hasSqlQuery: (sql: string) => boolean;
}

export const useNotesStore = create<NotesState>((set, get) => ({
  notes: [],
  isOpen: getPersistedOpen(),
  isLoading: false,
  loadedProjectId: null,
  scope: "all",

  setOpen: (open) => {
    persistOpen(open);
    set({ isOpen: open });
  },
  toggleOpen: () => {
    const next = !get().isOpen;
    persistOpen(next);
    set({ isOpen: next });
  },
  setScope: (scope) => {
    set({ scope });
    const pid = get().loadedProjectId;
    if (pid) get().loadNotes(pid, scope);
  },
  setNotes: (notes) => set({ notes }),
  addNote: (note) => set((s) => ({ notes: [note, ...s.notes] })),
  removeNote: (id) => set((s) => ({ notes: s.notes.filter((n) => n.id !== id) })),
  updateNote: (id, data) =>
    set((s) => ({
      notes: s.notes.map((n) => (n.id === id ? { ...n, ...data } : n)),
    })),
  loadNotes: async (projectId, scope?) => {
    const effectiveScope = scope ?? get().scope;
    set({ isLoading: true, notes: [], loadedProjectId: projectId });
    try {
      const notes = await api.notes.list(projectId, effectiveScope);
      if (get().loadedProjectId === projectId) {
        set({ notes });
      }
    } catch {
      if (get().loadedProjectId === projectId) {
        set({ notes: [] });
        toast("Failed to load saved queries", "error");
      }
    } finally {
      if (get().loadedProjectId === projectId) {
        set({ isLoading: false });
      }
    }
  },
  clear: () => set({ notes: [], loadedProjectId: null }),
  hasSqlQuery: (sql) => get().notes.some((n) => n.sql_query === sql),
}));
