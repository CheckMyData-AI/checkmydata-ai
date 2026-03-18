"use client";

import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { confirmAction } from "@/components/ui/ConfirmModal";
import { toast } from "@/stores/toast-store";
import { Spinner } from "@/components/ui/Spinner";
import { Icon } from "@/components/ui/Icon";
import { ActionButton } from "@/components/ui/ActionButton";

const inputCls =
  "w-full bg-surface-1 border border-border-subtle rounded-lg px-3 py-2 text-xs text-text-primary placeholder-text-muted focus:outline-none focus:ring-1 focus:ring-accent focus:border-accent transition-colors";

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);

  const copy = useCallback(() => {
    navigator.clipboard
      .writeText(text)
      .then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      })
      .catch(() => {
        toast("Failed to copy to clipboard", "error");
      });
  }, [text]);

  return (
    <button
      onClick={copy}
      className="absolute top-1 right-1 px-1.5 py-0.5 rounded text-[9px] bg-surface-2 text-text-tertiary hover:text-text-primary hover:bg-surface-3 transition-colors"
      title="Copy to clipboard"
    >
      {copied ? (
        <span className="flex items-center gap-0.5">
          <Icon name="check" size={8} /> Copied
        </span>
      ) : (
        <span className="flex items-center gap-0.5">
          <Icon name="copy" size={8} /> Copy
        </span>
      )}
    </button>
  );
}

function CodeBlock({ command }: { command: string }) {
  return (
    <div className="relative mt-1">
      <pre className="bg-surface-0 border border-border-subtle rounded-lg px-2.5 py-1.5 pr-14 font-mono text-[10px] text-success overflow-x-auto">
        {command}
      </pre>
      <CopyButton text={command} />
    </div>
  );
}

function SshKeyHelp() {
  return (
    <div className="space-y-3 p-2.5 bg-surface-1 border border-border-subtle rounded-lg text-[11px] text-text-tertiary leading-relaxed">
      <div>
        <p className="text-text-secondary font-medium">
          1. Check for existing keys
        </p>
        <CodeBlock command="ls -la ~/.ssh/" />
        <p className="mt-1">
          Look for{" "}
          <code className="text-text-secondary bg-surface-2 px-1 rounded">
            id_ed25519
          </code>
          ,{" "}
          <code className="text-text-secondary bg-surface-2 px-1 rounded">
            id_rsa
          </code>
          , or{" "}
          <code className="text-text-secondary bg-surface-2 px-1 rounded">
            id_ecdsa
          </code>
          . If you see one — you already have a key.
        </p>
      </div>

      <div>
        <p className="text-text-secondary font-medium">
          2. Create a new key (if needed)
        </p>
        <CodeBlock command='ssh-keygen -t ed25519 -C "your-email@example.com"' />
        <p className="mt-1">
          Press Enter to accept the default path. Optionally set a passphrase.
        </p>
      </div>

      <div>
        <p className="text-text-secondary font-medium">
          3. Copy the private key
        </p>
        <CodeBlock command="cat ~/.ssh/id_ed25519" />
        <p className="mt-1">
          Copy <span className="text-text-secondary">everything</span> from{" "}
          <code className="text-text-secondary bg-surface-2 px-1 rounded">
            -----BEGIN OPENSSH PRIVATE KEY-----
          </code>{" "}
          to{" "}
          <code className="text-text-secondary bg-surface-2 px-1 rounded">
            -----END OPENSSH PRIVATE KEY-----
          </code>{" "}
          and paste below.
        </p>
      </div>

      <div className="pt-1 border-t border-border-subtle text-[10px] space-y-0.5 text-text-muted">
        <p>
          Use the <span className="text-text-tertiary">private</span> key — not
          the{" "}
          <code className="bg-surface-2 px-0.5 rounded">.pub</code> file.
        </p>
        <p>Your key is encrypted at rest and never exposed via the API.</p>
      </div>
    </div>
  );
}

export function SshKeyManager() {
  const { sshKeys, setSshKeys } = useAppStore();
  const [showCreate, setShowCreate] = useState(false);
  const [showHelp, setShowHelp] = useState(false);
  const [form, setForm] = useState({
    name: "",
    private_key: "",
    passphrase: "",
  });
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [listLoading, setListLoading] = useState(true);

  useEffect(() => {
    api.sshKeys
      .list()
      .then(setSshKeys)
      .catch((err) => {
        toast(
          err instanceof Error ? err.message : "Failed to load SSH keys",
          "error",
        );
      })
      .finally(() => setListLoading(false));
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
      useAppStore.setState((state) => ({
        sshKeys: [key, ...state.sshKeys],
      }));
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
      toast(
        err instanceof Error ? err.message : "Failed to delete key",
        "error",
      );
    }
  };

  const truncateFingerprint = (fp: string) =>
    fp.length > 16 ? `${fp.slice(0, 8)}...${fp.slice(-8)}` : fp;

  return (
    <div className="space-y-1.5 px-1">
      <div className="flex justify-end px-1">
        <button
          onClick={() => {
            setShowCreate(!showCreate);
            setError(null);
            setShowHelp(false);
          }}
          className="flex items-center gap-1 text-[11px] text-accent hover:text-accent-hover transition-colors"
        >
          {showCreate ? (
            "Cancel"
          ) : (
            <>
              <Icon name="plus" size={12} />
              Add
            </>
          )}
        </button>
      </div>

      {showCreate && (
        <div className="space-y-2.5 p-3 bg-surface-1 rounded-lg border border-border-subtle text-xs">
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Key name (e.g. prod-server)"
            aria-label="Key name"
            className={inputCls}
          />

          <button
            type="button"
            onClick={() => setShowHelp(!showHelp)}
            className="flex items-center gap-1.5 text-[10px] text-text-muted hover:text-accent transition-colors"
          >
            <Icon name="help-circle" size={12} />
            {showHelp ? "Hide guide" : "Need help finding your SSH key?"}
          </button>

          {showHelp && <SshKeyHelp />}

          <textarea
            value={form.private_key}
            onChange={(e) =>
              setForm({ ...form, private_key: e.target.value })
            }
            placeholder="-----BEGIN OPENSSH PRIVATE KEY-----&#10;...paste your private key...&#10;-----END OPENSSH PRIVATE KEY-----"
            aria-label="Private key"
            rows={5}
            className={
              inputCls +
              " font-mono text-[10px] leading-relaxed resize-y"
            }
          />
          <input
            type="password"
            value={form.passphrase}
            onChange={(e) => setForm({ ...form, passphrase: e.target.value })}
            placeholder="Passphrase (optional)"
            aria-label="Passphrase"
            className={inputCls}
          />
          {error && (
            <p className="text-error text-[10px] flex items-center gap-1">
              <Icon name="x" size={10} />
              {error}
            </p>
          )}
          <button
            onClick={handleCreate}
            disabled={
              creating || !form.name.trim() || !form.private_key.trim()
            }
            className="w-full px-3 py-2 bg-accent text-white font-medium rounded-lg hover:bg-accent-hover disabled:opacity-50 transition-colors"
          >
            {creating ? "Adding..." : "Add Key"}
          </button>
        </div>
      )}

      {listLoading && <Spinner />}
      <div className="space-y-0.5 max-h-64 overflow-y-auto overflow-x-hidden sidebar-scroll">
        {sshKeys.map((k) => (
          <div
            key={k.id}
            className="group rounded-lg hover:bg-surface-2/50 transition-colors"
          >
            <div className="flex items-center gap-2 px-2.5 py-2">
              <div className="w-7 h-7 rounded-lg bg-surface-2 flex items-center justify-center shrink-0">
                <Icon name="key" size={13} className="text-text-tertiary" />
              </div>
              <div className="flex-1 min-w-0">
                <span className="text-[13px] font-medium text-text-primary block truncate">
                  {k.name}
                </span>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="text-[10px] text-accent/70 uppercase font-semibold font-mono shrink-0">
                    {k.key_type}
                  </span>
                  <span
                    className="text-[10px] text-text-muted font-mono truncate"
                    title={k.fingerprint}
                  >
                    {truncateFingerprint(k.fingerprint)}
                  </span>
                </div>
              </div>
            </div>
            <div className="invisible group-hover:visible focus-within:visible flex items-center gap-1 px-2.5 pb-1.5 pt-0.5">
              <ActionButton
                icon="trash"
                title="Delete key"
                onClick={(e) => handleDelete(e, k.id)}
                variant="danger"
                size="sm"
              />
            </div>
          </div>
        ))}
        {sshKeys.length === 0 && !showCreate && (
          <p className="text-[10px] text-text-muted px-3 py-1">
            No SSH keys added yet
          </p>
        )}
      </div>
    </div>
  );
}
