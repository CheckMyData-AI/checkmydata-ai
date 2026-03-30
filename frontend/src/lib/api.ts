import { toast } from "@/stores/toast-store";
import { useAuthStore } from "@/stores/auth-store";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

let sessionExpiredHandled = false;

export function handleSessionExpired(): void {
  if (sessionExpiredHandled || typeof window === "undefined") return;
  sessionExpiredHandled = true;
  useAuthStore.getState().logout();
  toast("Session expired, please log in again", "error");
  window.location.href = "/login";
}

function getAuthHeaders(): Record<string, string> {
  if (typeof window === "undefined") return {};
  try {
    const token = localStorage.getItem("auth_token");
    return token ? { Authorization: `Bearer ${token}` } : {};
  } catch {
    return {};
  }
}

const DEFAULT_TIMEOUT_MS = 60_000;
const MAX_RETRIES = 2;
const RETRY_BACKOFF_MS = [600, 1500];
const RETRYABLE_STATUSES = new Set([502, 503, 504]);

function isSafeMethod(method?: string): boolean {
  return !method || method.toUpperCase() === "GET" || method.toUpperCase() === "HEAD";
}

async function request<T>(path: string, options?: RequestInit & { timeoutMs?: number }): Promise<T> {
  const { headers: optHeaders, timeoutMs, ...restOptions } = (options ?? {}) as RequestInit & { timeoutMs?: number };
  const safe = isSafeMethod(restOptions.method);
  let lastError: Error | undefined;

  for (let attempt = 0; attempt <= (safe ? MAX_RETRIES : 0); attempt++) {
    if (attempt > 0) {
      await new Promise((r) => setTimeout(r, RETRY_BACKOFF_MS[attempt - 1] ?? 1500));
    }

    const controller = new AbortController();
    const existingSignal = restOptions.signal;
    let onAbort: (() => void) | undefined;
    if (existingSignal) {
      if (existingSignal.aborted) throw new Error("Request aborted");
      onAbort = () => controller.abort(existingSignal.reason);
      existingSignal.addEventListener("abort", onAbort);
    }
    const timeout = setTimeout(() => controller.abort("Request timed out"), timeoutMs ?? DEFAULT_TIMEOUT_MS);

    let res: Response;
    try {
      res = await fetch(`${API_BASE}${path}`, {
        ...restOptions,
        signal: controller.signal,
        headers: {
          "Content-Type": "application/json",
          ...getAuthHeaders(),
          ...(optHeaders instanceof Headers
            ? Object.fromEntries(optHeaders.entries())
            : Array.isArray(optHeaders)
              ? Object.fromEntries(optHeaders)
              : optHeaders),
        },
      });
    } catch (err) {
      clearTimeout(timeout);
      if (existingSignal && onAbort) existingSignal.removeEventListener("abort", onAbort);
      if (err instanceof DOMException && err.name === "AbortError") {
        throw new Error("Request timed out. Please try again.");
      }
      lastError = err instanceof Error ? err : new Error(String(err));
      if (safe && attempt < MAX_RETRIES) continue;
      throw lastError;
    }
    clearTimeout(timeout);
    if (existingSignal && onAbort) existingSignal.removeEventListener("abort", onAbort);

    if (safe && RETRYABLE_STATUSES.has(res.status) && attempt < MAX_RETRIES) {
      lastError = new Error(`Request failed: ${res.status}`);
      continue;
    }

    if (!res.ok) {
      const isAuthRoute = path.startsWith("/auth/");
      if (res.status === 401 && !isAuthRoute && typeof window !== "undefined") {
        handleSessionExpired();
        throw new Error("Session expired. Please log in again.");
      }
      if (res.status === 403) {
        throw new Error("You don't have permission to perform this action.");
      }
      if (res.status === 429) {
        throw new Error("Too many requests. Please wait a moment and try again.");
      }
      const body = await res.json().catch(() => ({}));
      const detail = Array.isArray(body.detail)
        ? body.detail.map((e: { msg?: string; message?: string }) => e.msg ?? e.message ?? "Validation error").join("; ")
        : body.detail || `Request failed: ${res.status}`;
      throw new Error(detail);
    }
    return res.json();
  }
  throw lastError ?? new Error("Request failed after retries");
}

export interface Project {
  id: string;
  name: string;
  description: string;
  repo_url: string | null;
  repo_branch: string;
  ssh_key_id: string | null;
  indexing_llm_provider: string | null;
  indexing_llm_model: string | null;
  agent_llm_provider: string | null;
  agent_llm_model: string | null;
  sql_llm_provider: string | null;
  sql_llm_model: string | null;
  owner_id: string | null;
  user_role: string | null;
}

export interface ProjectInvite {
  id: string;
  project_id: string;
  email: string;
  role: string;
  status: string;
  invited_by: string;
  created_at: string | null;
  accepted_at: string | null;
  project_name: string | null;
}

export interface ProjectMember {
  id: string;
  project_id: string;
  user_id: string;
  role: string;
  email: string | null;
  display_name: string | null;
}

export interface Connection {
  id: string;
  project_id: string;
  name: string;
  db_type: string;
  source_type: string;
  ssh_host: string | null;
  ssh_port: number;
  ssh_user: string | null;
  ssh_key_id: string | null;
  db_host: string;
  db_port: number;
  db_name: string;
  db_user: string | null;
  is_read_only: boolean;
  is_active: boolean;
  ssh_exec_mode: boolean;
  ssh_command_template: string | null;
  ssh_pre_commands: string | null;
  mcp_server_command: string | null;
  mcp_server_url: string | null;
  mcp_transport_type: string | null;
}

export interface SshKey {
  id: string;
  name: string;
  fingerprint: string;
  key_type: string;
  created_at: string;
}

export interface ChatSession {
  id: string;
  project_id: string;
  title: string;
  connection_id?: string | null;
  created_at?: string | null;
}

export interface ChatSearchResult {
  message_id: string;
  session_id: string;
  session_title: string;
  content_snippet: string;
  sql_query: string | null;
  created_at: string;
  role: string;
}

export interface QuerySuggestion {
  text: string;
  source: string;
  table?: string;
}

export interface ChatMessageDTO {
  id: string;
  role: string;
  content: string;
  metadata_json: string | null;
  tool_calls_json: string | null;
  user_rating: number | null;
  created_at: string;
}

export interface ChatResponse {
  session_id: string;
  answer: string;
  query: string | null;
  query_explanation: string | null;
  visualization: Record<string, unknown> | null;
  error: string | null;
  workflow_id: string | null;
  staleness_warning: string | null;
  response_type?: "text" | "sql_result" | "knowledge" | "error" | "clarification_request" | "stage_checkpoint" | "stage_failed" | "step_limit_reached";
  assistant_message_id?: string | null;
  user_message_id?: string | null;
  raw_result?: { columns: string[]; rows: unknown[][]; total_rows: number } | null;
  rag_sources?: Array<{ source_path: string; distance?: number; doc_type?: string }> | null;
  token_usage?: { prompt_tokens?: number; completion_tokens?: number; total_tokens?: number } | null;
  rules_changed?: boolean;
  steps_used?: number;
  steps_total?: number;
  continuation_context?: string | null;
  clarification_data?: {
    question: string;
    question_type: "yes_no" | "multiple_choice" | "numeric_range" | "free_text";
    options?: string[];
    context?: string;
  } | null;
}

export interface StreamError {
  error: string;
  error_type?: string;
  is_retryable?: boolean;
  user_message?: string;
}

export interface RepoCheckResult {
  accessible: boolean;
  branches: string[];
  default_branch: string | null;
  error: string | null;
}

export interface RepoStatus {
  project_id: string;
  repo_url: string;
  last_indexed_commit: string | null;
  last_indexed_at: string | null;
  branch: string;
  indexed_files_count: number;
  total_documents: number;
  is_indexing: boolean;
}

export interface UpdateCheck {
  has_updates: boolean;
  commits_behind: number;
  message: string;
}

export interface DbIndexStatus {
  is_indexed: boolean;
  is_indexing?: boolean;
  indexing_status?: string;
  indexed_at?: string | null;
  total_tables?: number;
  active_tables?: number;
  empty_tables?: number;
  orphan_tables?: number;
  phantom_tables?: number;
}

export interface DbIndexResponse {
  tables: {
    table_name: string;
    table_schema: string;
    column_count: number;
    row_count: number | null;
    is_active: boolean;
    relevance_score: number;
    business_description: string;
    query_hints: string;
    code_match_status: string;
    indexed_at: string | null;
  }[];
  summary?: {
    total_tables: number;
    active_tables: number;
    empty_tables: number;
    orphan_tables: number;
    phantom_tables: number;
    summary_text: string;
    recommendations: string;
    indexed_at: string | null;
  } | null;
}

export interface SyncStatus {
  is_synced: boolean;
  is_syncing?: boolean;
  synced_at?: string | null;
  total_tables?: number;
  synced_tables?: number;
  code_only_tables?: number;
  db_only_tables?: number;
  mismatch_tables?: number;
  sync_status?: string;
}

export interface SyncResponse {
  tables: {
    table_name: string;
    entity_name: string | null;
    sync_status: string;
    confidence_score: number;
    conversion_warnings: string;
    data_format_notes: string;
    query_recommendations: string;
    read_count: number;
    write_count: number;
    synced_at: string | null;
  }[];
  summary?: {
    total_tables: number;
    synced_tables: number;
    code_only_tables: number;
    db_only_tables: number;
    mismatch_tables: number;
    global_notes: string;
    data_conventions: string;
    query_guidelines: string;
    synced_at: string | null;
  } | null;
}

export interface ConnectionHealthState {
  status: string;
  latency_ms: number;
  last_check: string | null;
  consecutive_failures: number;
  last_error: string | null;
}

export interface LearningsStatus {
  has_learnings: boolean;
  total_active: number;
  categories: Record<string, number>;
  last_compiled_at: string | null;
}

export interface AgentLearningDTO {
  id: string;
  category: string;
  subject: string;
  lesson: string;
  confidence: number;
  times_confirmed: number;
  times_applied: number;
  is_active: boolean;
  source_query: string | null;
  source_error: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ProjectReadiness {
  repo_connected: boolean;
  repo_indexed: boolean;
  db_connected: boolean;
  db_indexed: boolean;
  code_db_synced: boolean;
  ready: boolean;
  missing_steps: { step: string; label: string }[];
  active_connection_id: string | null;
  last_indexed_at: string | null;
  commits_behind: number;
  is_stale: boolean;
}

export interface LLMModel {
  id: string;
  name: string;
  context_length: number | null;
  pricing: { prompt: string; completion: string } | null;
}

export interface SavedNote {
  id: string;
  project_id: string;
  user_id: string;
  connection_id: string | null;
  title: string;
  comment: string | null;
  sql_query: string;
  answer_text: string | null;
  visualization_json: string | null;
  last_result_json: string | null;
  is_shared: boolean;
  shared_by: string | null;
  last_executed_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface DashboardCard {
  note_id: string;
  viz_config?: Record<string, unknown>;
  refresh_interval?: number;
}

export interface Dashboard {
  id: string;
  project_id: string;
  creator_id: string;
  title: string;
  layout_json: string | null;
  cards_json: string | null;
  is_shared: boolean;
  created_at: string | null;
  updated_at: string | null;
  user_role?: string | null;
}

export interface ExecuteNoteResponse {
  id: string;
  last_result_json: string | null;
  last_executed_at: string | null;
  error: string | null;
}

export interface ScheduledQuery {
  id: string;
  user_id: string;
  project_id: string;
  connection_id: string;
  title: string;
  sql_query: string;
  cron_expression: string;
  alert_conditions: string | null;
  notification_channels: string | null;
  is_active: boolean;
  last_run_at: string | null;
  last_result_json: string | null;
  next_run_at: string | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface ScheduleRun {
  id: string;
  schedule_id: string;
  status: string;
  result_summary: string | null;
  alerts_fired: string | null;
  executed_at: string | null;
  duration_ms: number | null;
}

export interface AppNotification {
  id: string;
  user_id: string;
  project_id: string | null;
  title: string;
  body: string | null;
  type: string;
  is_read: boolean;
  created_at: string | null;
}

export interface AuthUser {
  id: string;
  email: string;
  display_name: string;
  picture_url?: string | null;
  auth_provider?: string;
  is_onboarded?: boolean;
  can_create_projects?: boolean;
}

export interface AuthResponse {
  token: string;
  user: AuthUser;
}

export interface UsagePeriod {
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number | null;
  request_count: number;
}

export interface DailyUsage {
  date: string;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  estimated_cost_usd: number | null;
  request_count: number;
}

export interface ChangePercent {
  prompt_tokens: number | null;
  completion_tokens: number | null;
  total_tokens: number | null;
  estimated_cost_usd: number | null;
  request_count: number | null;
}

export interface UsageStatsResponse {
  current_period: UsagePeriod;
  previous_period: UsagePeriod;
  change_percent: ChangePercent;
  daily_breakdown: DailyUsage[];
  period_days: number;
}

export interface LogUser {
  user_id: string;
  display_name: string;
  email: string;
  picture_url: string | null;
  request_count: number;
  last_request_at: string | null;
}

export interface LogRequestTrace {
  id: string;
  user_id: string;
  session_id: string | null;
  workflow_id: string;
  question: string;
  response_type: string;
  status: string;
  error_message: string | null;
  total_duration_ms: number | null;
  total_llm_calls: number;
  total_db_queries: number;
  total_tokens: number;
  estimated_cost_usd: number | null;
  llm_provider: string;
  llm_model: string;
  steps_used: number;
  steps_total: number;
  created_at: string | null;
}

export interface LogRequestsPage {
  items: LogRequestTrace[];
  total: number;
  page: number;
  page_size: number;
}

export interface LogTraceSpan {
  id: string;
  parent_span_id: string | null;
  span_type: string;
  name: string;
  status: string;
  detail: string;
  started_at: string | null;
  ended_at: string | null;
  duration_ms: number | null;
  input_preview: string | null;
  output_preview: string | null;
  token_usage_json: string | null;
  metadata_json: string | null;
  order_index: number;
}

export interface LogTraceDetail {
  trace: LogRequestTrace & {
    project_id: string;
    message_id: string | null;
    assistant_message_id: string | null;
  };
  spans: LogTraceSpan[];
}

export interface LogSummary {
  total_requests: number;
  successful: number;
  failed: number;
  total_llm_calls: number;
  total_db_queries: number;
  avg_duration_ms: number;
  total_tokens: number;
  total_cost_usd: number;
  by_status: Record<string, number>;
  by_type: Record<string, number>;
}

export interface CostEstimateBreakdown {
  schema_context: number;
  rules: number;
  learnings: number;
  overview: number;
  history_budget_remaining: number;
}

export interface CostEstimate {
  estimated_prompt_tokens: number;
  estimated_completion_tokens: number;
  estimated_total_tokens: number;
  estimated_cost_usd: number | null;
  context_utilization_pct: number;
  breakdown: CostEstimateBreakdown;
}

export interface BatchQueryDTO {
  id: string;
  user_id: string;
  project_id: string;
  connection_id: string;
  title: string;
  queries_json: string;
  note_ids_json: string | null;
  status: string;
  results_json: string | null;
  created_at: string | null;
  completed_at: string | null;
}

export interface DataGraphMetric {
  id: string;
  name: string;
  display_name: string;
  description: string;
  category: string;
  source_table: string | null;
  source_column: string | null;
  aggregation: string;
  unit: string;
  confidence: number;
  times_referenced: number;
  connection_id: string | null;
}

export interface DataGraphRelationship {
  id: string;
  metric_a_id: string;
  metric_b_id: string;
  relationship_type: string;
  strength: number;
  direction: string;
  description: string;
  confidence: number;
}

export interface InsightDTO {
  id: string;
  insight_type: string;
  severity: string;
  title: string;
  description: string;
  recommended_action: string;
  expected_impact: string;
  confidence: number;
  status: string;
  user_verdict: string | null;
  times_surfaced: number;
  times_confirmed: number;
  connection_id: string | null;
  detected_at: string;
}

export interface AnomalyReportDTO {
  check_type: string;
  title: string;
  description: string;
  severity: string;
  business_impact: string;
  root_cause_hypothesis: string;
  affected_metrics: string[];
  affected_rows: number;
  confidence: number;
  recommended_action: string;
  expected_impact: string;
  related_anomalies: string[];
}

export interface OpportunityDTO {
  opportunity_type: string;
  title: string;
  description: string;
  segment: string;
  metric: string;
  current_value: number;
  benchmark_value: number;
  gap_pct: number;
  estimated_impact: string;
  suggested_action: string;
  confidence: number;
  evidence: string[];
  severity: string;
}

export interface ActionRecommendationDTO {
  action_type: string;
  title: string;
  description: string;
  what_to_do: string;
  expected_impact: string;
  impact_metric: string;
  impact_estimate_pct: number;
  priority: string;
  effort: string;
  confidence: number;
  prerequisites: string[];
  risks: string[];
  source_insight_type: string;
  source_insight_title: string;
}

export interface TemporalTrendDTO {
  direction: string;
  slope: number;
  slope_pct_per_period: number;
  strength: number;
  description: string;
  start_value: number;
  end_value: number;
  periods: number;
}

export interface TemporalSeasonalityDTO {
  detected: boolean;
  period: number;
  amplitude: number;
  description: string;
  peak_positions: number[];
  trough_positions: number[];
}

export interface TemporalReportDTO {
  metric_name: string;
  total_points: number;
  trend: TemporalTrendDTO | null;
  seasonality: TemporalSeasonalityDTO | null;
  recent_anomalies: { position: number; value: number; z_score: number; direction: string; description: string }[];
  context_note: string;
}

export interface LagResultDTO {
  lag_periods: number;
  correlation: number;
  description: string;
}

export interface ExplorationFindingDTO {
  category: string;
  severity: string;
  title: string;
  description: string;
  evidence: string;
  recommended_action: string;
  confidence: number;
  source: string;
}

export interface ExplorationReportDTO {
  status: string;
  total_findings: number;
  critical_count: number;
  warning_count: number;
  positive_count: number;
  findings: ExplorationFindingDTO[];
  summary: string;
  investigation_steps: string[];
  data_coverage: Record<string, number>;
}

export interface CatalogMetricDTO {
  id: string;
  name: string;
  display_name: string;
  description: string;
  category: string;
  source_table: string | null;
  source_column: string | null;
  aggregation: string;
  formula: string;
  unit: string;
  data_type: string;
  confidence: number;
  connection_id: string | null;
  discovery_source: string;
  times_referenced: number;
}

export interface NormalizationResultDTO {
  canonical_name: string;
  display_name: string;
  variants: { name: string; connection_id: string; source_table: string; source_column: string }[];
  category: string;
  aggregation: string;
  unit: string;
  confidence: number;
}

export interface ReconciliationDiscrepancyDTO {
  discrepancy_type: string;
  severity: string;
  title: string;
  description: string;
  source_a_name: string;
  source_b_name: string;
  source_a_value: unknown;
  source_b_value: unknown;
  affected_metric: string;
  affected_table: string;
  difference_pct: number;
  likely_cause: string;
  recommended_action: string;
}

export interface ReconciliationReportDTO {
  source_a_name: string;
  source_b_name: string;
  source_a_connection_id: string;
  source_b_connection_id: string;
  status: string;
  total_checks: number;
  critical_count: number;
  warning_count: number;
  discrepancies: ReconciliationDiscrepancyDTO[];
  summary: string;
}

export interface LossReportDTO {
  loss_type: string;
  title: string;
  description: string;
  metric: string;
  current_value: number;
  expected_value: number;
  loss_amount: number;
  loss_pct: number;
  estimated_monthly_impact: string;
  suggested_fix: string;
  confidence: number;
  evidence: string[];
  severity: string;
}

export const api = {
  auth: {
    register: (email: string, password: string, displayName?: string) =>
      request<AuthResponse>("/auth/register", {
        method: "POST",
        body: JSON.stringify({ email, password, display_name: displayName || "" }),
      }),
    login: (email: string, password: string) =>
      request<AuthResponse>("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      }),
    googleLogin: (credential: string, nonce?: string, csrfToken?: string) =>
      request<AuthResponse>("/auth/google", {
        method: "POST",
        body: JSON.stringify({ credential, nonce, g_csrf_token: csrfToken }),
      }),
    changePassword: (currentPassword: string, newPassword: string) =>
      request<{ ok: boolean }>("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
      }),
    refresh: () =>
      request<AuthResponse>("/auth/refresh", { method: "POST" }),
    me: () =>
      request<AuthUser>("/auth/me"),
    deleteAccount: () =>
      request<{ ok: boolean }>("/auth/account", { method: "DELETE" }),
    completeOnboarding: () =>
      request<{ ok: boolean }>("/auth/complete-onboarding", { method: "POST" }),
  },

  projects: {
    list: () => request<Project[]>("/projects"),
    get: (id: string) => request<Project>(`/projects/${id}`),
    create: (data: Partial<Project>) =>
      request<Project>("/projects", { method: "POST", body: JSON.stringify(data) }),
    update: (id: string, data: Partial<Project>) =>
      request<Project>(`/projects/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<{ ok: boolean }>(`/projects/${id}`, { method: "DELETE" }),
    readiness: (id: string) =>
      request<ProjectReadiness>(`/projects/${id}/readiness`),
    requestAccess: (data: { email: string; description: string; message: string }) =>
      request<{ ok: boolean }>("/projects/access-requests", {
        method: "POST",
        body: JSON.stringify(data),
      }),
  },

  connections: {
    listByProject: (projectId: string) =>
      request<Connection[]>(`/connections/project/${projectId}`),
    get: (id: string) => request<Connection>(`/connections/${id}`),
    create: (data: Record<string, unknown>) =>
      request<Connection>("/connections", { method: "POST", body: JSON.stringify(data) }),
    update: (id: string, data: Record<string, unknown>) =>
      request<Connection>(`/connections/${id}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    delete: (id: string) =>
      request<{ ok: boolean }>(`/connections/${id}`, { method: "DELETE" }),
    test: (id: string) =>
      request<{ success: boolean; error?: string }>(`/connections/${id}/test`, {
        method: "POST",
      }),
    testSsh: (id: string) =>
      request<{ success: boolean; hostname?: string; error?: string }>(`/connections/${id}/test-ssh`, {
        method: "POST",
      }),
    refreshSchema: (id: string) =>
      request<{ ok: boolean; tables: number; db_type: string }>(`/connections/${id}/refresh-schema`, {
        method: "POST",
      }),
    indexDb: (id: string) =>
      request<{ status: string; connection_id: string }>(`/connections/${id}/index-db`, {
        method: "POST",
      }),
    indexDbStatus: (id: string) =>
      request<DbIndexStatus>(`/connections/${id}/index-db/status`),
    getDbIndex: (id: string) =>
      request<DbIndexResponse>(`/connections/${id}/index-db`),
    deleteDbIndex: (id: string) =>
      request<{ ok: boolean }>(`/connections/${id}/index-db`, { method: "DELETE" }),

    triggerSync: (id: string) =>
      request<{ status: string; connection_id: string }>(`/connections/${id}/sync`, {
        method: "POST",
      }),
    syncStatus: (id: string) =>
      request<SyncStatus>(`/connections/${id}/sync/status`),
    getSync: (id: string) =>
      request<SyncResponse>(`/connections/${id}/sync`),
    deleteSync: (id: string) =>
      request<{ ok: boolean }>(`/connections/${id}/sync`, { method: "DELETE" }),

    learningsStatus: (id: string) =>
      request<LearningsStatus>(`/connections/${id}/learnings/status`),
    listLearnings: (id: string) =>
      request<AgentLearningDTO[]>(`/connections/${id}/learnings`),
    learningsSummary: (id: string) =>
      request<{ compiled_prompt: string }>(`/connections/${id}/learnings/summary`),
    updateLearning: (connId: string, learningId: string, data: { lesson?: string; is_active?: boolean; confidence?: number }) =>
      request<{ ok: boolean; id: string }>(`/connections/${connId}/learnings/${learningId}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    deleteLearning: (connId: string, learningId: string) =>
      request<{ ok: boolean }>(`/connections/${connId}/learnings/${learningId}`, { method: "DELETE" }),
    clearLearnings: (connId: string) =>
      request<{ ok: boolean; deleted: number }>(`/connections/${connId}/learnings`, { method: "DELETE" }),
    recompileLearnings: (connId: string) =>
      request<{ ok: boolean; compiled_prompt: string }>(`/connections/${connId}/learnings/recompile`, { method: "POST" }),
    health: (id: string) =>
      request<ConnectionHealthState>(`/connections/${id}/health`),
    healthAll: (projectId: string) =>
      request<Record<string, ConnectionHealthState>>(`/connections/health?project_id=${projectId}`),
    reconnect: (id: string) =>
      request<{ success: boolean; health?: ConnectionHealthState; error?: string }>(`/connections/${id}/reconnect`, {
        method: "POST",
      }),
  },

  chat: {
    listSessions: (projectId: string) =>
      request<ChatSession[]>(`/chat/sessions/${projectId}`),
    createSession: (data: { project_id: string; title?: string; connection_id?: string }) =>
      request<ChatSession>("/chat/sessions", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    ensureWelcome: (projectId: string, connectionId?: string) =>
      request<ChatSession & { created: boolean }>("/chat/sessions/ensure-welcome", {
        method: "POST",
        body: JSON.stringify({ project_id: projectId, connection_id: connectionId }),
      }),
    updateSession: (sessionId: string, data: { title: string }) =>
      request<ChatSession>(`/chat/sessions/${sessionId}`, {
        method: "PATCH",
        body: JSON.stringify(data),
      }),
    generateTitle: (sessionId: string) =>
      request<ChatSession>(`/chat/sessions/${sessionId}/generate-title`, {
        method: "POST",
      }),
    deleteSession: (sessionId: string) =>
      request<{ ok: boolean }>(`/chat/sessions/${sessionId}`, { method: "DELETE" }),
    submitFeedback: (messageId: string, rating: number) =>
      request<{ ok: boolean; message_id: string; rating: number }>("/chat/feedback", {
        method: "POST",
        body: JSON.stringify({ message_id: messageId, rating }),
      }),
    getFeedbackAnalytics: (projectId: string) =>
      request<{ total_rated: number; positive: number; negative: number }>(
        `/chat/analytics/feedback/${projectId}`,
      ),
    getMessages: (sessionId: string) =>
      request<ChatMessageDTO[]>(`/chat/sessions/${sessionId}/messages`),
    search: (projectId: string, query: string, limit?: number) =>
      request<ChatSearchResult[]>(
        `/chat/search?project_id=${projectId}&q=${encodeURIComponent(query)}&limit=${limit || 20}`,
      ),
    summarize: (messageId: string, projectId: string) =>
      request<{ summary: string; message_id: string }>("/chat/summarize", {
        method: "POST",
        body: JSON.stringify({ message_id: messageId, project_id: projectId }),
      }),
    explainSql: (sql: string, projectId: string, dbType?: string) =>
      request<{ explanation: string; complexity: string }>("/chat/explain-sql", {
        method: "POST",
        body: JSON.stringify({ sql, project_id: projectId, db_type: dbType }),
      }),
    suggestions: (projectId: string, connectionId: string, limit?: number) =>
      request<QuerySuggestion[]>(
        `/chat/suggestions?project_id=${projectId}&connection_id=${connectionId}&limit=${limit || 5}`,
      ),
    estimate: (projectId: string, connectionId?: string) =>
      request<CostEstimate>(
        `/chat/estimate?project_id=${projectId}${connectionId ? `&connection_id=${connectionId}` : ""}`,
      ),
    ask: (data: {
      project_id: string;
      connection_id?: string;
      message: string;
      session_id?: string;
      preferred_provider?: string;
      model?: string;
    }) =>
      request<ChatResponse>("/chat/ask", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    askStream: (
      data: {
        project_id: string;
        connection_id?: string;
        message: string;
        session_id?: string;
        preferred_provider?: string;
        model?: string;
        pipeline_action?: string;
        pipeline_run_id?: string;
        modification?: string;
        continuation_context?: string;
      },
      onStep: (event: Record<string, unknown>) => void,
      onResult: (result: ChatResponse) => void,
      onError: (error: StreamError) => void,
      onToolCall?: (event: Record<string, unknown>) => void,
      onPipelineEvent?: (eventType: string, event: Record<string, unknown>) => void,
      onThinking?: (event: Record<string, unknown>) => void,
      onToken?: (chunk: string) => void,
      onSessionRotated?: (event: { old_session_id: string; new_session_id: string; summary_preview: string; message_count: number; topics: string[] }) => void,
    ) => {
      const ctrl = new AbortController();
      const STREAM_IDLE_TIMEOUT_MS = 120_000;
      let idleTimer: ReturnType<typeof setTimeout> | undefined;
      const resetIdleTimer = () => {
        if (idleTimer) clearTimeout(idleTimer);
        idleTimer = setTimeout(() => {
          ctrl.abort("Stream idle timeout");
        }, STREAM_IDLE_TIMEOUT_MS);
      };
      resetIdleTimer();
      const streamPromise = fetch(`${API_BASE}/chat/ask/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify(data),
        signal: ctrl.signal,
      }).then(async (res) => {
        if (res.status === 401 && typeof window !== "undefined") {
          handleSessionExpired();
          onError({ error: "Session expired", error_type: "auth", is_retryable: false, user_message: "Session expired, please log in again." });
          throw new Error("Session expired");
        }
        if (res.status === 403) {
          onError({ error: "Permission denied", error_type: "auth", is_retryable: false, user_message: "You don't have permission to perform this action." });
          throw new Error("Permission denied");
        }
        if (!res.ok || !res.body) {
          onError({ error: `Stream failed: ${res.status}`, error_type: "network", is_retryable: true, user_message: "Connection to the server failed. Please try again." });
          throw new Error(`Stream failed: ${res.status}`);
        }
        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        let gotResult = false;
        let gotError = false;
        while (true) {
          const { done, value } = await reader.read();
          if (done) break;
          resetIdleTimer();
          buffer += decoder.decode(value, { stream: true });
          const parts = buffer.split("\n\n");
          buffer = parts.pop() || "";
          for (const part of parts) {
            const eventMatch = part.match(/^event:\s*([\w-]+)\ndata:\s*(.+)$/s);
            if (!eventMatch) continue;
            const [, eventType, jsonStr] = eventMatch;
            try {
              const parsed = JSON.parse(jsonStr);
              const pipelineEvents = new Set([
                "plan", "stage_start", "stage_result", "stage_validation",
                "stage_complete", "checkpoint", "stage_retry",
              ]);
              if (eventType === "token") onToken?.((parsed as { chunk: string }).chunk ?? "");
              else if (eventType === "thinking") onThinking?.(parsed);
              else if (eventType === "step") onStep(parsed);
              else if (eventType === "tool_call") onToolCall?.(parsed);
              else if (eventType === "result") { gotResult = true; onResult(parsed as ChatResponse); }
              else if (eventType === "error") { gotError = true; onError(parsed as StreamError); }
              else if (eventType === "session_rotated") onSessionRotated?.(parsed as { old_session_id: string; new_session_id: string; summary_preview: string; message_count: number; topics: string[] });
              else if (pipelineEvents.has(eventType)) onPipelineEvent?.(eventType, parsed);
            } catch { /* skip malformed */ }
          }
        }
        if (!gotResult && !gotError) {
          onError({ error: "Stream ended unexpectedly", error_type: "network", is_retryable: true, user_message: "The response ended unexpectedly. Please try again." });
        }
      }).catch((err) => {
        if (idleTimer) clearTimeout(idleTimer);
        if ((err instanceof DOMException && err.name === "AbortError") || (err && typeof err === "object" && "name" in err && (err as { name: string }).name === "AbortError")) {
          if (String(err.message || err).includes("idle timeout")) {
            onError({ error: "Stream timed out", error_type: "timeout", is_retryable: true, user_message: "The response timed out. Please try again." });
          }
          return;
        }
        onError({ error: String(err), error_type: "network", is_retryable: true, user_message: "An unexpected error occurred. Please try again." });
      }).finally(() => { if (idleTimer) clearTimeout(idleTimer); });
      return Object.assign(ctrl, { done: streamPromise });
    },
  },

  sshKeys: {
    list: () => request<SshKey[]>("/ssh-keys"),
    create: (data: { name: string; private_key: string; passphrase?: string }) =>
      request<SshKey>("/ssh-keys", { method: "POST", body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<{ ok: boolean }>(`/ssh-keys/${id}`, { method: "DELETE" }),
  },

  repos: {
    checkAccess: (data: { repo_url: string; ssh_key_id?: string | null }) =>
      request<RepoCheckResult>("/repos/check-access", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    index: (projectId: string, forceFull = false) =>
      request<{ status: string; workflow_id: string | null; resumed?: boolean; commit_sha?: string; files_indexed?: number; schemas_found?: number }>(
        `/repos/${projectId}/index`,
        { method: "POST", body: JSON.stringify({ force_full: forceFull }) }
      ),
    docs: (projectId: string) =>
      request<{ id: string; doc_type: string; source_path: string; commit_sha: string | null; updated_at: string | null }[]>(
        `/repos/${projectId}/docs`,
      ),
    doc: (projectId: string, docId: string) =>
      request<{ id: string; doc_type: string; source_path: string; content: string }>(
        `/repos/${projectId}/docs/${docId}`,
      ),
    status: (projectId: string) =>
      request<RepoStatus>(`/repos/${projectId}/status`),
    checkUpdates: (projectId: string) =>
      request<UpdateCheck>(`/repos/${projectId}/check-updates`, { method: "POST" }),
  },

  rules: {
    list: (projectId?: string) =>
      request<{ id: string; project_id: string | null; name: string; content: string; format: string; is_default: boolean }[]>(
        `/rules${projectId ? `?project_id=${projectId}` : ""}`,
      ),
    create: (data: { project_id?: string; name: string; content: string; format?: string }) =>
      request<{ id: string; project_id: string | null; name: string; content: string; format: string; is_default: boolean }>(
        "/rules",
        { method: "POST", body: JSON.stringify(data) },
      ),
    update: (id: string, data: Record<string, unknown>) =>
      request<{ id: string; project_id: string | null; name: string; content: string; format: string; is_default: boolean }>(
        `/rules/${id}`,
        { method: "PATCH", body: JSON.stringify(data) },
      ),
    delete: (id: string) =>
      request<{ ok: boolean }>(`/rules/${id}`, { method: "DELETE" }),
  },

  invites: {
    create: (projectId: string, email: string, role: string = "editor") =>
      request<ProjectInvite>(`/invites/${projectId}/invites`, {
        method: "POST",
        body: JSON.stringify({ email, role }),
      }),
    list: (projectId: string) =>
      request<ProjectInvite[]>(`/invites/${projectId}/invites`),
    revoke: (projectId: string, inviteId: string) =>
      request<{ ok: boolean }>(`/invites/${projectId}/invites/${inviteId}`, {
        method: "DELETE",
      }),
    resend: (projectId: string, inviteId: string) =>
      request<{ ok: boolean }>(`/invites/${projectId}/invites/${inviteId}/resend`, {
        method: "POST",
      }),
    listPending: () =>
      request<ProjectInvite[]>("/invites/pending"),
    accept: (inviteId: string) =>
      request<{ ok: boolean; project_id: string; role: string }>(
        `/invites/accept/${inviteId}`,
        { method: "POST" },
      ),
    listMembers: (projectId: string) =>
      request<ProjectMember[]>(`/invites/${projectId}/members`),
    updateMemberRole: (projectId: string, userId: string, role: string) =>
      request<ProjectMember>(`/invites/${projectId}/members/${userId}`, {
        method: "PATCH",
        body: JSON.stringify({ role }),
      }),
    removeMember: (projectId: string, userId: string) =>
      request<{ ok: boolean }>(`/invites/${projectId}/members/${userId}`, {
        method: "DELETE",
      }),
  },

  notes: {
    list: (projectId: string, scope: "mine" | "shared" | "all" = "mine") =>
      request<SavedNote[]>(`/notes?project_id=${projectId}&scope=${scope}`),
    get: (id: string) =>
      request<SavedNote>(`/notes/${id}`),
    create: (data: {
      project_id: string;
      connection_id?: string | null;
      title: string;
      comment?: string | null;
      sql_query: string;
      answer_text?: string | null;
      visualization_json?: string | null;
      last_result_json?: string | null;
    }) =>
      request<SavedNote>("/notes", { method: "POST", body: JSON.stringify(data) }),
    update: (id: string, data: { title?: string; comment?: string | null; is_shared?: boolean }) =>
      request<SavedNote>(`/notes/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<{ ok: boolean }>(`/notes/${id}`, { method: "DELETE" }),
    execute: (id: string) =>
      request<ExecuteNoteResponse>(`/notes/${id}/execute`, {
        method: "POST",
        timeoutMs: 120_000,
      }),
  },

  dashboards: {
    list: (projectId: string) =>
      request<Dashboard[]>(`/dashboards?project_id=${projectId}`),
    get: (id: string) =>
      request<Dashboard>(`/dashboards/${id}`),
    create: (data: {
      project_id: string;
      title: string;
      layout_json?: string | null;
      cards_json?: string | null;
      is_shared?: boolean;
    }) =>
      request<Dashboard>("/dashboards", { method: "POST", body: JSON.stringify(data) }),
    update: (id: string, data: { title?: string; layout_json?: string | null; cards_json?: string | null; is_shared?: boolean }) =>
      request<Dashboard>(`/dashboards/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<{ ok: boolean }>(`/dashboards/${id}`, { method: "DELETE" }),
  },

  models: {
    list: (provider: string) =>
      request<LLMModel[]>(`/models?provider=${encodeURIComponent(provider)}`),
  },

  viz: {
    render: (
      columns: string[],
      rows: unknown[][],
      vizType: string,
      config?: Record<string, unknown>,
    ) =>
      request<Record<string, unknown>>("/visualizations/render", {
        method: "POST",
        body: JSON.stringify({
          columns,
          rows,
          viz_type: vizType,
          config: config || {},
        }),
      }),
    export: async (columns: string[], rows: unknown[][], format: string) => {
      const res = await fetch(`${API_BASE}/visualizations/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
        body: JSON.stringify({ columns, rows, format }),
      });
      if (res.status === 401 && typeof window !== "undefined") {
        handleSessionExpired();
        throw new Error("Session expired. Please log in again.");
      }
      if (!res.ok) throw new Error("Export failed");
      return res.blob();
    },
  },

  tasks: {
    getActive: () =>
      request<{ workflow_id: string; pipeline: string; started_at: number; extra: Record<string, unknown> }[]>(
        "/tasks/active",
      ),
  },

  dataValidation: {
    validateData: (body: {
      connection_id: string;
      session_id: string;
      message_id: string;
      query: string;
      verdict: string;
      metric_description?: string;
      agent_value?: string;
      user_expected_value?: string;
      deviation_pct?: number;
      rejection_reason?: string;
      project_id: string;
    }) =>
      request<{
        ok: boolean;
        feedback_id: string;
        verdict: string;
        learnings_created: string[];
        notes_created: string[];
        benchmark_updated: boolean;
        resolution: string;
      }>("/data-validation/validate-data", {
        method: "POST",
        body: JSON.stringify(body),
      }),

    getValidationStats: (connectionId: string, projectId: string) =>
      request<{
        total: number;
        confirmed: number;
        rejected: number;
        approximate: number;
        unknown: number;
        resolved: number;
        confirmation_rate: number | null;
      }>(`/data-validation/validation-stats/${connectionId}?project_id=${projectId}`),

    getBenchmarks: (connectionId: string, projectId: string) =>
      request<Array<{
        id: string;
        metric_key: string;
        metric_description: string;
        value: string;
        value_numeric: number | null;
        unit: string | null;
        confidence: number;
        source: string;
        times_confirmed: number;
        last_confirmed_at: string | null;
      }>>(`/data-validation/benchmarks/${connectionId}?project_id=${projectId}`),

    getAnalyticsSummary: (projectId: string) =>
      request<{ accuracy_rate: number | null; total_validations: number; active_learnings: number; benchmark_count: number }>(
        `/data-validation/summary/${projectId}`,
      ),

    getFeedbackAnalytics: (projectId: string) =>
      request<{
        connections: number;
        validations: {
          total: number;
          by_verdict: Record<string, number>;
          accuracy_rate: number | null;
          top_error_patterns: Array<{ reason: string; count: number }>;
        };
        learnings: {
          total_active: number;
          by_category: Record<string, number>;
        };
        benchmarks: { total: number };
        investigations: Record<string, number>;
      }>(`/data-validation/analytics/${projectId}`),

    startInvestigation: (body: {
      project_id: string;
      connection_id: string;
      session_id: string;
      message_id: string;
      complaint_type: string;
      complaint_detail?: string;
      expected_value?: string;
      problematic_column?: string;
    }) =>
      request<{ ok: boolean; investigation_id: string; status: string }>(
        "/data-validation/investigate",
        { method: "POST", body: JSON.stringify(body) },
      ),

    getInvestigation: (investigationId: string) =>
      request<Record<string, unknown>>(`/data-validation/investigate/${investigationId}`),

    confirmFix: (investigationId: string, body: { accepted: boolean; project_id: string }) =>
      request<{ ok: boolean; status: string; learnings_created?: string[]; notes_created?: string[] }>(
        `/data-validation/investigate/${investigationId}/confirm-fix`,
        { method: "POST", body: JSON.stringify(body) },
      ),

    runAnomalyAnalysis: (body: {
      project_id: string;
      connection_id: string;
      query?: string;
      question?: string;
      rows: Record<string, unknown>[];
      columns: string[];
    }) =>
      request<{
        ok: boolean;
        total: number;
        reports: AnomalyReportDTO[];
        summary: string;
      }>("/data-validation/anomaly-analysis", {
        method: "POST",
        body: JSON.stringify(body),
      }),

    scanConnectionAnomalies: (connectionId: string, projectId: string) =>
      request<{
        ok: boolean;
        tables_scanned: number;
        results: Array<{
          table: string;
          findings: string[];
          anomaly_reports: AnomalyReportDTO[];
          row_count: number | null;
          null_rates: Record<string, number>;
        }>;
      }>(`/data-validation/anomaly-scan/${connectionId}?project_id=${projectId}`, {
        method: "POST",
      }),
  },

  usage: {
    getStats: (days: number = 30) =>
      request<UsageStatsResponse>(`/usage/stats?days=${days}`),
  },

  logs: {
    getUsers: (projectId: string, days: number = 30) =>
      request<LogUser[]>(`/logs/${projectId}/users?days=${days}`),
    listRequests: (
      projectId: string,
      params: {
        user_id?: string;
        status?: string;
        date_from?: string;
        date_to?: string;
        page?: number;
        page_size?: number;
      } = {},
    ) => {
      const qs = new URLSearchParams();
      for (const [k, v] of Object.entries(params)) {
        if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
      }
      const q = qs.toString();
      return request<LogRequestsPage>(`/logs/${projectId}/requests${q ? `?${q}` : ""}`);
    },
    getTraceDetail: (projectId: string, traceId: string) =>
      request<LogTraceDetail>(`/logs/${projectId}/requests/${traceId}`),
    getSummary: (projectId: string, days: number = 7) =>
      request<LogSummary>(`/logs/${projectId}/summary?days=${days}`),
  },

  schedules: {
    list: (projectId: string) =>
      request<ScheduledQuery[]>(`/schedules?project_id=${projectId}`),
    get: (id: string) =>
      request<ScheduledQuery>(`/schedules/${id}`),
    create: (data: {
      project_id: string;
      connection_id: string;
      title: string;
      sql_query: string;
      cron_expression: string;
      alert_conditions?: string | null;
      notification_channels?: string | null;
    }) =>
      request<ScheduledQuery>("/schedules", { method: "POST", body: JSON.stringify(data) }),
    update: (id: string, data: Record<string, unknown>) =>
      request<ScheduledQuery>(`/schedules/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    delete: (id: string) =>
      request<{ ok: boolean }>(`/schedules/${id}`, { method: "DELETE" }),
    runNow: (id: string) =>
      request<ScheduleRun>(`/schedules/${id}/run-now`, { method: "POST", timeoutMs: 120_000 }),
    history: (id: string) =>
      request<ScheduleRun[]>(`/schedules/${id}/history`),
  },

  notifications: {
    list: (unreadOnly = true) =>
      request<AppNotification[]>(`/notifications?unread_only=${unreadOnly}`),
    count: () =>
      request<{ count: number }>("/notifications/count"),
    markRead: (id: string) =>
      request<{ ok: boolean }>(`/notifications/${id}/read`, { method: "PATCH" }),
    markAllRead: () =>
      request<{ ok: boolean }>("/notifications/read-all", { method: "POST" }),
  },

  batch: {
    execute: (data: {
      project_id: string;
      connection_id: string;
      title: string;
      queries: { sql: string; title: string }[];
      note_ids?: string[];
    }) =>
      request<{ batch_id: string; status: string }>("/batch/execute", {
        method: "POST",
        body: JSON.stringify(data),
      }),
    get: (id: string) =>
      request<BatchQueryDTO>(`/batch/${id}`),
    list: (projectId: string) =>
      request<BatchQueryDTO[]>(`/batch?project_id=${projectId}`),
    delete: (id: string) =>
      request<{ ok: boolean }>(`/batch/${id}`, { method: "DELETE" }),
    export: async (id: string) => {
      const res = await fetch(`${API_BASE}/batch/${id}/export`, {
        method: "POST",
        headers: { "Content-Type": "application/json", ...getAuthHeaders() },
      });
      if (res.status === 401 && typeof window !== "undefined") {
        handleSessionExpired();
        throw new Error("Session expired. Please log in again.");
      }
      if (!res.ok) throw new Error("Export failed");
      return res.blob();
    },
  },

  demo: {
    setup: () =>
      request<{ project_id: string; connection_id: string }>("/demo/setup", { method: "POST" }),
  },

  dataGraph: {
    summary: (projectId: string) =>
      request<{ total_metrics: number; total_relationships: number; categories: Record<string, number> }>(
        `/data-graph/${projectId}/summary`
      ),
    metrics: (projectId: string, params?: { connection_id?: string; category?: string }) => {
      const qs = new URLSearchParams();
      if (params?.connection_id) qs.set("connection_id", params.connection_id);
      if (params?.category) qs.set("category", params.category);
      const q = qs.toString();
      return request<DataGraphMetric[]>(`/data-graph/${projectId}/metrics${q ? `?${q}` : ""}`);
    },
    upsertMetric: (projectId: string, data: { name: string; description?: string; category?: string; connection_id?: string }) =>
      request<{ id: string; name: string }>(`/data-graph/${projectId}/metrics`, {
        method: "POST",
        body: JSON.stringify(data),
      }),
    relationships: (projectId: string, metricId?: string) => {
      const qs = metricId ? `?metric_id=${metricId}` : "";
      return request<DataGraphRelationship[]>(`/data-graph/${projectId}/relationships${qs}`);
    },
    discover: (projectId: string, connectionId: string) =>
      request<{ discovered_count: number }>(`/data-graph/${projectId}/discover/${connectionId}`, {
        method: "POST",
      }),
    deleteMetric: (projectId: string, metricId: string) =>
      request<{ deleted: boolean }>(`/data-graph/${projectId}/metrics/${metricId}`, {
        method: "DELETE",
      }),
  },

  feed: {
    scan: (projectId: string, connectionId: string) =>
      request<{ insights_created: number; insights_updated: number; queries_run: number; errors: string[] }>(
        `/feed/${projectId}/scan/${connectionId}`,
        { method: "POST" },
      ),
    scanAll: (projectId: string) =>
      request<{ total_insights_created: number; total_insights_updated: number; connections_scanned: number }>(
        `/feed/${projectId}/scan`,
        { method: "POST" },
      ),
    scanOpportunities: (projectId: string, connectionId: string) =>
      request<{
        ok: boolean;
        opportunities: OpportunityDTO[];
        tables_scanned: number;
        insights_stored: number;
      }>(`/feed/${projectId}/opportunities/${connectionId}`, { method: "POST" }),
    scanLosses: (projectId: string, connectionId: string) =>
      request<{
        ok: boolean;
        losses: LossReportDTO[];
        tables_scanned: number;
        insights_stored: number;
      }>(`/feed/${projectId}/losses/${connectionId}`, { method: "POST" }),
  },

  insights: {
    list: (projectId: string, params?: {
      connection_id?: string;
      insight_type?: string;
      severity?: string;
      status?: string;
      limit?: number;
    }) => {
      const qs = new URLSearchParams();
      if (params?.connection_id) qs.set("connection_id", params.connection_id);
      if (params?.insight_type) qs.set("insight_type", params.insight_type);
      if (params?.severity) qs.set("severity", params.severity);
      if (params?.status) qs.set("status", params.status || "active");
      if (params?.limit) qs.set("limit", String(params.limit));
      const q = qs.toString();
      return request<InsightDTO[]>(`/insights/${projectId}${q ? `?${q}` : ""}`);
    },
    summary: (projectId: string) =>
      request<{ total_active: number; by_type: Record<string, number>; by_severity: Record<string, number> }>(
        `/insights/${projectId}/summary`
      ),
    confirm: (projectId: string, insightId: string, feedback?: string) =>
      request<{ status: string; confidence: number }>(`/insights/${projectId}/${insightId}/confirm`, {
        method: "PATCH",
        body: JSON.stringify({ feedback: feedback || "" }),
      }),
    dismiss: (projectId: string, insightId: string, feedback?: string) =>
      request<{ status: string; confidence: number }>(`/insights/${projectId}/${insightId}/dismiss`, {
        method: "PATCH",
        body: JSON.stringify({ feedback: feedback || "" }),
      }),
    resolve: (projectId: string, insightId: string, feedback?: string) =>
      request<{ status: string }>(`/insights/${projectId}/${insightId}/resolve`, {
        method: "PATCH",
        body: JSON.stringify({ feedback: feedback || "" }),
      }),
    getActions: (projectId: string, connectionId?: string, limit?: number) => {
      const qs = new URLSearchParams();
      if (connectionId) qs.set("connection_id", connectionId);
      if (limit) qs.set("limit", String(limit));
      const q = qs.toString();
      return request<{ total: number; actions: ActionRecommendationDTO[] }>(
        `/insights/${projectId}/actions${q ? `?${q}` : ""}`,
      );
    },
  },

  temporal: {
    analyze: (projectId: string, values: number[], metricName?: string, periodLabel?: string) =>
      request<TemporalReportDTO>(
        `/temporal/${projectId}/analyze`,
        {
          method: "POST",
          body: JSON.stringify({
            project_id: projectId,
            values,
            metric_name: metricName || "metric",
            period_label: periodLabel || "day",
          }),
        },
      ),
    detectLag: (projectId: string, seriesA: number[], seriesB: number[], maxLag?: number) =>
      request<LagResultDTO>(
        `/temporal/${projectId}/lag`,
        {
          method: "POST",
          body: JSON.stringify({
            project_id: projectId,
            series_a: seriesA,
            series_b: seriesB,
            max_lag: maxLag || 14,
          }),
        },
      ),
  },

  explore: {
    investigate: (projectId: string, connectionId?: string) => {
      const qs = new URLSearchParams();
      if (connectionId) qs.set("connection_id", connectionId);
      const q = qs.toString();
      return request<ExplorationReportDTO>(
        `/explore/${projectId}${q ? `?${q}` : ""}`,
        { method: "POST" },
      );
    },
  },

  semanticLayer: {
    buildCatalog: (projectId: string, connectionId: string) =>
      request<{ connection_id: string; metrics_discovered: number; metrics: CatalogMetricDTO[] }>(
        `/semantic-layer/${projectId}/build/${connectionId}`,
        { method: "POST" },
      ),
    normalize: (projectId: string) =>
      request<{ canonical_metrics: number; cross_connection: number; results: NormalizationResultDTO[] }>(
        `/semantic-layer/${projectId}/normalize`,
        { method: "POST" },
      ),
    getCatalog: (projectId: string, connectionId?: string, category?: string) => {
      const qs = new URLSearchParams();
      if (connectionId) qs.set("connection_id", connectionId);
      if (category) qs.set("category", category);
      const q = qs.toString();
      return request<{ total: number; metrics: CatalogMetricDTO[] }>(
        `/semantic-layer/${projectId}/catalog${q ? `?${q}` : ""}`,
      );
    },
  },

  reconciliation: {
    full: (
      projectId: string,
      body: {
        project_id: string;
        source_a_connection_id: string;
        source_a_name?: string;
        source_b_connection_id: string;
        source_b_name?: string;
        counts_a?: Record<string, number>;
        counts_b?: Record<string, number>;
        aggregates_a?: Record<string, number>;
        aggregates_b?: Record<string, number>;
        schema_a?: Record<string, string[]>;
        schema_b?: Record<string, string[]>;
      },
    ) =>
      request<ReconciliationReportDTO>(
        `/reconciliation/${projectId}/full`,
        {
          method: "POST",
          body: JSON.stringify(body),
        },
      ),
    rowCounts: (projectId: string, body: Record<string, unknown>) =>
      request<ReconciliationReportDTO>(
        `/reconciliation/${projectId}/row-counts`,
        { method: "POST", body: JSON.stringify(body) },
      ),
    values: (projectId: string, body: Record<string, unknown>) =>
      request<ReconciliationReportDTO>(
        `/reconciliation/${projectId}/values`,
        { method: "POST", body: JSON.stringify(body) },
      ),
    schemas: (projectId: string, body: Record<string, unknown>) =>
      request<ReconciliationReportDTO>(
        `/reconciliation/${projectId}/schemas`,
        { method: "POST", body: JSON.stringify(body) },
      ),
  },
};
