export interface ParsedConnection {
  db_type: string;
  db_host: string;
  db_port: string;
  db_name: string;
  db_user: string;
  db_password: string;
}

const SCHEME_TO_DB_TYPE: Record<string, string> = {
  postgres: "postgres",
  postgresql: "postgres",
  mysql: "mysql",
  mariadb: "mysql",
  mongodb: "mongodb",
  "mongodb+srv": "mongodb",
  clickhouse: "clickhouse",
  tcp: "clickhouse",
};

const DEFAULT_PORTS: Record<string, string> = {
  postgres: "5432",
  mysql: "3306",
  mongodb: "27017",
  clickhouse: "9000",
};

export function parseConnectionString(raw: string): ParsedConnection | null {
  const trimmed = raw.trim();
  const schemeMatch = trimmed.match(/^([a-zA-Z][a-zA-Z0-9+.-]*):\/\//);
  if (!schemeMatch) return null;

  const scheme = schemeMatch[1].toLowerCase();
  const db_type = SCHEME_TO_DB_TYPE[scheme];
  if (!db_type) return null;

  let url: URL;
  try {
    url = new URL(trimmed);
  } catch {
    return null;
  }

  return {
    db_type,
    db_host: url.hostname || "",
    db_port: url.port || DEFAULT_PORTS[db_type] || "",
    db_name: decodeURIComponent(url.pathname.replace(/^\//, "").split("/")[0] || ""),
    db_user: decodeURIComponent(url.username || ""),
    db_password: decodeURIComponent(url.password || ""),
  };
}
