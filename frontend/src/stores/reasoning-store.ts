import { create } from "zustand";
import type { PlanSummaryData } from "@/components/chat/PlanSummaryCard";

export interface ReasoningStep {
  step: string;
  status: string;
  detail: string;
  agent?: string;
  elapsed_ms?: number;
  timestamp: number;
  extra?: Record<string, unknown>;
}

export interface ReasoningTrace {
  steps: ReasoningStep[];
  planSummary: PlanSummaryData | null;
  thinkingLog: string[];
  startTime: number;
  endTime?: number;
}

const MAX_TRACES = 20;
const MAX_STEPS_PER_TRACE = 200;

interface ReasoningStore {
  panelOpen: boolean;
  activeMessageId: string | null;
  traces: Record<string, ReasoningTrace>;

  openPanel: (messageId: string) => void;
  closePanel: () => void;
  initTrace: (messageId: string) => void;
  addStep: (messageId: string, step: ReasoningStep) => void;
  setPlanSummary: (messageId: string, plan: PlanSummaryData) => void;
  addThinkingLine: (messageId: string, line: string) => void;
  finalizeTrace: (messageId: string) => void;
  clearTrace: (messageId: string) => void;
  clearAllTraces: () => void;
}

export const useReasoningStore = create<ReasoningStore>((set) => ({
  panelOpen: false,
  activeMessageId: null,
  traces: {},

  openPanel: (messageId) => set({ panelOpen: true, activeMessageId: messageId }),
  closePanel: () => set({ panelOpen: false, activeMessageId: null }),

  initTrace: (messageId) =>
    set((state) => {
      const entries = Object.entries(state.traces);
      let base = state.traces;
      if (entries.length >= MAX_TRACES) {
        const sorted = entries.sort((a, b) => a[1].startTime - b[1].startTime);
        const toRemove = sorted.slice(0, entries.length - MAX_TRACES + 1);
        base = { ...state.traces };
        for (const [key] of toRemove) delete base[key];
      }
      return {
        traces: {
          ...base,
          [messageId]: {
            steps: [],
            planSummary: null,
            thinkingLog: [],
            startTime: Date.now(),
          },
        },
      };
    }),

  addStep: (messageId, step) =>
    set((state) => {
      const trace = state.traces[messageId];
      if (!trace) return state;
      const steps = trace.steps.length >= MAX_STEPS_PER_TRACE
        ? [...trace.steps.slice(-MAX_STEPS_PER_TRACE + 1), step]
        : [...trace.steps, step];
      return {
        traces: {
          ...state.traces,
          [messageId]: { ...trace, steps },
        },
      };
    }),

  setPlanSummary: (messageId, plan) =>
    set((state) => {
      const trace = state.traces[messageId];
      if (!trace) return state;
      return {
        traces: {
          ...state.traces,
          [messageId]: { ...trace, planSummary: plan },
        },
      };
    }),

  addThinkingLine: (messageId, line) =>
    set((state) => {
      const trace = state.traces[messageId];
      if (!trace) return state;
      const log = [...trace.thinkingLog, line];
      return {
        traces: {
          ...state.traces,
          [messageId]: {
            ...trace,
            thinkingLog: log.length > 100 ? log.slice(-100) : log,
          },
        },
      };
    }),

  finalizeTrace: (messageId) =>
    set((state) => {
      const trace = state.traces[messageId];
      if (!trace) return state;
      return {
        traces: {
          ...state.traces,
          [messageId]: { ...trace, endTime: Date.now() },
        },
      };
    }),

  clearTrace: (messageId) =>
    set((state) => {
      const { [messageId]: _, ...rest } = state.traces;
      return { traces: rest };
    }),

  clearAllTraces: () =>
    set({ traces: {}, panelOpen: false, activeMessageId: null }),
}));
