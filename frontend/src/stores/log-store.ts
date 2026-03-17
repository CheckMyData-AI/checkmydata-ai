import { create } from "zustand";

const MAX_ENTRIES = 500;

let _counter = 0;

export interface LogEntry {
  id: string;
  timestamp: number;
  pipeline: string;
  workflowId: string;
  step: string;
  status: string;
  detail: string;
  elapsedMs: number | null;
}

interface LogState {
  entries: LogEntry[];
  isOpen: boolean;
  isConnected: boolean;
  unreadCount: number;

  addEntry: (entry: Omit<LogEntry, "id">) => void;
  clear: () => void;
  toggle: () => void;
  setOpen: (open: boolean) => void;
  setConnected: (connected: boolean) => void;
  resetUnread: () => void;
}

export const useLogStore = create<LogState>((set, get) => ({
  entries: [],
  isOpen: false,
  isConnected: false,
  unreadCount: 0,

  addEntry: (entry) => {
    const id = `${entry.timestamp}-${++_counter}`;
    set((state) => {
      const next = [...state.entries, { ...entry, id }];
      if (next.length > MAX_ENTRIES) next.splice(0, next.length - MAX_ENTRIES);
      return {
        entries: next,
        unreadCount: state.isOpen ? 0 : state.unreadCount + 1,
      };
    });
  },

  clear: () => set({ entries: [], unreadCount: 0 }),

  toggle: () => {
    const wasOpen = get().isOpen;
    set({ isOpen: !wasOpen, unreadCount: wasOpen ? get().unreadCount : 0 });
  },

  setOpen: (open) => set({ isOpen: open, unreadCount: open ? 0 : get().unreadCount }),

  setConnected: (connected) => set({ isConnected: connected }),

  resetUnread: () => set({ unreadCount: 0 }),
}));
