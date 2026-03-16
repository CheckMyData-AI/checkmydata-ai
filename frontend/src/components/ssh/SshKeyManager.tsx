"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";

export function SshKeyManager() {
  const { sshKeys, setSshKeys } = useAppStore();
  const [showCreate, setShowCreate] = useState(false);
  const [form, setForm] = useState({ name: "", private_key: "", passphrase: "" });
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    api.sshKeys.list().then(setSshKeys).catch(console.error);
  }, [setSshKeys]);

  const handleCreate = async () => {
    if (!form.name.trim() || !form.private_key.trim()) return;
    setError(null);
    setCreating(true);
    try {
      const key = await api.sshKeys.create({
        name: form.name.trim(),
        private_key: form.private_key,
        passphrase: form.passphrase || undefined,
      });
      useAppStore.setState((state) => ({ sshKeys: [key, ...state.sshKeys] }));
      setForm({ name: "", private_key: "", passphrase: "" });
      setShowCreate(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add key");
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (!confirm("Delete this SSH key?")) return;
    try {
      await api.sshKeys.delete(id);
      useAppStore.setState((state) => ({
        sshKeys: state.sshKeys.filter((k) => k.id !== id),
      }));
    } catch (err) {
      alert(err instanceof Error ? err.message : "Failed to delete key");
    }
  };

  const truncateFingerprint = (fp: string) =>
    fp.length > 16 ? `${fp.slice(0, 8)}...${fp.slice(-8)}` : fp;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-medium text-zinc-500 uppercase tracking-wider">
          SSH Keys
        </h3>
        <button
          onClick={() => {
            setShowCreate(!showCreate);
            setError(null);
          }}
          className="text-xs text-blue-400 hover:text-blue-300"
        >
          {showCreate ? "Cancel" : "+ Add"}
        </button>
      </div>

      {showCreate && (
        <div className="space-y-2 p-2 bg-zinc-800/50 rounded-lg text-xs">
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Key name (e.g. prod-server)"
            className="w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-1.5 text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          <textarea
            value={form.private_key}
            onChange={(e) => setForm({ ...form, private_key: e.target.value })}
            placeholder="-----BEGIN OPENSSH PRIVATE KEY-----&#10;...paste your private key...&#10;-----END OPENSSH PRIVATE KEY-----"
            rows={5}
            className="w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-1.5 text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-blue-500 font-mono text-[10px] leading-relaxed resize-y"
          />
          <input
            type="password"
            value={form.passphrase}
            onChange={(e) => setForm({ ...form, passphrase: e.target.value })}
            placeholder="Passphrase (optional)"
            className="w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-1.5 text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
          />
          {error && <p className="text-red-400 text-[10px]">{error}</p>}
          <button
            onClick={handleCreate}
            disabled={creating || !form.name.trim() || !form.private_key.trim()}
            className="w-full px-3 py-1.5 bg-blue-600 text-white rounded hover:bg-blue-500 disabled:opacity-50"
          >
            {creating ? "Adding..." : "Add Key"}
          </button>
        </div>
      )}

      <div className="space-y-1">
        {sshKeys.map((k) => (
          <div key={k.id} className="flex items-center gap-1 group">
            <div className="flex-1 px-3 py-2 rounded-md text-xs text-zinc-300">
              <span className="text-zinc-100">{k.name}</span>
              <div className="flex items-center gap-2 mt-0.5">
                <span className="text-[10px] text-blue-400/70 uppercase font-medium">
                  {k.key_type}
                </span>
                <span
                  className="text-[10px] text-zinc-500 font-mono"
                  title={k.fingerprint}
                >
                  {truncateFingerprint(k.fingerprint)}
                </span>
              </div>
            </div>
            <button
              onClick={(e) => handleDelete(e, k.id)}
              className="text-xs text-zinc-600 hover:text-red-400 px-1 opacity-0 group-hover:opacity-100 transition-opacity"
              title="Delete key"
            >
              ×
            </button>
          </div>
        ))}
        {sshKeys.length === 0 && !showCreate && (
          <p className="text-[10px] text-zinc-600 px-3">No SSH keys added yet</p>
        )}
      </div>
    </div>
  );
}
