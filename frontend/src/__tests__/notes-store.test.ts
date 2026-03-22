import { describe, it, expect, vi, beforeEach } from "vitest";
import type { SavedNote } from "@/lib/api";
import { useNotesStore } from "@/stores/notes-store";

vi.mock("@/lib/api", () => ({
  api: {
    notes: {
      list: vi.fn(),
    },
  },
}));

import { api } from "@/lib/api";

const mockedList = api.notes.list as ReturnType<typeof vi.fn>;

function makeNote(overrides: Partial<SavedNote> = {}): SavedNote {
  return {
    id: "n1",
    project_id: "proj1",
    user_id: "u1",
    connection_id: null,
    title: "Test note",
    comment: null,
    sql_query: "SELECT 1",
    answer_text: null,
    visualization_json: null,
    last_result_json: null,
    is_shared: false,
    shared_by: null,
    last_executed_at: null,
    created_at: null,
    updated_at: null,
    ...overrides,
  };
}

const initial = {
  notes: [],
  isOpen: false,
  isLoading: false,
  loadedProjectId: null,
  scope: "all" as const,
};

describe("notes-store", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    useNotesStore.setState(initial);
  });

  it("has correct initial state", () => {
    const s = useNotesStore.getState();
    expect(s.notes).toEqual([]);
    expect(s.isOpen).toBe(false);
    expect(s.isLoading).toBe(false);
    expect(s.loadedProjectId).toBeNull();
    expect(s.scope).toBe("all");
  });

  it("setOpen updates isOpen and persists to localStorage", () => {
    useNotesStore.getState().setOpen(true);
    expect(useNotesStore.getState().isOpen).toBe(true);
    expect(localStorage.getItem("notes_panel_open")).toBe("true");

    useNotesStore.getState().setOpen(false);
    expect(useNotesStore.getState().isOpen).toBe(false);
    expect(localStorage.getItem("notes_panel_open")).toBe("false");
  });

  it("toggleOpen toggles isOpen", () => {
    expect(useNotesStore.getState().isOpen).toBe(false);
    useNotesStore.getState().toggleOpen();
    expect(useNotesStore.getState().isOpen).toBe(true);
    useNotesStore.getState().toggleOpen();
    expect(useNotesStore.getState().isOpen).toBe(false);
  });

  it("setScope changes scope and triggers loadNotes when project loaded", async () => {
    mockedList.mockResolvedValueOnce([]);
    useNotesStore.setState({ loadedProjectId: "proj1" });

    useNotesStore.getState().setScope("shared");
    expect(useNotesStore.getState().scope).toBe("shared");
    expect(mockedList).toHaveBeenCalledWith("proj1", "shared");
  });

  it("setScope does not trigger loadNotes when no project loaded", () => {
    useNotesStore.getState().setScope("mine");
    expect(useNotesStore.getState().scope).toBe("mine");
    expect(mockedList).not.toHaveBeenCalled();
  });

  it("setNotes replaces notes array", () => {
    const notes = [makeNote({ id: "a" }), makeNote({ id: "b" })];
    useNotesStore.getState().setNotes(notes);
    expect(useNotesStore.getState().notes).toHaveLength(2);
    expect(useNotesStore.getState().notes[0].id).toBe("a");
  });

  it("addNote prepends to notes", () => {
    useNotesStore.setState({ notes: [makeNote({ id: "existing" })] });
    useNotesStore.getState().addNote(makeNote({ id: "new" }));
    const { notes } = useNotesStore.getState();
    expect(notes).toHaveLength(2);
    expect(notes[0].id).toBe("new");
    expect(notes[1].id).toBe("existing");
  });

  it("removeNote filters by id", () => {
    useNotesStore.setState({
      notes: [makeNote({ id: "a" }), makeNote({ id: "b" }), makeNote({ id: "c" })],
    });
    useNotesStore.getState().removeNote("b");
    const ids = useNotesStore.getState().notes.map((n) => n.id);
    expect(ids).toEqual(["a", "c"]);
  });

  it("updateNote merges partial data", () => {
    useNotesStore.setState({ notes: [makeNote({ id: "n1", title: "Old" })] });
    useNotesStore.getState().updateNote("n1", { title: "New", comment: "Updated" });
    const note = useNotesStore.getState().notes[0];
    expect(note.title).toBe("New");
    expect(note.comment).toBe("Updated");
    expect(note.sql_query).toBe("SELECT 1");
  });

  it("updateNote leaves other notes unchanged", () => {
    useNotesStore.setState({
      notes: [makeNote({ id: "a", title: "A" }), makeNote({ id: "b", title: "B" })],
    });
    useNotesStore.getState().updateNote("a", { title: "A2" });
    expect(useNotesStore.getState().notes[1].title).toBe("B");
  });

  it("loadNotes success populates notes", async () => {
    const fetched = [makeNote({ id: "x" }), makeNote({ id: "y" })];
    mockedList.mockResolvedValueOnce(fetched);

    await useNotesStore.getState().loadNotes("proj1");

    const s = useNotesStore.getState();
    expect(s.notes).toEqual(fetched);
    expect(s.loadedProjectId).toBe("proj1");
    expect(s.isLoading).toBe(false);
  });

  it("loadNotes uses effective scope from parameter", async () => {
    mockedList.mockResolvedValueOnce([]);
    await useNotesStore.getState().loadNotes("proj1", "shared");
    expect(mockedList).toHaveBeenCalledWith("proj1", "shared");
  });

  it("loadNotes uses store scope when parameter omitted", async () => {
    mockedList.mockResolvedValueOnce([]);
    useNotesStore.setState({ scope: "mine" });
    await useNotesStore.getState().loadNotes("proj1");
    expect(mockedList).toHaveBeenCalledWith("proj1", "mine");
  });

  it("loadNotes error sets empty notes", async () => {
    mockedList.mockRejectedValueOnce(new Error("Network error"));
    await useNotesStore.getState().loadNotes("proj1");

    const s = useNotesStore.getState();
    expect(s.notes).toEqual([]);
    expect(s.isLoading).toBe(false);
  });

  it("clear resets notes and loadedProjectId", () => {
    useNotesStore.setState({ notes: [makeNote()], loadedProjectId: "proj1" });
    useNotesStore.getState().clear();
    expect(useNotesStore.getState().notes).toEqual([]);
    expect(useNotesStore.getState().loadedProjectId).toBeNull();
  });

  it("hasSqlQuery returns true for matching query", () => {
    useNotesStore.setState({ notes: [makeNote({ sql_query: "SELECT * FROM users" })] });
    expect(useNotesStore.getState().hasSqlQuery("SELECT * FROM users")).toBe(true);
  });

  it("hasSqlQuery returns false for non-matching query", () => {
    useNotesStore.setState({ notes: [makeNote({ sql_query: "SELECT 1" })] });
    expect(useNotesStore.getState().hasSqlQuery("SELECT 2")).toBe(false);
  });

  it("hasSqlQuery returns false when notes are empty", () => {
    expect(useNotesStore.getState().hasSqlQuery("SELECT 1")).toBe(false);
  });
});
