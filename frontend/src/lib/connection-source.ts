import type { IconName } from "@/components/ui/Icon";

/**
 * How a connection's *kind* is described, in one place.
 *
 * A connection is one of three things: a live database (`source_type`
 * "database", queried through `db_type`), an MCP server, or an analytics source
 * that is **collected** into local fact tables rather than queried live. Only
 * the first has a `db_type`, so any surface that renders `db_type` directly
 * prints an empty string for the other two — which is how a GA4 connection came
 * to be shown as `GA4 prod ()` under a database icon in four different places.
 *
 * Everything that labels or icons a connection routes through here.
 */

/** Sources that collect into local fact tables. `ga4` ships in m0. */
export const ANALYTICS_SOURCE_TYPES = ["ga4", "appstore", "googleplay"] as const;

export type AnalyticsSourceType = (typeof ANALYTICS_SOURCE_TYPES)[number];

const ANALYTICS_LABELS: Record<AnalyticsSourceType, string> = {
  ga4: "GA4",
  appstore: "App Store",
  googleplay: "Google Play",
};

/** Full vendor name, for prose and read-only form fields. */
const ANALYTICS_FULL_LABELS: Record<AnalyticsSourceType, string> = {
  ga4: "Google Analytics 4",
  appstore: "App Store Connect",
  googleplay: "Google Play",
};

const ANALYTICS_SET: ReadonlySet<string> = new Set(ANALYTICS_SOURCE_TYPES);

/** The two fields any labelling decision needs — nothing else is required. */
export interface ConnectionSourceLike {
  db_type?: string | null;
  source_type?: string | null;
}

export function isAnalyticsSource(sourceType: string | null | undefined): boolean {
  return ANALYTICS_SET.has(sourceType ?? "");
}

function analyticsKey(sourceType: string | null | undefined): AnalyticsSourceType | null {
  return isAnalyticsSource(sourceType) ? (sourceType as AnalyticsSourceType) : null;
}

/**
 * Compact label for a badge or a parenthetical: "GA4", "MCP", "postgres".
 * Never empty — an unknown kind says so rather than rendering nothing.
 */
export function connectionSourceLabel(conn: ConnectionSourceLike): string {
  if (conn.source_type === "mcp") return "MCP";
  const analytics = analyticsKey(conn.source_type);
  if (analytics) return ANALYTICS_LABELS[analytics];
  return conn.db_type || "unknown";
}

/** Full-sentence name of the source kind, for read-only form fields. */
export function connectionSourceFullLabel(conn: ConnectionSourceLike): string {
  if (conn.source_type === "mcp") return "MCP server";
  const analytics = analyticsKey(conn.source_type);
  if (analytics) return ANALYTICS_FULL_LABELS[analytics];
  return conn.db_type || "unknown";
}

/** Icon matching the kind — a collected source is not a database. */
export function connectionSourceIcon(conn: ConnectionSourceLike): IconName {
  if (conn.source_type === "mcp") return "link";
  if (isAnalyticsSource(conn.source_type)) return "bar-chart-2";
  return "database";
}
