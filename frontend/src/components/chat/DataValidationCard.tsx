"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { toast } from "@/stores/toast-store";

interface DataValidationCardProps {
  messageId: string;
  query: string;
  sessionId: string;
}

export function DataValidationCard({ messageId, query, sessionId }: DataValidationCardProps) {
  const [verdict, setVerdict] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);
  const [expectedValue, setExpectedValue] = useState("");
  const [rejectionReason, setRejectionReason] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const handleQuickAction = async (v: "confirmed" | "approximate" | "unknown") => {
    await submitValidation(v);
  };

  const handleReject = () => {
    setShowForm(true);
  };

  const submitValidation = async (v: string, reason?: string, expected?: string) => {
    const { activeProject, activeConnection } = useAppStore.getState();
    if (!activeProject) return;

    setSubmitting(true);
    try {
      await api.dataValidation.validateData({
        connection_id: activeConnection?.id ?? "",
        session_id: sessionId,
        message_id: messageId,
        query,
        verdict: v,
        user_expected_value: expected || undefined,
        rejection_reason: reason || undefined,
        project_id: activeProject.id,
      });
      setVerdict(v);
      setShowForm(false);
      toast(
        v === "confirmed" ? "Data confirmed!" : v === "rejected" ? "Feedback recorded" : "Noted",
        "info"
      );
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to submit", "error");
    } finally {
      setSubmitting(false);
    }
  };

  if (verdict) {
    const labels: Record<string, string> = {
      confirmed: "Confirmed accurate",
      approximate: "Approximately correct",
      rejected: "Flagged for review",
      unknown: "Will check later",
    };
    const colors: Record<string, string> = {
      confirmed: "text-success",
      approximate: "text-warning",
      rejected: "text-error",
      unknown: "text-text-secondary",
    };
    return (
      <div className="mt-2 flex items-center gap-1.5 text-[11px]">
        <span className={colors[verdict] ?? "text-text-secondary"}>
          {labels[verdict] ?? verdict}
        </span>
      </div>
    );
  }

  return (
    <div className="mt-3 p-3 rounded-xl border border-border-default bg-surface-2">
      <p className="text-xs text-text-secondary mb-2">Do these numbers look right?</p>

      {!showForm ? (
        <div className="flex flex-wrap gap-1.5">
          <button
            onClick={() => handleQuickAction("confirmed")}
            disabled={submitting}
            className="px-2.5 py-1 rounded text-[11px] font-medium bg-success-muted text-success border border-border-default hover:bg-success-muted transition-colors disabled:opacity-50"
          >
            Looks correct
          </button>
          <button
            onClick={handleReject}
            disabled={submitting}
            className="px-2.5 py-1 rounded text-[11px] font-medium bg-warning-muted text-warning border border-border-default hover:bg-warning-muted transition-colors disabled:opacity-50"
          >
            Something&apos;s off
          </button>
          <button
            onClick={() => handleQuickAction("unknown")}
            disabled={submitting}
            className="px-2.5 py-1 rounded text-[11px] text-text-tertiary hover:text-text-primary transition-colors disabled:opacity-50"
          >
            Check later
          </button>
        </div>
      ) : (
        <div className="space-y-2">
          <input
            type="text"
            value={expectedValue}
            onChange={(e) => setExpectedValue(e.target.value)}
            placeholder="What did you expect? (optional)"
            maxLength={200}
            aria-label="Expected value"
            className="w-full px-2.5 py-1.5 rounded text-xs bg-surface-1 border border-border-default text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent"
          />
          <input
            type="text"
            value={rejectionReason}
            onChange={(e) => setRejectionReason(e.target.value)}
            placeholder="What seems wrong? (optional)"
            maxLength={500}
            aria-label="Rejection reason"
            className="w-full px-2.5 py-1.5 rounded text-xs bg-surface-1 border border-border-default text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent"
          />
          <div className="flex gap-1.5">
            <button
              onClick={() => submitValidation("rejected", rejectionReason, expectedValue)}
              disabled={submitting}
              className="px-2.5 py-1 rounded text-[11px] font-medium bg-error-muted text-error border border-border-default hover:bg-error-muted transition-colors disabled:opacity-50"
            >
              {submitting ? "Submitting..." : "Submit feedback"}
            </button>
            <button
              onClick={() => setShowForm(false)}
              className="px-2.5 py-1 rounded text-[11px] text-text-tertiary hover:text-text-primary transition-colors"
            >
              Cancel
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
