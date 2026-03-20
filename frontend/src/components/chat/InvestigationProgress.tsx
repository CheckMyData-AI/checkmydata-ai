"use client";

const INVESTIGATION_STEPS = [
  { key: "analyzing", label: "Analyzing original query" },
  { key: "checking_formats", label: "Checking column formats" },
  { key: "diagnostic_queries", label: "Running diagnostic queries" },
  { key: "comparing", label: "Comparing results" },
  { key: "root_cause", label: "Identifying root cause" },
  { key: "generating_fix", label: "Generating corrected query" },
];

interface InvestigationProgressProps {
  investigation: Record<string, unknown> | null;
}

function getCompletedSteps(investigation: Record<string, unknown> | null): number {
  if (!investigation) return 0;
  const log = (investigation.investigation_log ?? []) as Array<Record<string, unknown>>;
  return Math.min(log.length, INVESTIGATION_STEPS.length);
}

export function InvestigationProgress({ investigation }: InvestigationProgressProps) {
  const completed = getCompletedSteps(investigation);
  const status = investigation?.status as string | undefined;
  const isDone = status === "presenting_fix" || status === "resolved" || status === "failed";

  return (
    <div className="space-y-3">
      <p className="text-xs text-zinc-400">Investigating the issue...</p>
      <div className="space-y-2">
        {INVESTIGATION_STEPS.map((step, idx) => {
          let state: "pending" | "active" | "done" | "error" = "pending";
          if (idx < completed) state = "done";
          else if (idx === completed && !isDone) state = "active";
          else if (isDone && status === "failed" && idx === completed) state = "error";

          return (
            <div key={step.key} className="flex items-center gap-2.5">
              <div className="w-5 h-5 flex items-center justify-center flex-shrink-0">
                {state === "done" && (
                  <svg className="w-4 h-4 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                  </svg>
                )}
                {state === "active" && (
                  <div className="w-3.5 h-3.5 rounded-full border-2 border-blue-400 border-t-transparent animate-spin" />
                )}
                {state === "error" && (
                  <svg className="w-4 h-4 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                )}
                {state === "pending" && (
                  <div className="w-2 h-2 rounded-full bg-zinc-700" />
                )}
              </div>
              <span className={`text-xs ${
                state === "done" ? "text-zinc-300" :
                state === "active" ? "text-blue-400" :
                state === "error" ? "text-red-400" :
                "text-zinc-600"
              }`}>
                {step.label}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
