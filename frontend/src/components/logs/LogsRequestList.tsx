"use client";

import type { LogRequestTrace, LogUser } from "@/lib/api";
import { Icon } from "@/components/ui/Icon";

interface Props {
  items: LogRequestTrace[];
  total: number;
  page: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  selectedTraceId: string | null;
  onSelectTrace: (traceId: string | null) => void;
  statusFilter: string | null;
  onStatusFilter: (status: string | null) => void;
  users?: LogUser[];
  selectedUserId?: string | null;
}

const STATUS_BADGE: Record<string, { bg: string; text: string }> = {
  completed: { bg: "bg-success/10", text: "text-success" },
  failed: { bg: "bg-error/10", text: "text-error" },
  started: { bg: "bg-info/10", text: "text-info" },
};

const TYPE_BADGE: Record<string, string> = {
  sql_result: "text-accent",
  knowledge: "text-info",
  text: "text-text-muted",
  error: "text-error",
  clarification_request: "text-warning",
};

function fmtMs(ms: number | null): string {
  if (ms == null) return "--";
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.round(ms)}ms`;
}

function fmtTime(iso: string | null): string {
  if (!iso) return "--";
  const d = new Date(iso);
  return d.toLocaleString("en-GB", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function LogsRequestList({
  items,
  total,
  page,
  pageSize,
  onPageChange,
  selectedTraceId,
  onSelectTrace,
  statusFilter,
  onStatusFilter,
  users,
  selectedUserId,
}: Props) {
  const usersMap = users
    ? Object.fromEntries(users.map((u) => [u.user_id, u]))
    : {};
  const showUser = !selectedUserId && users && users.length > 0;
  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="flex flex-col h-full">
      <div className="flex items-center gap-2 px-3 py-2 border-b border-border-subtle">
        <span className="text-[10px] text-text-tertiary uppercase tracking-wider">Filter:</span>
        {(["all", "completed", "failed"] as const).map((s) => {
          const active = s === "all" ? !statusFilter : statusFilter === s;
          return (
            <button
              key={s}
              onClick={() => onStatusFilter(s === "all" ? null : s)}
              className={`text-[10px] px-2 py-0.5 rounded-md transition-colors ${
                active
                  ? "bg-accent/10 text-accent font-medium"
                  : "text-text-muted hover:bg-surface-2"
              }`}
            >
              {s === "all" ? "All" : s.charAt(0).toUpperCase() + s.slice(1)}
            </button>
          );
        })}
        <span className="ml-auto text-[10px] text-text-muted tabular-nums">
          {total} result{total !== 1 ? "s" : ""}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {items.length === 0 ? (
          <div className="flex items-center justify-center h-32 text-xs text-text-muted">
            No requests found
          </div>
        ) : (
          items.map((t) => {
            const sb = STATUS_BADGE[t.status] || STATUS_BADGE.started;
            const isSelected = selectedTraceId === t.id;
            return (
              <button
                key={t.id}
                onClick={() => onSelectTrace(isSelected ? null : t.id)}
                className={`w-full text-left px-3 py-2.5 border-b border-border-subtle transition-colors ${
                  isSelected
                    ? "bg-accent/5 border-l-2 border-l-accent"
                    : "hover:bg-surface-1"
                }`}
              >
                <div className="flex items-start gap-2">
                  <div className="flex-1 min-w-0">
                    <p className="text-xs text-text-primary truncate">
                      {t.question || "(empty question)"}
                    </p>
                    <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-1">
                      {showUser && (
                        <span className="text-[10px] text-accent font-medium truncate max-w-[120px]">
                          {usersMap[t.user_id]?.display_name || usersMap[t.user_id]?.email || "Unknown"}
                        </span>
                      )}
                    </div>
                    <div className="flex flex-wrap gap-x-3 gap-y-0.5 mt-0.5">
                      <span className="text-[10px] text-text-muted">{fmtTime(t.created_at)}</span>
                      <span className={`text-[10px] font-medium px-1 py-0.5 rounded ${sb.bg} ${sb.text}`}>
                        {t.status}
                      </span>
                      <span className={`text-[10px] ${TYPE_BADGE[t.response_type] || "text-text-muted"}`}>
                        {t.response_type}
                      </span>
                      <span className="text-[10px] text-text-muted tabular-nums">
                        {fmtMs(t.total_duration_ms)}
                      </span>
                      <span className="text-[10px] text-text-muted tabular-nums">
                        {t.total_tokens.toLocaleString()} tok
                      </span>
                      {t.total_llm_calls > 0 && (
                        <span className="text-[10px] text-text-muted">
                          {t.total_llm_calls} LLM
                        </span>
                      )}
                      {t.total_db_queries > 0 && (
                        <span className="text-[10px] text-text-muted">
                          {t.total_db_queries} DB
                        </span>
                      )}
                    </div>
                    {t.error_message && (
                      <p className="text-[10px] text-error mt-1 truncate">{t.error_message}</p>
                    )}
                  </div>
                  <Icon
                    name={isSelected ? "chevron-down" : "chevron-right"}
                    size={12}
                    className="text-text-muted mt-0.5 shrink-0"
                  />
                </div>
              </button>
            );
          })
        )}
      </div>

      {totalPages > 1 && (
        <div className="flex items-center justify-between px-3 py-2 border-t border-border-subtle">
          <button
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1}
            className="text-[10px] px-2 py-1 rounded-md text-text-muted hover:bg-surface-2 disabled:opacity-30 transition-colors"
          >
            Prev
          </button>
          <span className="text-[10px] text-text-muted tabular-nums">
            {page} / {totalPages}
          </span>
          <button
            onClick={() => onPageChange(page + 1)}
            disabled={page >= totalPages}
            className="text-[10px] px-2 py-1 rounded-md text-text-muted hover:bg-surface-2 disabled:opacity-30 transition-colors"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
