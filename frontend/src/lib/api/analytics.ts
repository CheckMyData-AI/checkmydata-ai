import { request } from "./_client";
import type {
  ActionRecommendationDTO,
  AnomalyReportDTO,
  CatalogMetricDTO,
  DataGraphMetric,
  DataGraphRelationship,
  ExplorationReportDTO,
  InsightDTO,
  LagResultDTO,
  LogRequestsPage,
  LogSummary,
  LogTraceDetail,
  LogUser,
  LossReportDTO,
  NormalizationResultDTO,
  OpportunityDTO,
  ReconciliationReportDTO,
  TemporalReportDTO,
} from "./types";

export const dataValidation = {
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
    request<
      Array<{
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
      }>
    >(`/data-validation/benchmarks/${connectionId}?project_id=${projectId}`),

  getAnalyticsSummary: (projectId: string) =>
    request<{
      accuracy_rate: number | null;
      total_validations: number;
      active_learnings: number;
      benchmark_count: number;
    }>(`/data-validation/summary/${projectId}`),

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

  confirmFix: (
    investigationId: string,
    body: { accepted: boolean; project_id: string },
  ) =>
    request<{
      ok: boolean;
      status: string;
      learnings_created?: string[];
      notes_created?: string[];
    }>(`/data-validation/investigate/${investigationId}/confirm-fix`, {
      method: "POST",
      body: JSON.stringify(body),
    }),

  runAnomalyAnalysis: (body: {
    project_id: string;
    connection_id: string;
    query?: string;
    question?: string;
    rows: Record<string, unknown>[];
    columns: string[];
  }) =>
    request<{ ok: boolean; total: number; reports: AnomalyReportDTO[]; summary: string }>(
      "/data-validation/anomaly-analysis",
      { method: "POST", body: JSON.stringify(body) },
    ),

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
};

export const logs = {
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
};

export const dataGraph = {
  summary: (projectId: string) =>
    request<{
      total_metrics: number;
      total_relationships: number;
      categories: Record<string, number>;
    }>(`/data-graph/${projectId}/summary`),
  metrics: (projectId: string, params?: { connection_id?: string; category?: string }) => {
    const qs = new URLSearchParams();
    if (params?.connection_id) qs.set("connection_id", params.connection_id);
    if (params?.category) qs.set("category", params.category);
    const q = qs.toString();
    return request<DataGraphMetric[]>(`/data-graph/${projectId}/metrics${q ? `?${q}` : ""}`);
  },
  upsertMetric: (
    projectId: string,
    data: {
      name: string;
      description?: string;
      category?: string;
      connection_id?: string;
    },
  ) =>
    request<{ id: string; name: string }>(`/data-graph/${projectId}/metrics`, {
      method: "POST",
      body: JSON.stringify(data),
    }),
  relationships: (projectId: string, metricId?: string) => {
    const qs = metricId ? `?metric_id=${metricId}` : "";
    return request<DataGraphRelationship[]>(`/data-graph/${projectId}/relationships${qs}`);
  },
  discover: (projectId: string, connectionId: string) =>
    request<{ discovered_count: number }>(
      `/data-graph/${projectId}/discover/${connectionId}`,
      { method: "POST" },
    ),
  deleteMetric: (projectId: string, metricId: string) =>
    request<{ deleted: boolean }>(
      `/data-graph/${projectId}/metrics/${metricId}`,
      { method: "DELETE" },
    ),
};

export const feed = {
  scan: (projectId: string, connectionId: string) =>
    request<{
      insights_created: number;
      insights_updated: number;
      queries_run: number;
      errors: string[];
    }>(`/feed/${projectId}/scan/${connectionId}`, { method: "POST" }),
  scanAll: (projectId: string) =>
    request<{
      total_insights_created: number;
      total_insights_updated: number;
      connections_scanned: number;
    }>(`/feed/${projectId}/scan`, { method: "POST" }),
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
};

export const insights = {
  list: (
    projectId: string,
    params?: {
      connection_id?: string;
      insight_type?: string;
      severity?: string;
      status?: string;
      limit?: number;
    },
  ) => {
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
    request<{
      total_active: number;
      by_type: Record<string, number>;
      by_severity: Record<string, number>;
    }>(`/insights/${projectId}/summary`),
  confirm: (projectId: string, insightId: string, feedback?: string) =>
    request<{ status: string; confidence: number }>(
      `/insights/${projectId}/${insightId}/confirm`,
      { method: "PATCH", body: JSON.stringify({ feedback: feedback || "" }) },
    ),
  dismiss: (projectId: string, insightId: string, feedback?: string) =>
    request<{ status: string; confidence: number }>(
      `/insights/${projectId}/${insightId}/dismiss`,
      { method: "PATCH", body: JSON.stringify({ feedback: feedback || "" }) },
    ),
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
};

export const temporal = {
  analyze: (
    projectId: string,
    values: number[],
    metricName?: string,
    periodLabel?: string,
  ) =>
    request<TemporalReportDTO>(`/temporal/${projectId}/analyze`, {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        values,
        metric_name: metricName || "metric",
        period_label: periodLabel || "day",
      }),
    }),
  detectLag: (
    projectId: string,
    seriesA: number[],
    seriesB: number[],
    maxLag?: number,
  ) =>
    request<LagResultDTO>(`/temporal/${projectId}/lag`, {
      method: "POST",
      body: JSON.stringify({
        project_id: projectId,
        series_a: seriesA,
        series_b: seriesB,
        max_lag: maxLag || 14,
      }),
    }),
};

export const explore = {
  investigate: (projectId: string, connectionId?: string) => {
    const qs = new URLSearchParams();
    if (connectionId) qs.set("connection_id", connectionId);
    const q = qs.toString();
    return request<ExplorationReportDTO>(`/explore/${projectId}${q ? `?${q}` : ""}`, {
      method: "POST",
    });
  },
};

export const semanticLayer = {
  buildCatalog: (projectId: string, connectionId: string) =>
    request<{
      connection_id: string;
      metrics_discovered: number;
      metrics: CatalogMetricDTO[];
    }>(`/semantic-layer/${projectId}/build/${connectionId}`, { method: "POST" }),
  normalize: (projectId: string) =>
    request<{
      canonical_metrics: number;
      cross_connection: number;
      results: NormalizationResultDTO[];
    }>(`/semantic-layer/${projectId}/normalize`, { method: "POST" }),
  getCatalog: (projectId: string, connectionId?: string, category?: string) => {
    const qs = new URLSearchParams();
    if (connectionId) qs.set("connection_id", connectionId);
    if (category) qs.set("category", category);
    const q = qs.toString();
    return request<{ total: number; metrics: CatalogMetricDTO[] }>(
      `/semantic-layer/${projectId}/catalog${q ? `?${q}` : ""}`,
    );
  },
};

export const reconciliation = {
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
    request<ReconciliationReportDTO>(`/reconciliation/${projectId}/full`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  rowCounts: (projectId: string, body: Record<string, unknown>) =>
    request<ReconciliationReportDTO>(`/reconciliation/${projectId}/row-counts`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  values: (projectId: string, body: Record<string, unknown>) =>
    request<ReconciliationReportDTO>(`/reconciliation/${projectId}/values`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  schemas: (projectId: string, body: Record<string, unknown>) =>
    request<ReconciliationReportDTO>(`/reconciliation/${projectId}/schemas`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
};
