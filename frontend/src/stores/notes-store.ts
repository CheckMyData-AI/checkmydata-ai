import { create } from "zustand";
import type { SavedNote } from "@/lib/api";
import { api } from "@/lib/api";
import { toast } from "@/stores/toast-store";

function persistOpen(value: boolean) {
  try {
    if (typeof window !== "undefined") localStorage.setItem("notes_panel_open", String(value));
  } catch { /* storage unavailable */ }
}

function getPersistedOpen(): boolean {
  try {
    if (typeof window === "undefined") return false;
    return localStorage.getItem("notes_panel_open") === "true";
  } catch {
    return false;
  }
}

type NoteScope = "mine" | "shared" | "all";

interface NotesState {
  notes: SavedNote[];
  isOpen: boolean;
  isLoading: boolean;
  /**
   * FE-07: why the list is empty. `loadNotes` set `notes: []` on failure and raised
   * a toast, and the panel had exactly two states — loading and empty — so a failed
   * fetch rendered as the affirmative claim that the user has saved nothing,
   * complete with the onboarding hint explaining how to save their first one. The
   * toast is gone in ten seconds; the false sentence is not.
   */
  loadError: string | null;
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
  loadError: null,
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
    set({ isLoading: true, notes: [], loadError: null, loadedProjectId: projectId });
    try {
      const notes = await api.notes.list(projectId, effectiveScope);
      if (get().loadedProjectId === projectId) {
        set({ notes, loadError: null });
      }
    } catch (err) {
      if (get().loadedProjectId === projectId) {
        set({
          notes: [],
          loadError: err instanceof Error ? err.message : "Failed to load saved queries",
        });
        toast("Failed to load saved queries", "error");
      }
    } finally {
      if (get().loadedProjectId === projectId) {
        set({ isLoading: false });
      }
    }
  },
  clear: () => set({ notes: [], loadError: null, loadedProjectId: null }),
  hasSqlQuery: (sql) => get().notes.some((n) => n.sql_query === sql),
}));
