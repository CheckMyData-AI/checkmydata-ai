import type { Connection } from "@/lib/api";
import { inputBaseCls } from "@/components/ui/Input";
import { parseConnectionString } from "@/lib/connection-string";

export const DB_TYPES = ["postgres", "mysql", "mongodb", "clickhouse", "mcp"] as const;

export const DEFAULT_PORTS: Record<string, string> = {
  postgres: "5432",
  mysql: "3306",
  mongodb: "27017",
  clickhouse: "9000",
};

/**
 * C-02: the form used to ship its own exec templates and auto-fill one. They were the
 * two shapes the backend had already removed — `{db_password}` on the remote argv, where
 * `ps` on the bastion reads it, and the SQL piped to the client's stdin, where `psql`
 * treats `\!` as a shell command. Auto-filling also made every exec connection a CUSTOM
 * template, which is the one shape the server cannot decorate for read-only mode.
 *
 * The server serves its own, read-only, at `GET /connections/exec-templates`.
 */
export const PASSWORD_PLACEHOLDER = "{db_password}";

/**
 * A custom command must not carry the password: the bastion's `ps` is not private.
 * Mirrors `validate_new_command_template` (backend `exec_templates.py`), which is the
 * authority — this only says it before the save does. `$DBPASS` is safe solely as an
 * environment assignment (T05b, F-C2).
 */
export function commandTemplateError(template: string): string | null {
  if (!template.trim()) return null;
  if (template.includes(PASSWORD_PLACEHOLDER)) {
    return 'Remove {db_password}: it would be visible in the process list on the bastion. Pass $DBPASS through an environment variable instead, e.g. MYSQL_PWD="$DBPASS" mysql …';
  }
  const ref = /\$\{?DBPASS\b\}?/g;
  for (let m = ref.exec(template); m !== null; m = ref.exec(template)) {
    if (!/(?:^|[\s;&|(])[A-Za-z_][A-Za-z0-9_]*=["']?$/.test(template.slice(0, m.index))) {
      return 'Use $DBPASS only as an environment variable (e.g. MYSQL_PWD="$DBPASS" mysql …): as an argument it is visible in the process list on the bastion.';
    }
  }
  return null;
}

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

export const inputCls = inputBaseCls;
/**
 * The half-width field. It carried its own copy of the field style — and its own
 * focus treatment, a 1px ring plus a border swap — until the close-out walk
 * found it. There is one field in this design; a "half" one differs in width,
 * which is the caller's business, not the constant's.
 */
export const halfInputCls = inputBaseCls;

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

/**
 * The port an empty field means for THIS engine (C-15).
 *
 * Callers passed a literal `5432` whatever the engine was, so clearing the port on a
 * MySQL connection saved PostgreSQL's — a connection that then failed to connect for a
 * reason the form had just invented. The defaults already live in `DEFAULT_PORTS`; this
 * reads them instead of repeating one of them.
 */
export function portForEngine(raw: string, dbType: string): number {
  return safePort(raw, safePort(DEFAULT_PORTS[dbType] ?? "", 5432));
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
    // A non-database source carries nulls here. `String(null)` would put the
    // literal "null" in the port box and a null `value` would make React warn
    // about an uncontrolled input, so each one degrades to the empty form.
    db_type: c.db_type ?? EMPTY_FORM.db_type,
    db_host: c.db_host || EMPTY_FORM.db_host,
    db_port: c.db_port == null ? EMPTY_FORM.db_port : String(c.db_port),
    db_name: c.db_name ?? "",
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

export function applyConnectionString(
  form: FormState,
  raw: string,
): { form: FormState; detected: string | null } {
  const parsed = parseConnectionString(raw);
  if (!parsed) return { form, detected: null };
  const next: FormState = {
    ...form,
    db_type: parsed.db_type,
    ...(parsed.db_host ? { db_host: parsed.db_host } : {}),
    ...(parsed.db_port ? { db_port: parsed.db_port } : {}),
    ...(parsed.db_name ? { db_name: parsed.db_name } : {}),
    ...(parsed.db_user ? { db_user: parsed.db_user } : {}),
    ...(parsed.db_password ? { db_password: parsed.db_password } : {}),
  };
  return { form: next, detected: parsed.db_type };
}

export type BuiltUpdates =
  | { updates: Record<string, unknown>; error?: undefined }
  | { error: string; updates?: undefined };

/**
 * Every field the database/MCP edit form can PATCH, built from a form state.
 *
 * Built twice on save — from the form as edited and from the snapshot taken when the
 * edit began — and only the difference is sent (`changedFields`). Sending everything was
 * three defects at once (T05b, `docs/audits/2026-09-23-recent-work-audit.md` §3.2):
 * `ssh_key_id` always travelled, so the backend's "verify only the key being attached"
 * (C-04) ran on every rename and 404'd a co-owner (F-C1); `ssh_command_template` always
 * travelled, so a stored legacy template the C-02 validator now refuses made the
 * connection unsaveable (F-C2); and the form starts with empty `connection_string`,
 * `mcp_server_args` and `mcp_env` (they are never echoed back), so their explicit `null`
 * wiped a DSN or an MCP environment on any save (F-C9).
 */
export function buildConnectionUpdates(
  form: FormState,
  { useConnString, isMCP }: { useConnString: boolean; isMCP: boolean },
): BuiltUpdates {
  const updates: Record<string, unknown> = {};
  const fields = [
    "name",
    "db_type",
    "db_host",
    "db_name",
    "db_user",
    "ssh_host",
    "ssh_user",
    "ssh_key_id",
  ] as const;
  for (const f of fields) {
    updates[f] = form[f] !== "" ? form[f] : null;
  }
  updates.db_port = portForEngine(form.db_port, form.db_type);
  updates.ssh_port = safePort(form.ssh_port, 22);
  if (form.db_password) updates.db_password = form.db_password;
  if (useConnString && form.connection_string) {
    updates.connection_string = form.connection_string;
  } else if (!useConnString) {
    updates.connection_string = null;
  }
  updates.name = form.name;
  updates.is_read_only = form.is_read_only;
  updates.ssh_exec_mode = form.ssh_exec_mode;
  updates.ssh_command_template = form.ssh_command_template || null;
  updates.ssh_pre_commands = form.ssh_pre_commands.trim()
    ? form.ssh_pre_commands.split("\n").filter((l) => l.trim())
    : null;

  if (isMCP) {
    updates.source_type = "mcp";
    updates.mcp_transport_type = form.mcp_transport_type;
    updates.mcp_server_command = form.mcp_server_command || null;
    updates.mcp_server_url = form.mcp_server_url || null;
    updates.mcp_server_args = form.mcp_server_args.trim()
      ? form.mcp_server_args.split(/\s+/).filter(Boolean)
      : null;
    if (form.mcp_env.trim()) {
      try {
        updates.mcp_env = JSON.parse(form.mcp_env);
      } catch {
        return { error: 'MCP env must be valid JSON (e.g. {"KEY": "value"})' };
      }
    } else {
      updates.mcp_env = null;
    }
  }
  return { updates };
}

/** The keys of *updates* whose value differs from *baseline* — what the user changed. */
export function changedFields(
  updates: Record<string, unknown>,
  baseline: Record<string, unknown>,
): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(updates)) {
    if (!(key in baseline) || JSON.stringify(value) !== JSON.stringify(baseline[key])) {
      out[key] = value;
    }
  }
  return out;
}

const HOST_FIELDS = ["db_host", "db_port", "db_name", "db_user"] as const;

export type EditPatch =
  | { ok: true; patch: Record<string, unknown> }
  | { ok: false; error: string };

/**
 * The PATCH body for an edit: what differs from the snapshot taken when the edit began.
 *
 * The snapshot is built with `useConnString: false` because that is how every edit starts
 * (`handleEdit`) — building it with the current toggle would hide a DSN the user just
 * typed. Editing a host field without a DSN moves the connection onto its fields, so the
 * stored DSN is cleared then and only then.
 */
export function editPatch(
  form: FormState,
  snapshot: FormState,
  opts: { useConnString: boolean; isMCP: boolean },
): EditPatch {
  const now = buildConnectionUpdates(form, opts);
  if (now.error !== undefined) return { ok: false, error: now.error };
  const before = buildConnectionUpdates(snapshot, { useConnString: false, isMCP: opts.isMCP });
  const patch = changedFields(now.updates, before.updates ?? {});
  if (!opts.useConnString && HOST_FIELDS.some((f) => f in patch)) {
    patch.connection_string = null;
  }
  return { ok: true, patch };
}
