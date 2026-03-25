import { create } from "zustand";
import type { ChatSession, Connection, Project, SshKey } from "@/lib/api";

type ChatMode = "full" | "knowledge_only";

export interface RawResult {
  columns: string[];
  rows: unknown[][];
  total_rows: number;
}

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
  responseType?: "text" | "sql_result" | "knowledge" | "error" | "clarification_request" | "stage_checkpoint" | "stage_failed" | "session_continuation";
  userRating?: number | null;
  toolCallsJson?: string | null;
  rawResult?: RawResult | null;
  timestamp: number;
  clarificationData?: {
    question: string;
    question_type: "yes_no" | "multiple_choice" | "numeric_range" | "free_text";
    options?: string[];
    context?: string;
  } | null;
  verificationStatus?: "verified" | "unverified" | "flagged" | null;
  isRetryable?: boolean;
}

interface ToolCallEvent {
  step: string;
  status: string;
  detail: string;
}

function persistId(key: string, value: string | null) {
  if (typeof window === "undefined") return;
  try {
    if (value) localStorage.setItem(key, value);
    else localStorage.removeItem(key);
  } catch {
    /* QuotaExceededError — IDs persist only for this session */
  }
}

export function getPersistedId(key: string): string | null {
  try {
    if (typeof window === "undefined") return null;
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

interface ReadinessCacheEntry {
  ready: boolean;
  checkedAt: number;
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
  chatMode: ChatMode;
  activeToolCalls: ToolCallEvent[];
  restoringState: boolean;
  rulesVersion: number;
  focusSidebarSection: string | null;
  triggerProjectEdit: boolean;
  readinessCache: Record<string, ReadinessCacheEntry>;
  sessionTokens: number;
  sessionCost: number;

  setSshKeys: (keys: SshKey[]) => void;
  setProjects: (projects: Project[]) => void;
  setActiveProject: (project: Project | null) => void;
  setConnections: (connections: Connection[]) => void;
  setActiveConnection: (connection: Connection | null) => void;
  setChatSessions: (sessions: ChatSession[]) => void;
  setActiveSession: (session: ChatSession | null) => void;
  addMessage: (message: ChatMessage) => void;
  setMessages: (messages: ChatMessage[]) => void;
  updateMessageId: (oldId: string, newId: string) => void;
  clearMessages: () => void;
  setLoading: (loading: boolean) => void;
  setThinking: (thinking: boolean) => void;
  setUserRole: (role: string | null) => void;
  setChatMode: (mode: ChatMode) => void;
  addToolCall: (event: ToolCallEvent) => void;
  clearToolCalls: () => void;
  setRestoringState: (v: boolean) => void;
  bumpRulesVersion: () => void;
  setFocusSidebarSection: (section: string | null) => void;
  setTriggerProjectEdit: (v: boolean) => void;
  setReadinessCache: (projectId: string, entry: ReadinessCacheEntry) => void;
  clearReadinessCache: (projectId: string) => void;
  addSessionUsage: (tokens: number, cost: number) => void;
  resetSessionUsage: () => void;
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
  chatMode: "full",
  activeToolCalls: [],
  restoringState: false,
  rulesVersion: 0,
  focusSidebarSection: null,
  triggerProjectEdit: false,
  readinessCache: {},
  sessionTokens: 0,
  sessionCost: 0,

  setSshKeys: (keys) => set({ sshKeys: keys }),
  setProjects: (projects) => set({ projects }),
  setActiveProject: (project) => {
    persistId("active_project_id", project?.id ?? null);
    if (!project) {
      persistId("active_connection_id", null);
      persistId("active_session_id", null);
    }
    set({ activeProject: project });
  },
  setConnections: (connections) => set({ connections }),
  setActiveConnection: (connection) => {
    persistId("active_connection_id", connection?.id ?? null);
    set({ activeConnection: connection });
  },
  setChatSessions: (sessions) => set({ chatSessions: sessions }),
  setActiveSession: (session) => {
    persistId("active_session_id", session?.id ?? null);
    set({ activeSession: session });
  },
  addMessage: (message) =>
    set((state) => ({ messages: [...state.messages, message] })),
  setMessages: (messages) => set({ messages }),
  updateMessageId: (oldId, newId) =>
    set((state) => ({
      messages: state.messages.map((m) =>
        m.id === oldId ? { ...m, id: newId } : m,
      ),
    })),
  clearMessages: () => set({ messages: [] }),
  setLoading: (loading) => set({ isLoading: loading }),
  setThinking: (thinking) => set({ isThinking: thinking }),
  setUserRole: (role) => set({ userRole: role }),
  setChatMode: (mode) => set({ chatMode: mode }),
  addToolCall: (event) =>
    set((state) => ({ activeToolCalls: [...state.activeToolCalls, event] })),
  clearToolCalls: () => set({ activeToolCalls: [] }),
  setRestoringState: (v) => set({ restoringState: v }),
  bumpRulesVersion: () => set((state) => ({ rulesVersion: state.rulesVersion + 1 })),
  setFocusSidebarSection: (section) => set({ focusSidebarSection: section }),
  setTriggerProjectEdit: (v) => set({ triggerProjectEdit: v }),
  setReadinessCache: (projectId, entry) =>
    set((state) => ({
      readinessCache: { ...state.readinessCache, [projectId]: entry },
    })),
  clearReadinessCache: (projectId) =>
    set((state) => {
      const { [projectId]: _, ...rest } = state.readinessCache;
      return { readinessCache: rest };
    }),
  addSessionUsage: (tokens, cost) =>
    set((state) => ({
      sessionTokens: state.sessionTokens + tokens,
      sessionCost: state.sessionCost + cost,
    })),
  resetSessionUsage: () => set({ sessionTokens: 0, sessionCost: 0 }),
}));

export type { ChatMessage, ChatMode, ToolCallEvent };
