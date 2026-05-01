// Shared type definitions for the CheckMyData.ai REST API.
// Kept in a single module so domain api modules can import cleanly without
// producing a dense dependency graph (T28). Re-exported from `@/lib/api`.

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
  status?: "idle" | "processing";
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
  response_type?:
    | "text"
    | "sql_result"
    | "knowledge"
    | "error"
    | "clarification_request"
    | "stage_checkpoint"
    | "stage_failed"
    | "step_limit_reached";
  assistant_message_id?: string | null;
  user_message_id?: string | null;
  raw_result?: { columns: string[]; rows: unknown[][]; total_rows: number } | null;
  rag_sources?: Array<{ source_path: string; distance?: number; doc_type?: string }> | null;
  token_usage?: {
    prompt_tokens?: number;
    completion_tokens?: number;
    total_tokens?: number;
  } | null;
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
  sql_results?: Array<{
    query?: string;
    query_explanation?: string;
    visualization?: Record<string, unknown> | null;
    raw_result?: { columns: string[]; rows: unknown[][]; total_rows: number } | null;
    insights?: Array<{ type: string; title: string; description: string; confidence: number }>;
  }> | null;
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
  recent_anomalies: {
    position: number;
    value: number;
    z_score: number;
    direction: string;
    description: string;
  }[];
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
  variants: {
    name: string;
    connection_id: string;
    source_table: string;
    source_column: string;
  }[];
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
