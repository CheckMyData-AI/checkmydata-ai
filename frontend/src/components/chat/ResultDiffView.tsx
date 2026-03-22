"use client";

interface ResultDiffViewProps {
  originalQuery: string;
  correctedQuery: string;
  rootCause: string;
  rootCauseCategory: string;
}

const CATEGORY_LABELS: Record<string, string> = {
  column_format: "Column Format Issue",
  missing_filter: "Missing Filter",
  wrong_join: "Incorrect JOIN",
  wrong_table: "Wrong Table",
  aggregation_error: "Aggregation Error",
  timezone_issue: "Timezone Issue",
  currency_unit: "Currency/Unit Mismatch",
  other: "Other Issue",
};

const CATEGORY_COLORS: Record<string, string> = {
  column_format: "bg-purple-900/30 text-purple-400 border-purple-800/30",
  missing_filter: "bg-amber-900/30 text-amber-400 border-amber-800/30",
  wrong_join: "bg-red-900/30 text-red-400 border-red-800/30",
  wrong_table: "bg-red-900/30 text-red-400 border-red-800/30",
  aggregation_error: "bg-orange-900/30 text-orange-400 border-orange-800/30",
  timezone_issue: "bg-blue-900/30 text-blue-400 border-blue-800/30",
  currency_unit: "bg-emerald-900/30 text-emerald-400 border-emerald-800/30",
  other: "bg-zinc-700/30 text-zinc-400 border-zinc-600/30",
};

export function ResultDiffView({
  originalQuery,
  correctedQuery,
  rootCause,
  rootCauseCategory,
}: ResultDiffViewProps) {
  const categoryLabel = CATEGORY_LABELS[rootCauseCategory] ?? "Issue Found";
  const categoryColor = CATEGORY_COLORS[rootCauseCategory] ?? CATEGORY_COLORS.other;

  return (
    <div className="space-y-3">
      {/* Root cause */}
      <div className={`p-3 rounded-lg border ${categoryColor}`}>
        <div className="flex items-center gap-2 mb-1.5">
          <span className={`text-[10px] px-1.5 py-0.5 rounded border ${categoryColor}`}>
            {categoryLabel}
          </span>
        </div>
        <p className="text-xs break-words">{rootCause}</p>
      </div>

      {/* Queries comparison */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
        <div className="min-w-0">
          <div className="text-[10px] font-medium text-red-400 mb-1">Original Query</div>
          <pre className="p-2 rounded bg-red-950/20 border border-red-900/20 text-[10px] text-zinc-400 overflow-x-auto max-h-32">
            {originalQuery || "N/A"}
          </pre>
        </div>
        <div className="min-w-0">
          <div className="text-[10px] font-medium text-emerald-400 mb-1">Corrected Query</div>
          <pre className="p-2 rounded bg-emerald-950/20 border border-emerald-900/20 text-[10px] text-zinc-300 overflow-x-auto max-h-32">
            {correctedQuery || "Generating..."}
          </pre>
        </div>
      </div>
    </div>
  );
}
