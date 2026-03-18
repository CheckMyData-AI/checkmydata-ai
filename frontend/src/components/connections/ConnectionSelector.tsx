"use client";

import { useEffect, useRef, useState } from "react";
import { api, type Connection } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { confirmAction } from "@/components/ui/ConfirmModal";
import { toast } from "@/stores/toast-store";
import { Icon } from "@/components/ui/Icon";
import { ActionButton } from "@/components/ui/ActionButton";
import { StatusDot } from "@/components/ui/StatusDot";
import { Tooltip } from "@/components/ui/Tooltip";
import { LearningsPanel } from "@/components/learnings/LearningsPanel";

const DB_TYPES = ["postgres", "mysql", "mongodb", "clickhouse"];

function formatAge(isoDate: string): string {
  const diff = Date.now() - new Date(isoDate).getTime();
  const mins = Math.floor(diff / 60_000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
}

const DEFAULT_PORTS: Record<string, string> = {
  postgres: "5432",
  mysql: "3306",
  mongodb: "27017",
  clickhouse: "9000",
};

const EXEC_TEMPLATE_PRESETS: Record<string, string> = {
  mysql:
    'MYSQL_PWD="{db_password}" mysql -h {db_host} -P {db_port} -u {db_user} {db_name} --batch --raw',
  postgres:
    'PGPASSWORD="{db_password}" psql -h {db_host} -p {db_port} -U {db_user} -d {db_name} -A -F $\'\\t\' --pset footer=off',
  clickhouse:
    'clickhouse-client -h {db_host} --port {db_port} -u {db_user} --password "{db_password}" -d {db_name} --format TabSeparatedWithNames',
};

const EMPTY_FORM = {
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
};

type FormState = typeof EMPTY_FORM;

const inputCls =
  "w-full bg-surface-1 border border-border-subtle rounded-lg px-3 py-2 text-text-primary placeholder-text-muted focus:outline-none focus:ring-1 focus:ring-accent focus:border-accent transition-colors";
const halfInputCls =
  "bg-surface-1 border border-border-subtle rounded-lg px-3 py-2 text-text-primary placeholder-text-muted focus:outline-none focus:ring-1 focus:ring-accent focus:border-accent transition-colors";

function safePort(raw: string, fallback: number): number {
  const n = parseInt(raw, 10);
  if (Number.isNaN(n) || n < 1 || n > 65535) return fallback;
  return n;
}

function connToForm(c: Connection): FormState {
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
  };
}

export function ConnectionSelector() {
  const {
    activeProject,
    connections,
    activeConnection,
    setActiveConnection,
    sshKeys,
  } = useAppStore();
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>({ ...EMPTY_FORM });
  const [useConnString, setUseConnString] = useState(false);
  const [checking, setChecking] = useState<string | null>(null);
  const [status, setStatus] = useState<
    Record<string, { success: boolean; error?: string }>
  >({});
  const [refreshing, setRefreshing] = useState<string | null>(null);
  const [indexing, setIndexing] = useState<string | null>(null);
  const [indexStatus, setIndexStatus] = useState<
    Record<
      string,
      {
        is_indexed: boolean;
        active_tables?: number;
        total_tables?: number;
        is_indexing?: boolean;
        indexed_at?: string;
      }
    >
  >({});
  const [learningsCount, setLearningsCount] = useState<Record<string, number>>({});
  const [showLearnings, setShowLearnings] = useState<string | null>(null);
  const [syncing, setSyncing] = useState<string | null>(null);
  const [syncStatus, setSyncStatus] = useState<
    Record<
      string,
      {
        is_synced: boolean;
        is_syncing?: boolean;
        synced_tables?: number;
        total_tables?: number;
        synced_at?: string;
        sync_status?: string;
      }
    >
  >({});
  const indexPollRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const syncPollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    return () => {
      if (indexPollRef.current) clearInterval(indexPollRef.current);
      if (syncPollRef.current) clearInterval(syncPollRef.current);
    };
  }, []);

  useEffect(() => {
    setStatus({});
    setEditingId(null);
    setShowCreate(false);
    setIndexStatus({});
    setSyncStatus({});
    resetForm();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeProject?.id]);

  useEffect(() => {
    connections.forEach((c) => {
      api.connections
        .indexDbStatus(c.id)
        .then((s) => {
          setIndexStatus((prev) => ({
            ...prev,
            [c.id]: {
              is_indexed: s.is_indexed,
              active_tables: s.active_tables,
              total_tables: s.total_tables,
              is_indexing: s.is_indexing,
              indexed_at: s.indexed_at ?? undefined,
            },
          }));
        })
        .catch(() => {});
      api.connections
        .syncStatus(c.id)
        .then((s) => {
          setSyncStatus((prev) => ({
            ...prev,
            [c.id]: {
              is_synced: s.is_synced,
              is_syncing: s.is_syncing,
              synced_tables: s.synced_tables,
              total_tables: s.total_tables,
              synced_at: s.synced_at ?? undefined,
              sync_status: s.sync_status,
            },
          }));
        })
        .catch(() => {});
      api.connections
        .learningsStatus(c.id)
        .then((s) => {
          setLearningsCount((prev) => ({ ...prev, [c.id]: s.total_active }));
        })
        .catch(() => {});
    });
  }, [connections]);

  const resetForm = () => {
    setForm({ ...EMPTY_FORM });
    setUseConnString(false);
  };

  const hasSSH = form.ssh_host.trim().length > 0;

  const handleCreate = async () => {
    if (!activeProject || !form.name.trim()) return;
    if (form.ssh_host.trim() && (!form.ssh_user.trim() || !form.ssh_key_id)) {
      toast("SSH host is set — please provide an SSH user and key.", "error");
      return;
    }
    const preCommandsList = form.ssh_pre_commands.trim()
      ? form.ssh_pre_commands.split("\n").filter((l) => l.trim())
      : null;
    try {
      const conn = await api.connections.create({
        project_id: activeProject.id,
        name: form.name,
        db_type: form.db_type,
        db_host: form.db_host,
        db_port: safePort(form.db_port, 5432),
        db_name: form.db_name,
        db_user: form.db_user || null,
        db_password: form.db_password || null,
        ssh_host: form.ssh_host || null,
        ssh_port: safePort(form.ssh_port, 22),
        ssh_user: form.ssh_user || null,
        ssh_key_id: form.ssh_key_id || null,
        connection_string: useConnString ? form.connection_string || null : null,
        is_read_only: form.is_read_only,
        ssh_exec_mode: form.ssh_exec_mode,
        ssh_command_template: form.ssh_command_template || null,
        ssh_pre_commands: preCommandsList,
      });
      useAppStore.setState((state) => ({
        connections: [conn, ...state.connections],
      }));
      setActiveConnection(conn);
      setShowCreate(false);
      resetForm();
      toast("Connection created", "success");
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "Failed to create connection",
        "error",
      );
    }
  };

  const handleEdit = (c: Connection) => {
    setEditingId(c.id);
    setForm(connToForm(c));
    setShowCreate(false);
    setUseConnString(false);
  };

  const handleUpdate = async () => {
    if (!editingId) return;
    if (!form.name.trim()) {
      toast("Connection name is required.", "error");
      return;
    }
    if (form.ssh_host.trim() && (!form.ssh_user.trim() || !form.ssh_key_id)) {
      toast("SSH host is set — please provide an SSH user and key.", "error");
      return;
    }
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
    updates.db_port = safePort(form.db_port, 5432);
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
    const preCommandsList = form.ssh_pre_commands.trim()
      ? form.ssh_pre_commands.split("\n").filter((l) => l.trim())
      : null;
    updates.ssh_pre_commands = preCommandsList;

    try {
      const updated = await api.connections.update(editingId, updates);
      useAppStore.setState((state) => ({
        connections: state.connections.map((c) =>
          c.id === updated.id ? updated : c,
        ),
        ...(state.activeConnection?.id === updated.id
          ? { activeConnection: updated }
          : {}),
      }));
      setStatus((prev) => {
        const next = { ...prev };
        delete next[editingId];
        return next;
      });
      setEditingId(null);
      resetForm();
      toast("Connection updated", "success");
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "Failed to update connection",
        "error",
      );
    }
  };

  const handleCheckStatus = async (id: string) => {
    setChecking(id);
    try {
      const result = await api.connections.test(id);
      setStatus((prev) => ({ ...prev, [id]: result }));
      if (result.success) {
        toast("Connected", "success");
      } else {
        toast(`Not connected: ${result.error || "unknown error"}`, "error");
      }
    } catch (err) {
      const error =
        err instanceof Error ? err.message : "Connection check failed";
      setStatus((prev) => ({ ...prev, [id]: { success: false, error } }));
      toast(`Not connected: ${error}`, "error");
    } finally {
      setChecking(null);
    }
  };

  const handleRefreshSchema = async (id: string) => {
    setRefreshing(id);
    try {
      await api.connections.refreshSchema(id);
      toast("Schema refreshed", "success");
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "Schema refresh failed",
        "error",
      );
    } finally {
      setRefreshing(null);
    }
  };

  const handleIndexDb = async (id: string) => {
    setIndexing(id);
    try {
      await api.connections.indexDb(id);
      toast("Database indexing started", "success");
      setIndexStatus((prev) => ({
        ...prev,
        [id]: {
          ...prev[id],
          is_indexing: true,
          is_indexed: prev[id]?.is_indexed ?? false,
        },
      }));
      if (indexPollRef.current) clearInterval(indexPollRef.current);
      const pollStart = Date.now();
      const MAX_POLL_MS = 10 * 60 * 1000;
      indexPollRef.current = setInterval(async () => {
        if (Date.now() - pollStart > MAX_POLL_MS) {
          if (indexPollRef.current) clearInterval(indexPollRef.current);
          indexPollRef.current = null;
          setIndexing(null);
          toast("DB indexing timed out — check connection settings", "error");
          return;
        }
        try {
          const s = await api.connections.indexDbStatus(id);
          setIndexStatus((prev) => ({
            ...prev,
            [id]: {
              is_indexed: s.is_indexed,
              active_tables: s.active_tables,
              total_tables: s.total_tables,
              is_indexing: s.is_indexing,
              indexed_at: s.indexed_at ?? undefined,
            },
          }));
          if (!s.is_indexing) {
            if (indexPollRef.current) clearInterval(indexPollRef.current);
            indexPollRef.current = null;
            setIndexing(null);
            if (s.is_indexed) {
              toast(
                `DB indexed: ${s.active_tables}/${s.total_tables} active tables`,
                "success",
              );
            }
          }
        } catch {
          if (indexPollRef.current) clearInterval(indexPollRef.current);
          indexPollRef.current = null;
          setIndexing(null);
        }
      }, 3000);
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "DB indexing failed",
        "error",
      );
      setIndexing(null);
    }
  };

  const handleSync = async (id: string) => {
    setSyncing(id);
    try {
      await api.connections.triggerSync(id);
      toast("Code-DB sync started", "success");
      setSyncStatus((prev) => ({
        ...prev,
        [id]: {
          ...prev[id],
          is_syncing: true,
          is_synced: prev[id]?.is_synced ?? false,
        },
      }));
      if (syncPollRef.current) clearInterval(syncPollRef.current);
      const syncPollStart = Date.now();
      const SYNC_MAX_POLL_MS = 10 * 60 * 1000;
      syncPollRef.current = setInterval(async () => {
        if (Date.now() - syncPollStart > SYNC_MAX_POLL_MS) {
          if (syncPollRef.current) clearInterval(syncPollRef.current);
          syncPollRef.current = null;
          setSyncing(null);
          toast("Code-DB sync timed out — check connection settings", "error");
          return;
        }
        try {
          const s = await api.connections.syncStatus(id);
          setSyncStatus((prev) => ({
            ...prev,
            [id]: {
              is_synced: s.is_synced,
              is_syncing: s.is_syncing,
              synced_tables: s.synced_tables,
              total_tables: s.total_tables,
              synced_at: s.synced_at ?? undefined,
              sync_status: s.sync_status,
            },
          }));
          if (!s.is_syncing) {
            if (syncPollRef.current) clearInterval(syncPollRef.current);
            syncPollRef.current = null;
            setSyncing(null);
            if (s.is_synced) {
              toast(
                `Code-DB synced: ${s.synced_tables ?? 0}/${s.total_tables ?? 0} tables matched`,
                "success",
              );
            }
          }
        } catch {
          if (syncPollRef.current) clearInterval(syncPollRef.current);
          syncPollRef.current = null;
          setSyncing(null);
        }
      }, 3000);
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "Code-DB sync failed",
        "error",
      );
      setSyncing(null);
    }
  };

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (!(await confirmAction("Delete this connection?"))) return;
    try {
      await api.connections.delete(id);
      useAppStore.setState((state) => ({
        connections: state.connections.filter((c) => c.id !== id),
        ...(state.activeConnection?.id === id
          ? { activeConnection: null }
          : {}),
      }));
      setStatus((prev) => {
        const next = { ...prev };
        delete next[id];
        return next;
      });
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "Failed to delete connection",
        "error",
      );
    }
  };

  if (!activeProject) return null;

  const isFormOpen = showCreate || editingId !== null;

  const formUI = (
    <div className="space-y-2.5 p-3 bg-surface-1 rounded-lg border border-border-subtle text-xs">
      <input
        value={form.name}
        onChange={(e) => setForm({ ...form, name: e.target.value })}
        placeholder="Connection name"
        aria-label="Connection name"
        className={inputCls}
      />
      <select
        value={form.db_type}
        aria-label="Database type"
        onChange={(e) => {
          const newType = e.target.value;
          const knownDefaults = Object.values(DEFAULT_PORTS);
          const presetValues = Object.values(EXEC_TEMPLATE_PRESETS);
          setForm((prev) => {
            const autoTemplate =
              prev.ssh_exec_mode &&
              newType !== "mongodb" &&
              (!prev.ssh_command_template ||
                presetValues.includes(prev.ssh_command_template))
                ? EXEC_TEMPLATE_PRESETS[newType] || ""
                : prev.ssh_command_template;
            return {
              ...prev,
              db_type: newType,
              ...(knownDefaults.includes(prev.db_port)
                ? { db_port: DEFAULT_PORTS[newType] || "5432" }
                : {}),
              ...(newType === "mongodb" ? { ssh_exec_mode: false } : {}),
              ssh_command_template: autoTemplate,
            };
          });
        }}
        className={inputCls}
      >
        {DB_TYPES.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>

      <label className="flex items-center gap-2 text-text-tertiary cursor-pointer select-none">
        <input
          type="checkbox"
          checked={useConnString}
          onChange={(e) => setUseConnString(e.target.checked)}
          className="accent-accent"
        />
        Use connection string
      </label>

      {useConnString ? (
        <input
          value={form.connection_string}
          onChange={(e) =>
            setForm({ ...form, connection_string: e.target.value })
          }
          placeholder="postgresql://user:pass@host:5432/dbname"
          aria-label="Connection string"
          className={inputCls}
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            <input
              value={form.db_host}
              onChange={(e) => setForm({ ...form, db_host: e.target.value })}
              placeholder="Host"
              aria-label="Database host"
              className={halfInputCls}
            />
            <input
              value={form.db_port}
              onChange={(e) => setForm({ ...form, db_port: e.target.value })}
              placeholder="Port"
              aria-label="Database port"
              className={halfInputCls}
            />
          </div>
          <input
            value={form.db_name}
            onChange={(e) => setForm({ ...form, db_name: e.target.value })}
            placeholder="Database name"
            aria-label="Database name"
            className={inputCls}
          />
          <div className="grid grid-cols-2 gap-2">
            <input
              value={form.db_user}
              onChange={(e) => setForm({ ...form, db_user: e.target.value })}
              placeholder="Username"
              aria-label="Database username"
              className={halfInputCls}
            />
            <input
              type="password"
              value={form.db_password}
              onChange={(e) =>
                setForm({ ...form, db_password: e.target.value })
              }
              placeholder={
                editingId ? "New password (leave blank)" : "Password"
              }
              aria-label="Database password"
              className={halfInputCls}
            />
          </div>
        </>
      )}

      {useConnString ? (
        <p className="text-[10px] text-text-muted px-1">
          SSH tunnel is not used with connection strings. Switch to individual
          fields to configure SSH.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            <input
              value={form.ssh_host}
              onChange={(e) => setForm({ ...form, ssh_host: e.target.value })}
              placeholder="SSH Host (optional)"
              aria-label="SSH host"
              className={halfInputCls}
            />
            <input
              value={form.ssh_port}
              onChange={(e) => setForm({ ...form, ssh_port: e.target.value })}
              placeholder="SSH Port"
              aria-label="SSH port"
              className={halfInputCls}
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <input
              value={form.ssh_user}
              onChange={(e) => setForm({ ...form, ssh_user: e.target.value })}
              placeholder="SSH User"
              aria-label="SSH user"
              className={halfInputCls}
            />
            <select
              value={form.ssh_key_id}
              aria-label="SSH key"
              onChange={(e) =>
                setForm({ ...form, ssh_key_id: e.target.value })
              }
              className={halfInputCls}
            >
              <option value="">SSH Key (none)</option>
              {sshKeys.map((k) => (
                <option key={k.id} value={k.id}>
                  {k.name}
                </option>
              ))}
            </select>
          </div>
          {hasSSH && (!form.ssh_user.trim() || !form.ssh_key_id) && (
            <p className="text-[10px] text-warning px-1">
              SSH tunnel requires a user and key.
            </p>
          )}
          {hasSSH &&
            form.ssh_user.trim() &&
            form.ssh_key_id &&
            !form.ssh_exec_mode && (
              <p className="text-[10px] text-text-muted px-1">
                SSH tunnel mode: connects via port-forwarding and a native
                driver.
              </p>
            )}

          {hasSSH && (
            <div className="space-y-2 border border-border-subtle rounded-lg p-2.5">
              <label
                className={`flex items-center gap-2 cursor-pointer select-none ${form.db_type === "mongodb" ? "text-text-muted" : "text-text-tertiary"}`}
              >
                <input
                  type="checkbox"
                  checked={form.ssh_exec_mode}
                  onChange={(e) => {
                    const on = e.target.checked;
                    setForm((prev) => ({
                      ...prev,
                      ssh_exec_mode: on,
                      ...(on && !prev.ssh_command_template
                        ? {
                            ssh_command_template:
                              EXEC_TEMPLATE_PRESETS[prev.db_type] || "",
                          }
                        : {}),
                    }));
                  }}
                  className="accent-purple-500"
                  disabled={form.db_type === "mongodb"}
                />
                <span className="flex items-center gap-1.5">
                  <Icon name="terminal" size={12} />
                  SSH Exec Mode
                  {form.db_type === "mongodb" ? (
                    <span className="text-[9px] text-text-muted">
                      (not supported for MongoDB)
                    </span>
                  ) : (
                    <span className="text-[9px] text-text-muted">
                      (CLI on server)
                    </span>
                  )}
                </span>
              </label>
              {!form.ssh_exec_mode && (
                <p className="text-[9px] text-text-muted px-1">
                  Enable only if port forwarding is blocked or you need specific
                  CLI options.
                </p>
              )}

              {form.ssh_exec_mode && (
                <>
                  <div className="flex items-center gap-2">
                    <span className="text-[10px] text-text-muted shrink-0">
                      Template:
                    </span>
                    <select
                      onChange={(e) => {
                        if (e.target.value) {
                          setForm((prev) => ({
                            ...prev,
                            ssh_command_template: e.target.value,
                          }));
                        }
                      }}
                      className="flex-1 bg-surface-1 border border-border-subtle rounded-lg px-2 py-1.5 text-text-secondary text-[10px]"
                      defaultValue=""
                    >
                      <option value="" disabled>
                        Load preset...
                      </option>
                      {Object.entries(EXEC_TEMPLATE_PRESETS).map(
                        ([key, val]) => (
                          <option key={key} value={val}>
                            {key}
                          </option>
                        ),
                      )}
                    </select>
                  </div>
                  <textarea
                    value={form.ssh_command_template}
                    onChange={(e) =>
                      setForm({
                        ...form,
                        ssh_command_template: e.target.value,
                      })
                    }
                    placeholder="Command template, e.g.: mysql -h {db_host} ..."
                    rows={2}
                    className={inputCls + " font-mono text-[10px] resize-y"}
                  />
                  <p className="text-[9px] text-text-muted px-1">
                    Placeholders: {"{db_host}"} {"{db_port}"} {"{db_user}"}{" "}
                    {"{db_password}"} {"{db_name}"}. Query piped via stdin.
                  </p>
                  <textarea
                    value={form.ssh_pre_commands}
                    onChange={(e) =>
                      setForm({ ...form, ssh_pre_commands: e.target.value })
                    }
                    placeholder={
                      "Pre-commands (one per line, optional):\nsource ~/.bashrc"
                    }
                    rows={2}
                    className={inputCls + " font-mono text-[10px] resize-y"}
                  />
                </>
              )}
            </div>
          )}
        </>
      )}

      <label className="flex items-center gap-2 text-text-tertiary cursor-pointer select-none">
        <input
          type="checkbox"
          checked={form.is_read_only}
          onChange={(e) =>
            setForm({ ...form, is_read_only: e.target.checked })
          }
          className="accent-accent"
        />
        <span className="flex items-center gap-1.5">
          <Icon name="shield" size={12} />
          Read-only mode
        </span>
      </label>

      <div className="flex gap-2 pt-1">
        <button
          onClick={editingId ? handleUpdate : handleCreate}
          className="flex-1 px-3 py-2 bg-accent text-white font-medium rounded-lg hover:bg-accent-hover transition-colors"
        >
          {editingId ? "Save Changes" : "Create Connection"}
        </button>
        {editingId && (
          <button
            onClick={() => {
              setEditingId(null);
              resetForm();
            }}
            className="px-3 py-2 text-text-tertiary hover:text-text-primary transition-colors"
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  );

  function getConnStatus(id: string): "success" | "error" | "loading" | "idle" {
    if (checking === id) return "loading";
    const s = status[id];
    if (!s) return "idle";
    return s.success ? "success" : "error";
  }

  function getConnStatusTitle(id: string): string {
    if (checking === id) return "Checking...";
    const s = status[id];
    if (!s) return "Not checked";
    return s.success ? "Connected" : s.error || "Error";
  }

  return (
    <div className="space-y-1.5 px-1">
      <div className="flex justify-end px-1">
        <button
          onClick={() => {
            if (showCreate) {
              setShowCreate(false);
              resetForm();
            } else {
              setEditingId(null);
              resetForm();
              setShowCreate(true);
            }
          }}
          className="flex items-center gap-1 text-[11px] text-accent hover:text-accent-hover transition-colors"
        >
          {showCreate ? (
            "Cancel"
          ) : (
            <>
              <Icon name="plus" size={12} />
              New
            </>
          )}
        </button>
      </div>

      {isFormOpen && formUI}

      <div className="space-y-0.5 max-h-64 overflow-y-auto sidebar-scroll">
        {connections.map((c) => {
          const isActive = activeConnection?.id === c.id;
          const idx = indexStatus[c.id];
          const sync = syncStatus[c.id];

          return (
            <div
              key={c.id}
              className={`group rounded-lg transition-colors ${
                isActive ? "bg-surface-2" : "hover:bg-surface-2/50"
              }`}
            >
              <button
                onClick={() => setActiveConnection(c)}
                className="w-full text-left px-2.5 py-2"
              >
                <div className="flex items-center gap-2">
                  <StatusDot
                    status={getConnStatus(c.id)}
                    title={getConnStatusTitle(c.id)}
                    size="md"
                  />
                  <span
                    className={`text-[13px] font-medium truncate ${
                      isActive
                        ? "text-text-primary"
                        : "text-text-secondary"
                    }`}
                  >
                    {c.name}
                  </span>
                </div>
                <div className="flex items-center gap-1.5 mt-1 ml-4 flex-wrap">
                  <span className="text-[10px] text-text-muted font-mono uppercase">
                    {c.db_type}
                  </span>
                  {c.is_read_only && (
                    <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-surface-3/50 text-text-tertiary">
                      RO
                    </span>
                  )}
                  {c.ssh_exec_mode && (
                    <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-purple-900/30 text-purple-400">
                      EXEC
                    </span>
                  )}
                  {idx?.is_indexing ? (
                    <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-warning-muted text-warning animate-pulse-dot">
                      IDX...
                    </span>
                  ) : idx?.is_indexed ? (
                    <Tooltip label={`Indexed: ${idx.active_tables ?? "?"}/${idx.total_tables ?? "?"} active${idx.indexed_at ? ` (${formatAge(idx.indexed_at)})` : ""}. Click to re-index`} position="bottom">
                      <button
                        type="button"
                        aria-label="Re-index database"
                        className="text-[9px] px-1.5 py-0.5 rounded-full bg-success-muted text-success cursor-pointer hover:bg-success/20 outline-none focus-visible:ring-2 focus-visible:ring-accent"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleIndexDb(c.id);
                        }}
                      >
                        IDX
                      </button>
                    </Tooltip>
                  ) : isActive ? (
                    <Tooltip label="Index database schema" position="bottom">
                      <button
                        type="button"
                        aria-label="Index database schema"
                        className="text-[9px] px-1.5 py-0.5 rounded-full bg-surface-3/50 text-text-muted cursor-pointer hover:text-text-secondary hover:bg-surface-3 outline-none focus-visible:ring-2 focus-visible:ring-accent"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleIndexDb(c.id);
                        }}
                      >
                        IDX
                      </button>
                    </Tooltip>
                  ) : null}
                  {sync?.is_syncing ? (
                    <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-warning-muted text-warning animate-pulse-dot">
                      SYNC...
                    </span>
                  ) : sync?.is_synced ? (
                    <Tooltip label={`Synced: ${sync.synced_tables ?? "?"}/${sync.total_tables ?? "?"} tables${sync.synced_at ? ` (${formatAge(sync.synced_at)})` : ""}. Click to re-sync`} position="bottom">
                      <button
                        type="button"
                        aria-label="Re-sync database"
                        className="text-[9px] px-1.5 py-0.5 rounded-full bg-success-muted text-success cursor-pointer hover:bg-success/20 outline-none focus-visible:ring-2 focus-visible:ring-accent"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleSync(c.id);
                        }}
                      >
                        SYNC
                      </button>
                    </Tooltip>
                  ) : sync?.sync_status === "stale" ? (
                    <Tooltip label="Sync data is stale -- click to re-sync" position="bottom">
                      <button
                        type="button"
                        aria-label="Re-sync stale data"
                        className="text-[9px] px-1.5 py-0.5 rounded-full bg-warning-muted text-warning cursor-pointer hover:bg-warning/20 outline-none focus-visible:ring-2 focus-visible:ring-accent"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleSync(c.id);
                        }}
                      >
                        SYNC
                      </button>
                    </Tooltip>
                  ) : isActive && idx?.is_indexed ? (
                    <Tooltip label="Run Code-DB Sync" position="bottom">
                      <button
                        type="button"
                        aria-label="Run Code-DB Sync"
                        className="text-[9px] px-1.5 py-0.5 rounded-full bg-surface-3/50 text-text-muted cursor-pointer hover:text-text-secondary hover:bg-surface-3 outline-none focus-visible:ring-2 focus-visible:ring-accent"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleSync(c.id);
                        }}
                      >
                        SYNC
                      </button>
                    </Tooltip>
                  ) : null}
                  {(learningsCount[c.id] ?? 0) > 0 ? (
                    <Tooltip label={`${learningsCount[c.id]} agent learnings. Click to manage`} position="bottom">
                      <button
                        type="button"
                        aria-label="Manage agent learnings"
                        className="text-[9px] px-1.5 py-0.5 rounded-full bg-blue-900/30 text-blue-400 cursor-pointer hover:bg-blue-900/50 outline-none focus-visible:ring-2 focus-visible:ring-accent"
                        onClick={(e) => {
                          e.stopPropagation();
                          setShowLearnings(showLearnings === c.id ? null : c.id);
                        }}
                      >
                        LEARN {learningsCount[c.id]}
                      </button>
                    </Tooltip>
                  ) : null}
                </div>
              </button>
              <div className="hidden group-hover:flex focus-within:flex items-center gap-1 px-2.5 pb-1.5 pt-0.5">
                <ActionButton
                  icon="refresh-cw"
                  title={
                    checking === c.id ? "Checking..." : "Test connection"
                  }
                  onClick={() => handleCheckStatus(c.id)}
                  disabled={checking === c.id}
                  size="sm"
                />
                <ActionButton
                  icon="pencil"
                  title="Edit"
                  onClick={() => handleEdit(c)}
                  size="sm"
                />
                {isActive && (
                  <ActionButton
                    icon="database"
                    title="Refresh schema cache"
                    onClick={() => handleRefreshSchema(c.id)}
                    disabled={refreshing === c.id}
                    size="sm"
                  />
                )}
                <ActionButton
                  icon="trash"
                  title="Delete connection"
                  onClick={(e) => handleDelete(e, c.id)}
                  variant="danger"
                  size="sm"
                />
              </div>
              {showLearnings === c.id && (
                <div className="px-2 pb-2">
                  <LearningsPanel
                    connectionId={c.id}
                    onClose={() => setShowLearnings(null)}
                    onCountChange={(count) =>
                      setLearningsCount((prev) => ({ ...prev, [c.id]: count }))
                    }
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
