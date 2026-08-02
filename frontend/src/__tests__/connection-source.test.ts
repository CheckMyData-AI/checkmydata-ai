/**
 * One source of truth for "what kind of connection is this?".
 *
 * The GA4 spine added `source_type` but only the connection list learned to
 * read it, so four other surfaces rendered an analytics connection as
 * `GA4 prod ()` — an empty parenthesis where `db_type` used to be — under a
 * database icon. Labelling lives here so a fifth surface cannot get it wrong.
 */
import { describe, it, expect } from "vitest";
import {
  connectionSourceIcon,
  connectionSourceLabel,
  isAnalyticsSource,
} from "@/lib/connection-source";

describe("isAnalyticsSource", () => {
  it("recognises the collected sources", () => {
    expect(isAnalyticsSource("ga4")).toBe(true);
    expect(isAnalyticsSource("appstore")).toBe(true);
    expect(isAnalyticsSource("googleplay")).toBe(true);
  });

  it("rejects everything queried live", () => {
    expect(isAnalyticsSource("database")).toBe(false);
    expect(isAnalyticsSource("mcp")).toBe(false);
    expect(isAnalyticsSource(null)).toBe(false);
    expect(isAnalyticsSource(undefined)).toBe(false);
  });
});

describe("connectionSourceLabel", () => {
  it("names the vendor for an analytics source instead of an absent db_type", () => {
    expect(connectionSourceLabel({ db_type: null, source_type: "ga4" })).toBe("GA4");
    expect(connectionSourceLabel({ db_type: null, source_type: "appstore" })).toBe(
      "App Store",
    );
    expect(connectionSourceLabel({ db_type: null, source_type: "googleplay" })).toBe(
      "Google Play",
    );
  });

  it("names MCP for an MCP source", () => {
    expect(connectionSourceLabel({ db_type: "mcp", source_type: "mcp" })).toBe("MCP");
  });

  it("falls back to the engine for a database connection", () => {
    expect(connectionSourceLabel({ db_type: "postgres", source_type: "database" })).toBe(
      "postgres",
    );
    expect(connectionSourceLabel({ db_type: "mysql" })).toBe("mysql");
  });

  it("never renders an empty label", () => {
    expect(connectionSourceLabel({ db_type: null, source_type: "database" })).toBe(
      "unknown",
    );
    expect(connectionSourceLabel({})).toBe("unknown");
  });
});

describe("connectionSourceIcon", () => {
  it("does not put a database icon on something that is not a database", () => {
    expect(connectionSourceIcon({ db_type: null, source_type: "ga4" })).not.toBe(
      "database",
    );
    expect(connectionSourceIcon({ db_type: "mcp", source_type: "mcp" })).not.toBe(
      "database",
    );
  });

  it("keeps the database icon for a database", () => {
    expect(connectionSourceIcon({ db_type: "postgres", source_type: "database" })).toBe(
      "database",
    );
  });
});
