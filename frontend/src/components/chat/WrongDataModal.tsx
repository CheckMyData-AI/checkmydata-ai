"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { toast } from "@/stores/toast-store";
import { InvestigationProgress } from "./InvestigationProgress";
import { ResultDiffView } from "./ResultDiffView";

const COMPLAINT_TYPES = [
  { id: "numbers_too_high", label: "Numbers too high", icon: "↑" },
  { id: "numbers_too_low", label: "Numbers too low", icon: "↓" },
  { id: "wrong_time_period", label: "Wrong time period", icon: "📅" },
  { id: "missing_data", label: "Missing data", icon: "∅" },
  { id: "wrong_categories", label: "Wrong categories", icon: "🏷" },
  { id: "completely_wrong", label: "Completely wrong", icon: "✕" },
] as const;

interface WrongDataModalProps {
  messageId: string;
  query: string;
  sessionId: string;
  resultColumns?: string[];
  onClose: () => void;
}

type Step = "collect" | "investigating" | "results";

export function WrongDataModal({
  messageId,
  query,
  sessionId,
  resultColumns = [],
  onClose,
}: WrongDataModalProps) {
  const [step, setStep] = useState<Step>("collect");
  const [complaintType, setComplaintType] = useState("");
  const [expectedValue, setExpectedValue] = useState("");
  const [problematicColumn, setProblematicColumn] = useState("");
  const [investigationId, setInvestigationId] = useState<string | null>(null);
  const [investigation, setInvestigation] = useState<Record<string, unknown> | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const mountedRef = useRef(true);
  const dialogRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (e.key === "Tab" && dialogRef.current) {
        const focusable = dialogRef.current.querySelectorAll<HTMLElement>(
          'button:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
        );
        if (focusable.length === 0) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (e.shiftKey && document.activeElement === first) {
          e.preventDefault();
          last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
          e.preventDefault();
          first.focus();
        }
      }
    };
    document.addEventListener("keydown", handleKeyDown);
    return () => document.removeEventListener("keydown", handleKeyDown);
  }, [onClose]);

  useEffect(() => {
    dialogRef.current?.focus();
  }, []);

  const pollInvestigation = useCallback(async (id: string) => {
    const maxAttempts = 30;
    for (let i = 0; i < maxAttempts; i++) {
      await new Promise((r) => setTimeout(r, 2000));
      if (!mountedRef.current) return;
      try {
        const inv = await api.dataValidation.getInvestigation(id);
        if (!mountedRef.current) return;
        setInvestigation(inv);
        if (inv.status === "presenting_fix" || inv.status === "resolved" || inv.status === "failed") {
          setStep("results");
          return;
        }
      } catch {
        break;
      }
    }
  }, []);

  const handleStartInvestigation = async () => {
    const { activeProject, activeConnection } = useAppStore.getState();
    if (!activeProject || !complaintType) return;

    setSubmitting(true);
    try {
      const res = await api.dataValidation.startInvestigation({
        project_id: activeProject.id,
        connection_id: activeConnection?.id ?? "",
        session_id: sessionId,
        message_id: messageId,
        complaint_type: complaintType,
        complaint_detail: undefined,
        expected_value: expectedValue || undefined,
        problematic_column: problematicColumn || undefined,
      });
      if (!mountedRef.current) return;
      setInvestigationId(res.investigation_id);
      setStep("investigating");
      pollInvestigation(res.investigation_id);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to start investigation", "error");
    } finally {
      if (mountedRef.current) setSubmitting(false);
    }
  };

  const [confirming, setConfirming] = useState(false);

  const handleConfirmFix = async (accepted: boolean) => {
    if (!investigationId || confirming) return;
    const { activeProject } = useAppStore.getState();
    if (!activeProject) return;

    setConfirming(true);
    try {
      await api.dataValidation.confirmFix(investigationId, {
        accepted,
        project_id: activeProject.id,
      });
      if (accepted) {
        toast("Fix accepted! Memory updated.", "info");
        onClose();
      } else {
        setStep("collect");
        setInvestigation(null);
      }
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to confirm", "error");
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div ref={dialogRef} role="dialog" aria-modal="true" aria-label="Report Incorrect Data" tabIndex={-1} className="w-full max-w-lg mx-4 bg-zinc-900 rounded-xl border border-zinc-700/50 shadow-2xl max-h-[80vh] overflow-y-auto focus:outline-none">
        {/* Header */}
        <div className="flex items-center justify-between p-4 border-b border-zinc-800">
          <h3 className="text-sm font-semibold text-zinc-200">Report Incorrect Data</h3>
          <button onClick={onClose} aria-label="Close dialog" className="text-zinc-500 hover:text-zinc-300 transition-colors p-1 rounded hover:bg-zinc-800 min-w-[28px] min-h-[28px] flex items-center justify-center">
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <div className="p-4">
          {/* Step 1: Collect */}
          {step === "collect" && (
            <div className="space-y-4">
              <div>
                <p className="text-xs text-zinc-400 mb-2">What seems wrong?</p>
                <div className="grid grid-cols-2 gap-2">
                  {COMPLAINT_TYPES.map((ct) => (
                    <button
                      key={ct.id}
                      onClick={() => setComplaintType(ct.id)}
                      className={`p-2.5 rounded-lg text-left text-xs border transition-colors ${
                        complaintType === ct.id
                          ? "border-amber-600 bg-amber-900/20 text-amber-300"
                          : "border-zinc-700/50 bg-zinc-800/50 text-zinc-400 hover:bg-zinc-800"
                      }`}
                    >
                      <span className="text-sm mr-1.5">{ct.icon}</span>
                      {ct.label}
                    </button>
                  ))}
                </div>
              </div>

              <div>
                <label className="text-xs text-zinc-400 block mb-1">Expected value (optional)</label>
                <input
                  type="text"
                  value={expectedValue}
                  onChange={(e) => setExpectedValue(e.target.value)}
                  placeholder="e.g., ~150,000"
                  className="w-full px-3 py-1.5 rounded-md text-xs bg-zinc-800 border border-zinc-700 text-zinc-200 placeholder:text-zinc-500 focus:outline-none focus:border-amber-600"
                />
              </div>

              {resultColumns.length > 0 && (
                <div>
                  <label className="text-xs text-zinc-400 block mb-1">Which column? (optional)</label>
                  <select
                    value={problematicColumn}
                    onChange={(e) => setProblematicColumn(e.target.value)}
                    className="w-full px-3 py-1.5 rounded-md text-xs bg-zinc-800 border border-zinc-700 text-zinc-200 focus:outline-none focus:border-amber-600"
                  >
                    <option value="">All / not sure</option>
                    {resultColumns.map((col) => (
                      <option key={col} value={col}>{col}</option>
                    ))}
                  </select>
                </div>
              )}

              <button
                onClick={handleStartInvestigation}
                disabled={!complaintType || submitting}
                className="w-full py-2 rounded-lg text-xs font-medium bg-amber-600 text-white hover:bg-amber-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {submitting ? "Starting..." : "Start Investigation"}
              </button>
            </div>
          )}

          {/* Step 2: Investigating */}
          {step === "investigating" && (
            <InvestigationProgress investigation={investigation} />
          )}

          {/* Step 3: Results */}
          {step === "results" && investigation && (
            <div className="space-y-4">
              <ResultDiffView
                originalQuery={query}
                correctedQuery={(investigation.corrected_query as string) ?? ""}
                rootCause={(investigation.root_cause as string) ?? "No root cause identified"}
                rootCauseCategory={(investigation.root_cause_category as string) ?? "other"}
              />
              <div className="flex gap-2">
                <button
                  onClick={() => handleConfirmFix(true)}
                  disabled={confirming}
                  className="flex-1 py-2 rounded-lg text-xs font-medium bg-emerald-600 text-white hover:bg-emerald-500 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  {confirming ? "Saving..." : "Accept Fix"}
                </button>
                <button
                  onClick={() => handleConfirmFix(false)}
                  disabled={confirming}
                  className="flex-1 py-2 rounded-lg text-xs font-medium border border-red-800/40 text-red-400 hover:bg-red-900/20 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
                >
                  Still Wrong
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
