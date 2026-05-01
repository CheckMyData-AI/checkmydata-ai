"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type Connection } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { confirmAction } from "@/components/ui/ConfirmModal";
import { toast } from "@/stores/toast-store";
import { Icon } from "@/components/ui/Icon";
import { ActionButton } from "@/components/ui/ActionButton";
import { StatusDot } from "@/components/ui/StatusDot";
import { Tooltip } from "@/components/ui/Tooltip";
import { ConnectionHealth } from "@/components/connections/ConnectionHealth";
import { LearningsPanel } from "@/components/learnings/LearningsPanel";
import { POLL_INTERVAL_MS, MAX_POLL_MS } from "@/lib/polling";
import { usePermission } from "@/hooks/usePermission";
import { FormModal } from "@/components/ui/FormModal";

import {
  DB_TYPES,
  DEFAULT_PORTS,
  EMPTY_FORM,
  EXEC_TEMPLATE_PRESETS,
  type FormState,
  connToForm,
  formatAge,
  halfInputCls,
  inputCls,
  safePort,
} from "./connection-form-helpers";

interface ConnectionSelectorProps {
  createRequested?: boolean;
  onCreateHandled?: () => void;
}

export function ConnectionSelector({ createRequested, onCreateHandled }: ConnectionSelectorProps) {
  const activeProject = useAppStore((s) => s.activeProject);
  const connections = useAppStore((s) => s.connections);
  const activeConnection = useAppStore((s) => s.activeConnection);
  const setActiveConnection = useAppStore((s) => s.setActiveConnection);
  const sshKeys = useAppStore((s) => s.sshKeys);
  const { canDelete, canIndex, canManageProject } = usePermission();
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>({ ...EMPTY_FORM });
  const [useConnString, setUseConnString] = useState(false);
  const [checking, setChecking] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
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
  const [learningsCategories, setLearningsCategories] = useState<Record<string, Record<string, number>>>({});
  const [showLearnings, setShowLearnings] = useState<string | null>(null);
  const [healthStatuses, setHealthStatuses] = useState<Record<string, string>>({});
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
  const indexPollRef = useRef<Map<string, ReturnType<typeof setInterval>>>(new Map());
  const syncPollRef = useRef<Map<string, ReturnType<typeof setInterval>>>(new Map());
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    const indexPolls = indexPollRef.current;
    const syncPolls = syncPollRef.current;
    return () => {
      mountedRef.current = false;
      for (const t of indexPolls.values()) clearInterval(t);
      indexPolls.clear();
      for (const t of syncPolls.values()) clearInterval(t);
      syncPolls.clear();
    };
  }, []);

  useEffect(() => {
    setStatus({});
    setEditingId(null);
    setShowCreate(false);
    setIndexStatus({});
    setSyncStatus({});
    resetForm();
  }, [activeProject?.id]);

  const startIndexPoll = useCallback((id: string) => {
    const prevTimer = indexPollRef.current.get(id);
    if (prevTimer) clearInterval(prevTimer);
    const pollStart = Date.now();
    const timer = setInterval(async () => {
      if (Date.now() - pollStart > MAX_POLL_MS) {
        clearInterval(timer);
        indexPollRef.current.delete(id);
        setIndexing((prev) => (prev === id ? null : prev));
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
          clearInterval(timer);
          indexPollRef.current.delete(id);
          setIndexing((prev) => (prev === id ? null : prev));
          if (s.is_indexed) {
            toast(
              `DB indexed: ${s.active_tables}/${s.total_tables} active tables`,
              "success",
            );
          } else {
            toast("DB indexing failed — try again or check connection", "error");
          }
          const pid = useAppStore.getState().activeProject?.id;
          if (pid) useAppStore.getState().clearReadinessCache(pid);
        }
      } catch {
        clearInterval(timer);
        indexPollRef.current.delete(id);
        setIndexing((prev) => (prev === id ? null : prev));
        toast("Lost connection while checking index status", "error");
      }
    }, POLL_INTERVAL_MS);
    indexPollRef.current.set(id, timer);
  }, []);

  const startSyncPoll = useCallback((id: string) => {
    const prevTimer = syncPollRef.current.get(id);
    if (prevTimer) clearInterval(prevTimer);
    const pollStart = Date.now();
    const timer = setInterval(async () => {
      if (Date.now() - pollStart > MAX_POLL_MS) {
        clearInterval(timer);
        syncPollRef.current.delete(id);
        setSyncing((prev) => (prev === id ? null : prev));
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
          clearInterval(timer);
          syncPollRef.current.delete(id);
          setSyncing((prev) => (prev === id ? null : prev));
          if (s.is_synced) {
            toast(
              `Code-DB synced: ${s.synced_tables ?? 0}/${s.total_tables ?? 0} tables matched`,
              "success",
            );
          } else {
            toast("Code-DB sync failed — ensure DB is indexed first", "error");
          }
          const pid = useAppStore.getState().activeProject?.id;
          if (pid) useAppStore.getState().clearReadinessCache(pid);
        }
      } catch {
        clearInterval(timer);
        syncPollRef.current.delete(id);
        setSyncing((prev) => (prev === id ? null : prev));
        toast("Lost connection while checking sync status", "error");
      }
    }, POLL_INTERVAL_MS);
    syncPollRef.current.set(id, timer);
  }, []);

  useEffect(() => {
    let cancelled = false;
    connections.forEach((c) => {
      api.connections
        .indexDbStatus(c.id)
        .then((s) => {
          if (!cancelled && mountedRef.current) {
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
            if (s.is_indexing && !indexPollRef.current.has(c.id)) {
              startIndexPoll(c.id);
            }
          }
        })
        .catch(() => {});
      api.connections
        .syncStatus(c.id)
        .then((s) => {
          if (!cancelled && mountedRef.current) {
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
            if (s.is_syncing && !syncPollRef.current.has(c.id)) {
              startSyncPoll(c.id);
            }
          }
        })
        .catch(() => {});
      api.connections
        .learningsStatus(c.id)
        .then((s) => {
          if (!cancelled && mountedRef.current) {
            setLearningsCount((prev) => ({ ...prev, [c.id]: s.total_active }));
            if (s.categories) {
              setLearningsCategories((prev) => ({ ...prev, [c.id]: s.categories }));
            }
          }
        })
        .catch(() => {});
    });
    return () => { cancelled = true; };
  }, [connections, startIndexPoll, startSyncPoll]);

  useEffect(() => {
    if (createRequested) {
      setEditingId(null);
      setForm({ ...EMPTY_FORM });
      setUseConnString(false);
      setShowCreate(true);
      onCreateHandled?.();
    }
  }, [createRequested, onCreateHandled]);

  const resetForm = () => {
    setForm({ ...EMPTY_FORM });
    setUseConnString(false);
  };

  const isMCP = form.db_type === "mcp";
  const hasSSH = !isMCP && form.ssh_host.trim().length > 0;

  const handleCreate = async () => {
    if (!activeProject || !form.name.trim()) return;
    if (!isMCP && form.ssh_host.trim() && (!form.ssh_user.trim() || !form.ssh_key_id)) {
      toast("SSH host is set — please provide an SSH user and key.", "error");
      return;
    }
    if (isMCP) {
      if (form.mcp_transport_type === "stdio" && !form.mcp_server_command.trim()) {
        toast("MCP stdio transport requires a server command.", "error");
        return;
      }
      if (form.mcp_transport_type === "sse" && !form.mcp_server_url.trim()) {
        toast("MCP SSE transport requires a server URL.", "error");
        return;
      }
    }
    const preCommandsList = form.ssh_pre_commands.trim()
      ? form.ssh_pre_commands.split("\n").filter((l) => l.trim())
      : null;
    let mcpEnv: Record<string, string> | null = null;
    if (isMCP && form.mcp_env.trim()) {
      try {
        mcpEnv = JSON.parse(form.mcp_env);
      } catch {
        toast("MCP env must be valid JSON (e.g. {\"KEY\": \"value\"})", "error");
        return;
      }
    }
    const mcpArgs = isMCP && form.mcp_server_args.trim()
      ? form.mcp_server_args.split(/\s+/).filter(Boolean)
      : null;
    setSaving(true);
    try {
      const conn = await api.connections.create({
        project_id: activeProject.id,
        name: form.name,
        db_type: form.db_type,
        ...(isMCP ? { source_type: "mcp" } : {}),
        db_host: isMCP ? "mcp" : form.db_host,
        db_port: isMCP ? 0 : safePort(form.db_port, 5432),
        db_name: isMCP ? form.name : form.db_name,
        db_user: isMCP ? null : form.db_user || null,
        db_password: isMCP ? null : form.db_password || null,
        ssh_host: isMCP ? null : form.ssh_host || null,
        ssh_port: isMCP ? 22 : safePort(form.ssh_port, 22),
        ssh_user: isMCP ? null : form.ssh_user || null,
        ssh_key_id: isMCP ? null : form.ssh_key_id || null,
        connection_string: !isMCP && useConnString ? form.connection_string || null : null,
        is_read_only: form.is_read_only,
        ssh_exec_mode: isMCP ? false : form.ssh_exec_mode,
        ssh_command_template: isMCP ? null : form.ssh_command_template || null,
        ssh_pre_commands: isMCP ? null : preCommandsList,
        ...(isMCP ? {
          mcp_transport_type: form.mcp_transport_type,
          mcp_server_command: form.mcp_server_command || null,
          mcp_server_args: mcpArgs,
          mcp_server_url: form.mcp_server_url || null,
          mcp_env: mcpEnv,
        } : {}),
      } as Parameters<typeof api.connections.create>[0]);
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
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = (c: Connection) => {
    setEditingId(c.id);
    setForm(connToForm(c));
    setShowCreate(false);
    setUseConnString(false);
  };

  const handleUpdate = async () => {
    if (!editingId || saving) return;
    if (!form.name.trim()) {
      toast("Connection name is required.", "error");
      return;
    }
    if (!isMCP && form.ssh_host.trim() && (!form.ssh_user.trim() || !form.ssh_key_id)) {
      toast("SSH host is set — please provide an SSH user and key.", "error");
      return;
    }
    if (isMCP) {
      if (form.mcp_transport_type === "stdio" && !form.mcp_server_command.trim()) {
        toast("MCP stdio transport requires a server command.", "error");
        return;
      }
      if (form.mcp_transport_type === "sse" && !form.mcp_server_url.trim()) {
        toast("MCP SSE transport requires a server URL.", "error");
        return;
      }
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

    if (isMCP) {
      updates.source_type = "mcp";
      updates.mcp_transport_type = form.mcp_transport_type;
      updates.mcp_server_command = form.mcp_server_command || null;
      updates.mcp_server_url = form.mcp_server_url || null;
      const mcpArgs = form.mcp_server_args.trim()
        ? form.mcp_server_args.split(/\s+/).filter(Boolean)
        : null;
      updates.mcp_server_args = mcpArgs;
      if (form.mcp_env.trim()) {
        try {
          updates.mcp_env = JSON.parse(form.mcp_env);
        } catch {
          toast("MCP env must be valid JSON (e.g. {\"KEY\": \"value\"})", "error");
          return;
        }
      } else {
        updates.mcp_env = null;
      }
    }

    setSaving(true);
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
    } finally {
      setSaving(false);
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
    if (indexing === id) return;
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
      startIndexPoll(id);
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "DB indexing failed",
        "error",
      );
      setIndexing(null);
    }
  };

  const handleSync = async (id: string) => {
    if (syncing === id) return;
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
      startSyncPoll(id);
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
    const conn = connections.find((c) => c.id === id);
    const name = conn?.db_name || conn?.id || "this connection";
    if (
      !(await confirmAction(`Delete connection "${name}"?`, {
        severity: "critical",
        detail:
          "This will permanently remove all DB indexes, sync data, learnings, benchmarks, and session notes associated with this connection.",
        confirmText: "DELETE",
      }))
    ) return;
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

  const cancelForm = () => {
    setEditingId(null);
    setShowCreate(false);
    resetForm();
  };

  const formUI = (
    <div className="space-y-2.5 text-xs">
      <input
        value={form.name}
        onChange={(e) => setForm({ ...form, name: e.target.value })}
        placeholder="Connection name"
        aria-label="Connection name"
        className={inputCls}
        maxLength={255}
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

      {isMCP ? (
        <div className="space-y-2.5">
          <select
            value={form.mcp_transport_type}
            aria-label="MCP transport type"
            onChange={(e) =>
              setForm({ ...form, mcp_transport_type: e.target.value as "stdio" | "sse" })
            }
            className={inputCls}
          >
            <option value="stdio">stdio (local command)</option>
            <option value="sse">SSE (remote URL)</option>
          </select>

          {form.mcp_transport_type === "stdio" ? (
            <>
              <input
                value={form.mcp_server_command}
                onChange={(e) =>
                  setForm({ ...form, mcp_server_command: e.target.value })
                }
                placeholder="Command (e.g. npx -y @anthropic/mcp-server)"
                aria-label="MCP server command"
                className={inputCls}
                maxLength={500}
              />
              <input
                value={form.mcp_server_args}
                onChange={(e) =>
                  setForm({ ...form, mcp_server_args: e.target.value })
                }
                placeholder="Arguments (space-separated)"
                aria-label="MCP server arguments"
                className={inputCls}
                maxLength={1000}
              />
            </>
          ) : (
            <input
              value={form.mcp_server_url}
              onChange={(e) =>
                setForm({ ...form, mcp_server_url: e.target.value })
              }
              placeholder="Server URL (e.g. http://localhost:8100/sse)"
              aria-label="MCP server URL"
              className={inputCls}
              maxLength={500}
            />
          )}

          <textarea
            value={form.mcp_env}
            onChange={(e) => setForm({ ...form, mcp_env: e.target.value })}
            placeholder={'Environment variables (JSON, optional):\n{"API_KEY": "..."}'}
            rows={2}
            className={inputCls + " font-mono text-[10px] resize-y"}
          />
          <p className="text-[10px] text-text-muted px-1">
            Connect to an external MCP server to query data from services like
            Google Analytics, Stripe, Jira, etc.
          </p>
        </div>
      ) : (
        <>
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
              maxLength={500}
            />
          ) : (
            <>
              <div className="grid grid-cols-2 gap-2">
                <input
                  value={form.db_host}
                  onChange={(e) =>
                    setForm({ ...form, db_host: e.target.value })
                  }
                  placeholder="Host"
                  aria-label="Database host"
                  className={halfInputCls}
                  maxLength={255}
                />
                <input
                  value={form.db_port}
                  onChange={(e) =>
                    setForm({ ...form, db_port: e.target.value })
                  }
                  placeholder="Port"
                  aria-label="Database port"
                  className={halfInputCls}
                  maxLength={5}
                />
              </div>
              <input
                value={form.db_name}
                onChange={(e) =>
                  setForm({ ...form, db_name: e.target.value })
                }
                placeholder="Database name"
                aria-label="Database name"
                className={inputCls}
                maxLength={128}
              />
              <div className="grid grid-cols-2 gap-2">
                <input
                  value={form.db_user}
                  onChange={(e) =>
                    setForm({ ...form, db_user: e.target.value })
                  }
                  placeholder="Username"
                  aria-label="Database username"
                  className={halfInputCls}
                  maxLength={128}
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
                  maxLength={255}
                />
              </div>
            </>
          )}
        </>
      )}

      {!isMCP && (useConnString ? (
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
              maxLength={255}
            />
            <input
              value={form.ssh_port}
              onChange={(e) => setForm({ ...form, ssh_port: e.target.value })}
              placeholder="SSH Port"
              aria-label="SSH port"
              className={halfInputCls}
              maxLength={5}
            />
          </div>
          <div className="grid grid-cols-2 gap-2">
            <input
              value={form.ssh_user}
              onChange={(e) => setForm({ ...form, ssh_user: e.target.value })}
              placeholder="SSH User"
              aria-label="SSH user"
              className={halfInputCls}
              maxLength={128}
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
                  className="accent-accent"
                  disabled={form.db_type === "mongodb"}
                />
                <span className="flex items-center gap-1.5">
                  <Icon name="terminal" size={12} />
                  SSH Exec Mode
                  {form.db_type === "mongodb" ? (
                    <span className="text-[10px] text-text-muted">
                      (not supported for MongoDB)
                    </span>
                  ) : (
                    <span className="text-[10px] text-text-muted">
                      (CLI on server)
                    </span>
                  )}
                </span>
              </label>
              {!form.ssh_exec_mode && (
                <p className="text-[10px] text-text-muted px-1">
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
                  <p className="text-[10px] text-text-muted px-1">
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
      ))}

      {!isMCP && (
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
      )}

      <div className="flex gap-2 pt-1">
        <button
          onClick={editingId ? handleUpdate : handleCreate}
          disabled={saving}
          className="flex-1 px-3 py-2 bg-accent text-white font-medium rounded-lg hover:bg-accent-hover transition-colors disabled:opacity-60 disabled:cursor-not-allowed flex items-center justify-center gap-2"
        >
          {saving && <span className="w-3.5 h-3.5 border-2 border-text-primary/30 border-t-text-primary rounded-full animate-spin" />}
          {saving ? "Saving…" : editingId ? "Save Changes" : "Create Connection"}
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
    <div className="px-1">
      <FormModal
        open={isFormOpen}
        onClose={cancelForm}
        title={editingId ? "Edit Connection" : "New Connection"}
        maxWidth="max-w-lg"
      >
        {formUI}
      </FormModal>

      {!isFormOpen && connections.length === 0 && (
        <div className="px-2 py-3 text-center">
          <p className="text-[10px] text-text-muted">No connections yet</p>
        </div>
      )}

      <div>
        {connections.map((c) => {
          const isActive = activeConnection?.id === c.id;
          const idx = indexStatus[c.id];
          const sync = syncStatus[c.id];

          return (
            <div key={c.id}>
              <div
                className={`group relative flex items-start gap-2 pl-3 pr-1.5 py-1.5 rounded-md transition-colors cursor-pointer ${
                  isActive ? "bg-surface-1" : "hover:bg-surface-1"
                }`}
                role="button"
                tabIndex={0}
                onClick={() => setActiveConnection(c)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    setActiveConnection(c);
                  }
                }}
              >
                {isActive && (
                  <div className="absolute left-0.5 top-1/4 bottom-1/4 w-0.5 bg-accent rounded-full" />
                )}
                <span className="flex items-center gap-0.5 mt-1">
                  <StatusDot
                    status={getConnStatus(c.id)}
                    title={getConnStatusTitle(c.id)}
                    size="md"
                  />
                  <ConnectionHealth
                    connectionId={c.id}
                    onStatusChange={(s) =>
                      setHealthStatuses((prev) => ({ ...prev, [c.id]: s }))
                    }
                  />
                </span>
                <div className="flex-1 min-w-0 py-0.5">
                  <span
                    className={`text-xs font-medium truncate block ${
                      isActive ? "text-text-primary" : "text-text-secondary"
                    }`}
                  >
                    {c.name}
                  </span>
                  <div className="flex items-center gap-1 mt-0.5 flex-wrap">
                    <span className="text-[10px] text-text-muted font-mono uppercase">
                      {c.source_type === "mcp" ? "MCP" : c.db_type}
                    </span>
                    {c.is_read_only && (
                      <span className="text-[10px] px-1 py-px rounded-full bg-surface-3/50 text-text-tertiary leading-none">
                        RO
                      </span>
                    )}
                    {c.ssh_exec_mode && (
                      <span className="text-[10px] px-1 py-px rounded-full bg-accent-muted text-accent leading-none">
                        EXEC
                      </span>
                    )}
                    {idx?.is_indexing ? (
                      <span className="text-[10px] px-1 py-px rounded-full bg-warning-muted text-warning animate-pulse-dot leading-none">
                        IDX...
                      </span>
                    ) : idx?.is_indexed ? (
                      canIndex ? (
                        <Tooltip label={`Indexed: ${idx.active_tables ?? "?"}/${idx.total_tables ?? "?"} active${idx.indexed_at ? ` (${formatAge(idx.indexed_at)})` : ""}. Click to re-index`} position="bottom">
                          <button
                            type="button"
                            aria-label="Re-index database"
                            className="text-[10px] px-1 py-px rounded-full bg-success-muted text-success cursor-pointer hover:bg-success/20 outline-none focus-visible:ring-2 focus-visible:ring-accent leading-none"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleIndexDb(c.id);
                            }}
                          >
                            IDX
                          </button>
                        </Tooltip>
                      ) : (
                        <Tooltip label={`Indexed: ${idx.active_tables ?? "?"}/${idx.total_tables ?? "?"} active${idx.indexed_at ? ` (${formatAge(idx.indexed_at)})` : ""}`} position="bottom">
                          <span className="text-[10px] px-1 py-px rounded-full bg-success-muted text-success leading-none">
                            IDX
                          </span>
                        </Tooltip>
                      )
                    ) : isActive && canIndex ? (
                      <Tooltip label="Index database schema" position="bottom">
                        <button
                          type="button"
                          aria-label="Index database schema"
                          className="text-[10px] px-1 py-px rounded-full bg-surface-3/50 text-text-muted cursor-pointer hover:text-text-secondary hover:bg-surface-3 outline-none focus-visible:ring-2 focus-visible:ring-accent leading-none"
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
                      <span className="text-[10px] px-1 py-px rounded-full bg-warning-muted text-warning animate-pulse-dot leading-none">
                        SYNC...
                      </span>
                    ) : sync?.is_synced ? (
                      canIndex ? (
                        <Tooltip label={`Synced: ${sync.synced_tables ?? "?"}/${sync.total_tables ?? "?"} tables${sync.synced_at ? ` (${formatAge(sync.synced_at)})` : ""}. Click to re-sync`} position="bottom">
                          <button
                            type="button"
                            aria-label="Re-sync database"
                            className="text-[10px] px-1 py-px rounded-full bg-success-muted text-success cursor-pointer hover:bg-success/20 outline-none focus-visible:ring-2 focus-visible:ring-accent leading-none"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleSync(c.id);
                            }}
                          >
                            SYNC
                          </button>
                        </Tooltip>
                      ) : (
                        <Tooltip label={`Synced: ${sync.synced_tables ?? "?"}/${sync.total_tables ?? "?"} tables${sync.synced_at ? ` (${formatAge(sync.synced_at)})` : ""}`} position="bottom">
                          <span className="text-[10px] px-1 py-px rounded-full bg-success-muted text-success leading-none">
                            SYNC
                          </span>
                        </Tooltip>
                      )
                    ) : sync?.sync_status === "stale" ? (
                      canIndex ? (
                        <Tooltip label="Sync data is stale -- click to re-sync" position="bottom">
                          <button
                            type="button"
                            aria-label="Re-sync stale data"
                            className="text-[10px] px-1 py-px rounded-full bg-warning-muted text-warning cursor-pointer hover:bg-warning/20 outline-none focus-visible:ring-2 focus-visible:ring-accent leading-none"
                            onClick={(e) => {
                              e.stopPropagation();
                              handleSync(c.id);
                            }}
                          >
                            SYNC
                          </button>
                        </Tooltip>
                      ) : (
                        <Tooltip label="Sync data is stale" position="bottom">
                          <span className="text-[10px] px-1 py-px rounded-full bg-warning-muted text-warning leading-none">
                            SYNC
                          </span>
                        </Tooltip>
                      )
                    ) : isActive && idx?.is_indexed && canIndex ? (
                      <Tooltip label="Run Code-DB Sync" position="bottom">
                        <button
                          type="button"
                          aria-label="Run Code-DB Sync"
                          className="text-[10px] px-1 py-px rounded-full bg-surface-3/50 text-text-muted cursor-pointer hover:text-text-secondary hover:bg-surface-3 outline-none focus-visible:ring-2 focus-visible:ring-accent leading-none"
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
                      <Tooltip label={(() => {
                        const catLabels: Record<string, string> = {
                          table_preference: "table prefs",
                          column_usage: "column usage",
                          data_format: "data formats",
                          query_pattern: "query patterns",
                          schema_gotcha: "schema gotchas",
                          performance_hint: "perf hints",
                        };
                        const cats = learningsCategories[c.id];
                        if (!cats || Object.keys(cats).length === 0) {
                          return `${learningsCount[c.id]} agent learnings. Click to manage`;
                        }
                        const breakdown = Object.entries(cats)
                          .map(([k, v]) => `${v} ${catLabels[k] || k}`)
                          .join(", ");
                        return `${learningsCount[c.id]} learnings: ${breakdown}`;
                      })()} position="bottom">
                        <button
                          type="button"
                          aria-label="Manage agent learnings"
                          className="text-[10px] px-1 py-px rounded-full bg-accent-muted text-accent cursor-pointer hover:bg-accent-muted outline-none focus-visible:ring-2 focus-visible:ring-accent leading-none"
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
                </div>
                <div className="shrink-0 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity duration-150">
                  <ActionButton
                    icon="refresh-cw"
                    title={checking === c.id ? "Checking..." : "Test connection"}
                    onClick={(e) => { e.stopPropagation(); handleCheckStatus(c.id); }}
                    disabled={checking === c.id}
                    size="xs"
                  />
                  {canManageProject && (
                    <ActionButton
                      icon="pencil"
                      title="Edit"
                      onClick={(e) => { e.stopPropagation(); handleEdit(c); }}
                      size="xs"
                    />
                  )}
                  {isActive && c.source_type !== "mcp" && canIndex && (
                    <ActionButton
                      icon="database"
                      title="Refresh schema cache"
                      onClick={(e) => { e.stopPropagation(); handleRefreshSchema(c.id); }}
                      disabled={refreshing === c.id}
                      size="xs"
                    />
                  )}
                  {canDelete && (
                    <ActionButton
                      icon="trash"
                      title="Delete connection"
                      onClick={(e) => handleDelete(e, c.id)}
                      variant="danger"
                      size="xs"
                    />
                  )}
                </div>
              </div>
              {healthStatuses[c.id] === "down" && (
                <div className="mx-3 mb-1 px-2 py-1 rounded bg-error-muted text-error text-[10px] flex items-center gap-1">
                  <span className="w-1.5 h-1.5 rounded-full bg-error shrink-0" />
                  Connection is unreachable
                </div>
              )}
              {showLearnings === c.id && (
                <LearningsPanel
                  connectionId={c.id}
                  onClose={() => setShowLearnings(null)}
                  onCountChange={(count) =>
                    setLearningsCount((prev) => ({ ...prev, [c.id]: count }))
                  }
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
