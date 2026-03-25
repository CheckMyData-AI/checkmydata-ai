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
  column_format: "bg-accent-muted text-accent border-border-default",
  missing_filter: "bg-warning-muted text-warning border-border-default",
  wrong_join: "bg-error-muted text-error border-border-default",
  wrong_table: "bg-error-muted text-error border-border-default",
  aggregation_error: "bg-warning-muted text-warning border-border-default",
  timezone_issue: "bg-accent-muted text-accent border-border-default",
  currency_unit: "bg-success-muted text-success border-border-default",
  other: "bg-surface-3 text-text-secondary border-border-default",
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
      <div className={`p-3 rounded-xl border ${categoryColor}`}>
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
          <div className="text-[10px] font-medium text-error mb-1">Original Query</div>
          <pre className="p-2 rounded bg-error-muted border border-border-default text-[10px] text-text-secondary overflow-x-auto max-h-32">
            {originalQuery || "N/A"}
          </pre>
        </div>
        <div className="min-w-0">
          <div className="text-[10px] font-medium text-success mb-1">Corrected Query</div>
          <pre className="p-2 rounded bg-success-muted border border-border-default text-[10px] text-text-primary overflow-x-auto max-h-32">
            {correctedQuery || "Generating..."}
          </pre>
        </div>
      </div>
    </div>
  );
}
