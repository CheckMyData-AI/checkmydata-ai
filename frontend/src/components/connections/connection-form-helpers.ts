import type { Connection } from "@/lib/api";

export const DB_TYPES = ["postgres", "mysql", "mongodb", "clickhouse", "mcp"] as const;

export const DEFAULT_PORTS: Record<string, string> = {
  postgres: "5432",
  mysql: "3306",
  mongodb: "27017",
  clickhouse: "9000",
};

export const EXEC_TEMPLATE_PRESETS: Record<string, string> = {
  mysql:
    'MYSQL_PWD="{db_password}" mysql -h {db_host} -P {db_port} -u {db_user} {db_name} --batch --raw',
  postgres:
    'PGPASSWORD="{db_password}" psql -h {db_host} -p {db_port} -U {db_user} -d {db_name} -A -F $\'\\t\' --pset footer=off',
  clickhouse:
    'clickhouse-client -h {db_host} --port {db_port} -u {db_user} --password "{db_password}" -d {db_name} --format TabSeparatedWithNames',
};

export const EMPTY_FORM = {
  name: "",
  db_type: "postgres",
  db_host: "127.0.0.1",
  db_port: "5432",
  db_name: "",
  db_user: "",
  db_password: "",
  ssh_host: "",
  ssh_port: "22",
  ssh_user: "",
  ssh_key_id: "",
  connection_string: "",
  is_read_only: true,
  ssh_exec_mode: false,
  ssh_command_template: "",
  ssh_pre_commands: "",
  mcp_transport_type: "stdio" as "stdio" | "sse",
  mcp_server_command: "",
  mcp_server_args: "",
  mcp_server_url: "",
  mcp_env: "",
};

export type FormState = typeof EMPTY_FORM;

export const inputCls =
  "w-full bg-surface-1 border border-border-subtle rounded-lg px-3 py-2 text-text-primary placeholder-text-muted focus:outline-none focus:ring-1 focus:ring-accent focus:border-accent transition-colors";
export const halfInputCls =
  "bg-surface-1 border border-border-subtle rounded-lg px-3 py-2 text-text-primary placeholder-text-muted focus:outline-none focus:ring-1 focus:ring-accent focus:border-accent transition-colors";

export function formatAge(isoDate: string): string {
  const diff = Date.now() - new Date(isoDate).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

export function safePort(raw: string, fallback: number): number {
  const n = parseInt(raw, 10);
  if (Number.isNaN(n) || n < 1 || n > 65535) return fallback;
  return n;
}

export function connToForm(c: Connection): FormState {
  let preCommands = "";
  if (c.ssh_pre_commands) {
    try {
      const arr = JSON.parse(c.ssh_pre_commands);
      preCommands = Array.isArray(arr) ? arr.join("\n") : "";
    } catch {
      preCommands = "";
    }
  }
  return {
    name: c.name,
    db_type: c.db_type,
    db_host: c.db_host,
    db_port: String(c.db_port),
    db_name: c.db_name,
    db_user: c.db_user || "",
    db_password: "",
    ssh_host: c.ssh_host || "",
    ssh_port: String(c.ssh_port),
    ssh_user: c.ssh_user || "",
    ssh_key_id: c.ssh_key_id || "",
    connection_string: "",
    is_read_only: c.is_read_only,
    ssh_exec_mode: c.ssh_exec_mode,
    ssh_command_template: c.ssh_command_template || "",
    ssh_pre_commands: preCommands,
    mcp_transport_type: (c.mcp_transport_type || "stdio") as "stdio" | "sse",
    mcp_server_command: c.mcp_server_command || "",
    mcp_server_args: "",
    mcp_server_url: c.mcp_server_url || "",
    mcp_env: "",
  };
}
