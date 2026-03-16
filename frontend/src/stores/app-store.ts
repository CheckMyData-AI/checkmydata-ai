import { create } from "zustand";
import type { ChatSession, Connection, Project, SshKey } from "@/lib/api";

interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  query?: string;
  queryExplanation?: string;
  visualization?: Record<string, unknown> | null;
  error?: string | null;
  metadataJson?: string | null;
  stalenessWarning?: string | null;
  timestamp: number;
}

interface AppState {
  sshKeys: SshKey[];
  projects: Project[];
  activeProject: Project | null;
  connections: Connection[];
  activeConnection: Connection | null;
  chatSessions: ChatSession[];
  activeSession: ChatSession | null;
  messages: ChatMessage[];
  isLoading: boolean;
  isThinking: boolean;
  userRole: string | null;

  setSshKeys: (keys: SshKey[]) => void;
  setProjects: (projects: Project[]) => void;
  setActiveProject: (project: Project | null) => void;
  setConnections: (connections: Connection[]) => void;
  setActiveConnection: (connection: Connection | null) => void;
  setChatSessions: (sessions: ChatSession[]) => void;
  setActiveSession: (session: ChatSession | null) => void;
  addMessage: (message: ChatMessage) => void;
  setMessages: (messages: ChatMessage[]) => void;
  clearMessages: () => void;
  setLoading: (loading: boolean) => void;
  setThinking: (thinking: boolean) => void;
  setUserRole: (role: string | null) => void;
}

export const useAppStore = create<AppState>((set) => ({
  sshKeys: [],
  projects: [],
  activeProject: null,
  connections: [],
  activeConnection: null,
  chatSessions: [],
  activeSession: null,
  messages: [],
  isLoading: false,
  isThinking: false,
  userRole: null,

  setSshKeys: (keys) => set({ sshKeys: keys }),
  setProjects: (projects) => set({ projects }),
  setActiveProject: (project) => set({ activeProject: project }),
  setConnections: (connections) => set({ connections }),
  setActiveConnection: (connection) => set({ activeConnection: connection }),
  setChatSessions: (sessions) => set({ chatSessions: sessions }),
  setActiveSession: (session) => set({ activeSession: session }),
  addMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),
  setMessages: (messages) => set({ messages }),
  clearMessages: () => set({ messages: [] }),
  setLoading: (loading) => set({ isLoading: loading }),
  setThinking: (thinking) => set({ isThinking: thinking }),
  setUserRole: (role) => set({ userRole: role }),
}));

export type { ChatMessage };
