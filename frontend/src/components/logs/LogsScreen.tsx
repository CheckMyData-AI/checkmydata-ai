"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import type {
  LogSummary,
  LogUser,
  LogRequestTrace,
} from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { Icon } from "@/components/ui/Icon";
import { LogsSummary } from "./LogsSummary";
import { LogsUserFilter } from "./LogsUserFilter";
import { LogsRequestList } from "./LogsRequestList";
import { LogsTraceDetail } from "./LogsTraceDetail";
import { LogsDateFilter } from "./LogsDateFilter";

export function LogsScreen() {
  const activeProject = useAppStore((s) => s.activeProject);
  const setLogsOpen = useAppStore((s) => s.setLogsOpen);

  const [days, setDays] = useState(7);
  const [summary, setSummary] = useState<LogSummary | null>(null);
  const [users, setUsers] = useState<LogUser[]>([]);
  const [requests, setRequests] = useState<LogRequestTrace[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);
  const [selectedTraceId, setSelectedTraceId] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const projectId = activeProject?.id;

  const loadData = useCallback(async () => {
    if (!projectId) return;
    setLoading(true);
    setError(null);
    try {
      const dateFrom = new Date();
      dateFrom.setDate(dateFrom.getDate() - days);
      const [summaryData, usersData, requestsData] = await Promise.all([
        api.logs.getSummary(projectId, days),
        api.logs.getUsers(projectId, days),
        api.logs.listRequests(projectId, {
          user_id: selectedUserId || undefined,
          status: statusFilter || undefined,
          date_from: dateFrom.toISOString(),
          page,
          page_size: 50,
        }),
      ]);
      setSummary(summaryData);
      setUsers(usersData);
      setRequests(requestsData.items);
      setTotal(requestsData.total);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load logs");
    } finally {
      setLoading(false);
    }
  }, [projectId, days, selectedUserId, statusFilter, page]);

  useEffect(() => {
    loadData();
  }, [loadData]);

  const handleUserSelect = useCallback((userId: string | null) => {
    setSelectedUserId(userId);
    setPage(1);
    setSelectedTraceId(null);
  }, []);

  const handleStatusFilter = useCallback((status: string | null) => {
    setStatusFilter(status);
    setPage(1);
    setSelectedTraceId(null);
  }, []);

  const handleDaysChange = useCallback((d: number) => {
    setDays(d);
    setPage(1);
    setSelectedTraceId(null);
  }, []);

  if (!projectId) return null;

  return (
    <div className="absolute inset-0 z-30 bg-surface-0 flex flex-col overflow-hidden">
      {/* Header */}
      <div className="flex items-center gap-3 px-4 py-3 border-b border-border-subtle bg-surface-0 shrink-0">
        <button
          onClick={() => setLogsOpen(false)}
          className="p-1.5 rounded-md hover:bg-surface-2 transition-colors text-text-muted"
          aria-label="Close logs"
        >
          <Icon name="arrow-left" size={16} />
        </button>
        <Icon name="activity" size={16} className="text-text-tertiary" />
        <h2 className="text-sm font-semibold text-text-primary">Request Logs</h2>
        <LogsDateFilter days={days} onChange={handleDaysChange} />
        <button
          onClick={loadData}
          className="ml-auto p-1.5 rounded-md hover:bg-surface-2 transition-colors text-text-muted"
          aria-label="Refresh"
          disabled={loading}
        >
          <Icon name="refresh-cw" size={14} className={loading ? "animate-spin" : ""} />
        </button>
      </div>

      {error && (
        <div className="px-4 py-2 bg-error/5 text-xs text-error border-b border-border-subtle flex items-center gap-2">
          <span>{error}</span>
          <button onClick={loadData} className="underline hover:no-underline">
            Retry
          </button>
        </div>
      )}

      {/* Summary cards */}
      {summary && (
        <div className="px-4 py-3 border-b border-border-subtle shrink-0">
          <LogsSummary summary={summary} />
        </div>
      )}

      {/* Main content: user filter + request list + trace detail */}
      <div className="flex-1 flex min-h-0 overflow-hidden">
        {/* User sidebar */}
        <div className="w-48 lg:w-56 border-r border-border-subtle overflow-y-auto shrink-0 py-2 px-1.5 hidden sm:block">
          <div className="text-[10px] text-text-tertiary uppercase tracking-wider px-2 py-1 mb-1">
            Users ({users.length})
          </div>
          <LogsUserFilter
            users={users}
            selectedUserId={selectedUserId}
            onSelect={handleUserSelect}
          />
        </div>

        {/* Request list */}
        <div className={`flex-1 min-w-0 flex flex-col ${selectedTraceId ? "hidden lg:flex lg:max-w-[50%]" : ""}`}>
          {loading && requests.length === 0 ? (
            <div className="flex-1 flex items-center justify-center text-xs text-text-tertiary animate-pulse">
              Loading requests...
            </div>
          ) : (
            <LogsRequestList
              items={requests}
              total={total}
              page={page}
              pageSize={50}
              onPageChange={setPage}
              selectedTraceId={selectedTraceId}
              onSelectTrace={setSelectedTraceId}
              statusFilter={statusFilter}
              onStatusFilter={handleStatusFilter}
              users={users}
              selectedUserId={selectedUserId}
            />
          )}
        </div>

        {/* Trace detail panel */}
        {selectedTraceId && (
          <div className="flex-1 min-w-0 lg:max-w-[50%] border-l border-border-subtle overflow-y-auto p-3">
            <LogsTraceDetail
              projectId={projectId}
              traceId={selectedTraceId}
              onClose={() => setSelectedTraceId(null)}
            />
          </div>
        )}
      </div>
    </div>
  );
}
