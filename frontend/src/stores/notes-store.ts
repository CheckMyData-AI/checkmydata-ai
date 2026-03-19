import { create } from "zustand";
import type { SavedNote } from "@/lib/api";
import { api } from "@/lib/api";

function persistOpen(value: boolean) {
  if (typeof window === "undefined") return;
  localStorage.setItem("notes_panel_open", String(value));
}

function getPersistedOpen(): boolean {
  if (typeof window === "undefined") return false;
  return localStorage.getItem("notes_panel_open") === "true";
}

interface NotesState {
  notes: SavedNote[];
  isOpen: boolean;
  isLoading: boolean;
  loadedProjectId: string | null;

  setOpen: (open: boolean) => void;
  toggleOpen: () => void;
  setNotes: (notes: SavedNote[]) => void;
  addNote: (note: SavedNote) => void;
  removeNote: (id: string) => void;
  updateNote: (id: string, data: Partial<SavedNote>) => void;
  loadNotes: (projectId: string) => Promise<void>;
  clear: () => void;
  hasSqlQuery: (sql: string) => boolean;
}

export const useNotesStore = create<NotesState>((set, get) => ({
  notes: [],
  isOpen: getPersistedOpen(),
  isLoading: false,
  loadedProjectId: null,

  setOpen: (open) => {
    persistOpen(open);
    set({ isOpen: open });
  },
  toggleOpen: () => {
    const next = !get().isOpen;
    persistOpen(next);
    set({ isOpen: next });
  },
  setNotes: (notes) => set({ notes }),
  addNote: (note) => set((s) => ({ notes: [note, ...s.notes] })),
  removeNote: (id) => set((s) => ({ notes: s.notes.filter((n) => n.id !== id) })),
  updateNote: (id, data) =>
    set((s) => ({
      notes: s.notes.map((n) => (n.id === id ? { ...n, ...data } : n)),
    })),
  loadNotes: async (projectId) => {
    set({ isLoading: true, notes: [], loadedProjectId: projectId });
    try {
      const notes = await api.notes.list(projectId);
      if (get().loadedProjectId === projectId) {
        set({ notes });
      }
    } catch {
      if (get().loadedProjectId === projectId) {
        set({ notes: [] });
      }
    } finally {
      set({ isLoading: false });
    }
  },
  clear: () => set({ notes: [], loadedProjectId: null }),
  hasSqlQuery: (sql) => get().notes.some((n) => n.sql_query === sql),
}));
