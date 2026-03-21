"use client";

import { useState, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import { api } from "@/lib/api";
import { toast } from "@/stores/toast-store";

interface SQLExplainerProps {
  sql: string;
  projectId: string;
  dbType?: string;
}

export function SQLExplainer({ sql, projectId, dbType }: SQLExplainerProps) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [explanation, setExplanation] = useState<string | null>(null);
  const [complexity, setComplexity] = useState<string | null>(null);

  const handleToggle = useCallback(async () => {
    if (open) {
      setOpen(false);
      return;
    }
    setOpen(true);
    if (explanation) return;

    setLoading(true);
    try {
      const res = await api.chat.explainSql(sql, projectId, dbType);
      setExplanation(res.explanation);
      setComplexity(res.complexity);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to explain SQL", "error");
      setOpen(false);
    } finally {
      setLoading(false);
    }
  }, [open, explanation, sql, projectId, dbType]);

  const handleCopy = useCallback(() => {
    if (!explanation) return;
    navigator.clipboard.writeText(explanation).then(
      () => toast("Copied to clipboard", "info"),
      () => toast("Failed to copy", "error"),
    );
  }, [explanation]);

  const complexityColors: Record<string, string> = {
    simple: "bg-emerald-900/30 text-emerald-400",
    moderate: "bg-blue-900/30 text-blue-400",
    complex: "bg-amber-900/30 text-amber-400",
    expert: "bg-red-900/30 text-red-400",
  };

  return (
    <div className="mt-2">
      <button
        onClick={handleToggle}
        className="text-[11px] text-zinc-500 hover:text-zinc-300 transition-colors flex items-center gap-1"
      >
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
        </svg>
        {open ? "Hide explanation" : "Explain SQL"}
      </button>

      {open && (
        <div className="mt-2 p-3 bg-zinc-900/60 border border-zinc-700/50 rounded-lg text-sm">
          {loading ? (
            <div className="flex items-center gap-2 text-zinc-400 text-xs">
              <svg className="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Generating explanation...
            </div>
          ) : (
            <>
              {complexity && (
                <div className="mb-2 flex items-center gap-2">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded font-medium ${complexityColors[complexity] || "bg-zinc-700/50 text-zinc-400"}`}>
                    {complexity.charAt(0).toUpperCase() + complexity.slice(1)}
                  </span>
                  <button
                    onClick={handleCopy}
                    className="text-[10px] text-zinc-500 hover:text-zinc-300 transition-colors ml-auto"
                    title="Copy explanation"
                  >
                    Copy
                  </button>
                </div>
              )}
              {explanation && (
                <div className="text-xs text-zinc-300 leading-relaxed prose prose-invert prose-xs max-w-none">
                  <ReactMarkdown>{explanation}</ReactMarkdown>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );
}
