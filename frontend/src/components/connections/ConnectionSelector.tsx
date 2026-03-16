"use client";

import { useState } from "react";
import { api, type Connection } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";

const DB_TYPES = ["postgres", "mysql", "mongodb", "clickhouse"];

const DEFAULT_PORTS: Record<string, string> = {
  postgres: "5432",
  mysql: "3306",
  mongodb: "27017",
  clickhouse: "9000",
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
};

type FormState = typeof EMPTY_FORM;

function connToForm(c: Connection): FormState {
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
    ssh_user: "",
    ssh_key_id: c.ssh_key_id || "",
    connection_string: "",
    is_read_only: c.is_read_only,
  };
}

const inputCls =
  "w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-1.5 text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-blue-500";
const halfInputCls =
  "bg-zinc-900 border border-zinc-700 rounded px-3 py-1.5 text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-blue-500";

export function ConnectionSelector() {
  const { activeProject, connections, activeConnection, setActiveConnection, sshKeys } =
    useAppStore();
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>({ ...EMPTY_FORM });
  const [useConnString, setUseConnString] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<
    Record<string, { success: boolean; error?: string }>
  >({});
  const [refreshing, setRefreshing] = useState<string | null>(null);

  const resetForm = () => {
    setForm({ ...EMPTY_FORM });
    setUseConnString(false);
  };

  const handleCreate = async () => {
    if (!activeProject || !form.name.trim()) return;
    const conn = await api.connections.create({
      project_id: activeProject.id,
      name: form.name,
      db_type: form.db_type,
      db_host: form.db_host,
      db_port: parseInt(form.db_port),
      db_name: form.db_name,
      db_user: form.db_user || null,
      db_password: form.db_password || null,
      ssh_host: form.ssh_host || null,
      ssh_port: parseInt(form.ssh_port) || 22,
      ssh_user: form.ssh_user || null,
      ssh_key_id: form.ssh_key_id || null,
      connection_string: useConnString ? form.connection_string || null : null,
      is_read_only: form.is_read_only,
    });
    useAppStore.setState((state) => ({
      connections: [conn, ...state.connections],
    }));
    setActiveConnection(conn);
    setShowCreate(false);
    resetForm();
  };

  const handleEdit = (c: Connection) => {
    setEditingId(c.id);
    setForm(connToForm(c));
    setShowCreate(false);
    setUseConnString(false);
  };

  const handleUpdate = async () => {
    if (!editingId) return;
    const updates: Record<string, unknown> = {};
    const fields = [
      "name", "db_type", "db_host", "db_name", "db_user", "ssh_host",
      "ssh_user", "ssh_key_id", "is_read_only",
    ] as const;
    for (const f of fields) {
      updates[f] = form[f] || null;
    }
    updates.db_port = parseInt(form.db_port);
    updates.ssh_port = parseInt(form.ssh_port) || 22;
    if (form.db_password) updates.db_password = form.db_password;
    if (useConnString && form.connection_string) {
      updates.connection_string = form.connection_string;
    }
    updates.name = form.name;
    updates.is_read_only = form.is_read_only;

    const updated = await api.connections.update(editingId, updates);
    useAppStore.setState((state) => ({
      connections: state.connections.map((c) => (c.id === updated.id ? updated : c)),
      ...(state.activeConnection?.id === updated.id ? { activeConnection: updated } : {}),
    }));
    setEditingId(null);
    resetForm();
  };

  const handleTest = async (id: string) => {
    setTesting(id);
    try {
      const result = await api.connections.test(id);
      setTestResult((prev) => ({ ...prev, [id]: result }));
    } finally {
      setTesting(null);
    }
  };

  const handleRefreshSchema = async (id: string) => {
    setRefreshing(id);
    try {
      await api.connections.refreshSchema(id);
    } catch (err) {
      console.error("Schema refresh failed", err);
    } finally {
      setRefreshing(null);
    }
  };

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (!confirm("Delete this connection?")) return;
    try {
      await api.connections.delete(id);
      useAppStore.setState((state) => ({
        connections: state.connections.filter((c) => c.id !== id),
        ...(state.activeConnection?.id === id ? { activeConnection: null } : {}),
      }));
    } catch (err) {
      console.error("Failed to delete connection", err);
    }
  };

  if (!activeProject) return null;

  const isFormOpen = showCreate || editingId !== null;

  const formUI = (
    <div className="space-y-2 p-2 bg-zinc-800/50 rounded-lg text-xs">
      <input
        value={form.name}
        onChange={(e) => setForm({ ...form, name: e.target.value })}
        placeholder="Connection name"
        className={inputCls}
      />
      <select
        value={form.db_type}
        onChange={(e) => {
          const newType = e.target.value;
          const knownDefaults = Object.values(DEFAULT_PORTS);
          setForm((prev) => ({
            ...prev,
            db_type: newType,
            ...(knownDefaults.includes(prev.db_port)
              ? { db_port: DEFAULT_PORTS[newType] || "5432" }
              : {}),
          }));
        }}
        className={inputCls}
      >
        {DB_TYPES.map((t) => (
          <option key={t} value={t}>
            {t}
          </option>
        ))}
      </select>

      {/* Connection string toggle */}
      <label className="flex items-center gap-2 text-zinc-400 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={useConnString}
          onChange={(e) => setUseConnString(e.target.checked)}
          className="accent-blue-500"
        />
        Use connection string
      </label>

      {useConnString ? (
        <input
          value={form.connection_string}
          onChange={(e) => setForm({ ...form, connection_string: e.target.value })}
          placeholder="postgresql://user:pass@host:5432/dbname"
          className={inputCls}
        />
      ) : (
        <>
          <div className="grid grid-cols-2 gap-2">
            <input
              value={form.db_host}
              onChange={(e) => setForm({ ...form, db_host: e.target.value })}
              placeholder="Host"
              className={halfInputCls}
            />
            <input
              value={form.db_port}
              onChange={(e) => setForm({ ...form, db_port: e.target.value })}
              placeholder="Port"
              className={halfInputCls}
            />
          </div>
          <input
            value={form.db_name}
            onChange={(e) => setForm({ ...form, db_name: e.target.value })}
            placeholder="Database name"
            className={inputCls}
          />
          <div className="grid grid-cols-2 gap-2">
            <input
              value={form.db_user}
              onChange={(e) => setForm({ ...form, db_user: e.target.value })}
              placeholder="Username"
              className={halfInputCls}
            />
            <input
              type="password"
              value={form.db_password}
              onChange={(e) => setForm({ ...form, db_password: e.target.value })}
              placeholder="Password"
              className={halfInputCls}
            />
          </div>
        </>
      )}

      <div className="grid grid-cols-2 gap-2">
        <input
          value={form.ssh_host}
          onChange={(e) => setForm({ ...form, ssh_host: e.target.value })}
          placeholder="SSH Host (optional)"
          className={halfInputCls}
        />
        <input
          value={form.ssh_port}
          onChange={(e) => setForm({ ...form, ssh_port: e.target.value })}
          placeholder="SSH Port"
          className={halfInputCls}
        />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <input
          value={form.ssh_user}
          onChange={(e) => setForm({ ...form, ssh_user: e.target.value })}
          placeholder="SSH User"
          className={halfInputCls}
        />
        <select
          value={form.ssh_key_id}
          onChange={(e) => setForm({ ...form, ssh_key_id: e.target.value })}
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

      {/* Read-only toggle */}
      <label className="flex items-center gap-2 text-zinc-400 cursor-pointer select-none">
        <input
          type="checkbox"
          checked={form.is_read_only}
          onChange={(e) => setForm({ ...form, is_read_only: e.target.checked })}
          className="accent-blue-500"
        />
        Read-only mode
      </label>

      <div className="flex gap-2">
        <button
          onClick={editingId ? handleUpdate : handleCreate}
          className="flex-1 px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-500"
        >
          {editingId ? "Save Changes" : "Create Connection"}
        </button>
        {editingId && (
          <button
            onClick={() => { setEditingId(null); resetForm(); }}
            className="px-3 py-1.5 text-zinc-400 hover:text-zinc-200"
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  );

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium text-zinc-500 uppercase tracking-wider">
          Connections
        </h3>
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
          className="text-xs text-blue-400 hover:text-blue-300"
        >
          {showCreate ? "Cancel" : "+ New"}
        </button>
      </div>

      {isFormOpen && formUI}

      <div className="space-y-1">
        {connections.map((c) => (
          <div key={c.id} className="flex items-center gap-1 group">
            <button
              onClick={() => setActiveConnection(c)}
              className={`flex-1 text-left px-3 py-2 rounded-md text-sm transition-colors truncate ${
                activeConnection?.id === c.id
                  ? "bg-zinc-800 text-zinc-100"
                  : "text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-300"
              }`}
            >
              <span className="flex items-center gap-1.5">
                <span className="text-[10px] text-zinc-500 uppercase">{c.db_type}</span>
                {c.is_read_only && (
                  <span className="text-[9px] px-1 py-0.5 rounded bg-zinc-700 text-zinc-400">
                    RO
                  </span>
                )}
              </span>
              {c.name}
            </button>
            <button
              onClick={() => handleEdit(c)}
              className="text-[10px] text-zinc-600 hover:text-blue-400 px-1 opacity-0 group-hover:opacity-100 transition-opacity"
              title="Edit"
            >
              ✎
            </button>
            <button
              onClick={() => handleTest(c.id)}
              disabled={testing === c.id}
              className={`text-[10px] px-2 py-1 rounded ${
                testResult[c.id]?.success
                  ? "text-green-400"
                  : testResult[c.id]
                    ? "text-red-400"
                    : "text-zinc-500 hover:text-zinc-300"
              }`}
            >
              {testing === c.id
                ? "..."
                : testResult[c.id]?.success
                  ? "OK"
                  : testResult[c.id]
                    ? "Fail"
                    : "Test"}
            </button>
            {activeConnection?.id === c.id && (
              <button
                onClick={() => handleRefreshSchema(c.id)}
                disabled={refreshing === c.id}
                className="text-[10px] px-1.5 py-1 rounded text-zinc-500 hover:text-blue-400 opacity-0 group-hover:opacity-100 transition-opacity"
                title="Refresh schema cache"
              >
                {refreshing === c.id ? "..." : "↻"}
              </button>
            )}
            <button
              onClick={(e) => handleDelete(e, c.id)}
              className="text-xs text-zinc-600 hover:text-red-400 px-1 opacity-0 group-hover:opacity-100 transition-opacity"
              title="Delete connection"
            >
              ×
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
