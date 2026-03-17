"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { confirmAction } from "@/components/ui/ConfirmModal";
import { toast } from "@/stores/toast-store";
import { Spinner } from "@/components/ui/Spinner";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const copy = useCallback(() => {
    navigator.clipboard.writeText(text).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }).catch(() => {
      toast("Failed to copy to clipboard", "error");
    });
  }, [text]);

  return (
    <button
      onClick={copy}
      className="absolute top-1 right-1 px-1.5 py-0.5 rounded text-[9px] bg-zinc-700 text-zinc-400 hover:text-zinc-200 hover:bg-zinc-600 transition-colors"
      title="Copy to clipboard"
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

function CodeBlock({ command }: { command: string }) {
  return (
    <div className="relative mt-1">
      <pre className="bg-zinc-950 border border-zinc-700/50 rounded px-2.5 py-1.5 pr-14 font-mono text-[10px] text-emerald-400 overflow-x-auto">
        {command}
      </pre>
      <CopyButton text={command} />
    </div>
  );
}

function SshKeyHelp() {
  return (
    <div className="space-y-3 p-2.5 bg-zinc-900 border border-zinc-700/50 rounded-lg text-[11px] text-zinc-400 leading-relaxed">
      <div>
        <p className="text-zinc-300 font-medium">1. Check for existing keys</p>
        <CodeBlock command="ls -la ~/.ssh/" />
        <p className="mt-1">
          Look for <code className="text-zinc-300 bg-zinc-800 px-1 rounded">id_ed25519</code>,{" "}
          <code className="text-zinc-300 bg-zinc-800 px-1 rounded">id_rsa</code>, or{" "}
          <code className="text-zinc-300 bg-zinc-800 px-1 rounded">id_ecdsa</code>.
          If you see one — you already have a key.
        </p>
      </div>

      <div>
        <p className="text-zinc-300 font-medium">2. Create a new key (if needed)</p>
        <CodeBlock command='ssh-keygen -t ed25519 -C "your-email@example.com"' />
        <p className="mt-1">Press Enter to accept the default path. Optionally set a passphrase.</p>
      </div>

      <div>
        <p className="text-zinc-300 font-medium">3. Copy the private key</p>
        <CodeBlock command="cat ~/.ssh/id_ed25519" />
        <p className="mt-1">
          Copy <span className="text-zinc-300">everything</span> from{" "}
          <code className="text-zinc-300 bg-zinc-800 px-1 rounded">-----BEGIN OPENSSH PRIVATE KEY-----</code>{" "}
          to{" "}
          <code className="text-zinc-300 bg-zinc-800 px-1 rounded">-----END OPENSSH PRIVATE KEY-----</code>{" "}
          and paste below.
        </p>
      </div>

      <div className="pt-1 border-t border-zinc-800 text-[10px] space-y-0.5 text-zinc-500">
        <p>Use the <span className="text-zinc-400">private</span> key — not the <code className="bg-zinc-800 px-0.5 rounded">.pub</code> file.</p>
        <p>Your key is encrypted at rest and never exposed via the API.</p>
      </div>
    </div>
  );
}

export function SshKeyManager() {
  const { sshKeys, setSshKeys } = useAppStore();
  const [showCreate, setShowCreate] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [form, setForm] = useState({ name: "", private_key: "", passphrase: "" });
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [listLoading, setListLoading] = useState(true);

  useEffect(() => {
    api.sshKeys.list().then(setSshKeys).catch((err) => {
      toast(err instanceof Error ? err.message : "Failed to load SSH keys", "error");
    }).finally(() => setListLoading(false));
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
      toast("SSH key added", "success");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add key");
    } finally {
      setCreating(false);
    }
  };

  const handleDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    if (!(await confirmAction("Delete this SSH key?"))) return;
    try {
      await api.sshKeys.delete(id);
      useAppStore.setState((state) => ({
        sshKeys: state.sshKeys.filter((k) => k.id !== id),
      }));
      toast("SSH key deleted", "success");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to delete key", "error");
    }
  };

  const truncateFingerprint = (fp: string) =>
    fp.length > 16 ? `${fp.slice(0, 8)}...${fp.slice(-8)}` : fp;

  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <button
          onClick={() => {
            setShowCreate(!showCreate);
            setError(null);
            setShowHelp(false);
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

          <button
            type="button"
            onClick={() => setShowHelp(!showHelp)}
            className="flex items-center gap-1 text-[10px] text-zinc-500 hover:text-blue-400 transition-colors"
          >
            <span className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-full border border-current text-[8px] leading-none">?</span>
            {showHelp ? "Hide guide" : "Need help finding your SSH key?"}
          </button>

          {showHelp && <SshKeyHelp />}

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

      {listLoading && <Spinner />}
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
