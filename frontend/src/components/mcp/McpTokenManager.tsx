"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "@/lib/api";
import { confirmAction } from "@/components/ui/ConfirmModal";
import { toast } from "@/stores/toast-store";
import { Spinner } from "@/components/ui/Spinner";
import { Icon } from "@/components/ui/Icon";
import { ActionButton } from "@/components/ui/ActionButton";
import { FormModal } from "@/components/ui/FormModal";
import { inputBaseCls as inputCls } from "@/components/ui/Input";
import type { McpToken, McpTokenIssued } from "@/lib/api/auth";

function formatRelative(ts: string | null): string {
  if (!ts) return "—";
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function statusOf(token: McpToken): { label: string; tone: string } {
  if (token.revoked_at) {
    return { label: "revoked", tone: "text-text-muted line-through" };
  }
  if (token.expires_at && new Date(token.expires_at) <= new Date()) {
    return { label: "expired", tone: "text-text-muted" };
  }
  return { label: "active", tone: "text-emerald-400" };
}

function CopyInline({ text, ariaLabel }: { text: string; ariaLabel: string }) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  useEffect(() => () => clearTimeout(timer.current), []);
  return (
    <button
      type="button"
      aria-label={ariaLabel}
      onClick={() => {
        navigator.clipboard
          .writeText(text)
          .then(() => {
            setCopied(true);
            clearTimeout(timer.current);
            timer.current = setTimeout(() => setCopied(false), 1500);
          })
          .catch(() => toast("Failed to copy to clipboard", "error"));
      }}
      className="ml-2 inline-flex items-center gap-1 rounded border border-border-subtle bg-surface-2 px-2 py-0.5 text-[10px] text-text-tertiary hover:text-text-primary"
    >
      <Icon name={copied ? "check" : "clipboard"} size={11} />
      {copied ? "copied" : "copy"}
    </button>
  );
}

export function McpTokenManager() {
  const [tokens, setTokens] = useState<McpToken[]>([]);
  const [loading, setLoading] = useState(true);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [expiresInDays, setExpiresInDays] = useState<string>("");
  const [creating, setCreating] = useState(false);
  const [justIssued, setJustIssued] = useState<McpTokenIssued | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const list = await api.mcpTokens.list();
      setTokens(list);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to load MCP tokens", "error");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const handleCreate = async () => {
    const trimmed = newName.trim();
    if (!trimmed) {
      toast("Token name is required", "error");
      return;
    }
    const expiresParsed = expiresInDays.trim() ? Number(expiresInDays) : null;
    if (expiresParsed !== null && (!Number.isFinite(expiresParsed) || expiresParsed <= 0)) {
      toast("Expiration must be a positive number of days", "error");
      return;
    }
    setCreating(true);
    try {
      const issued = await api.mcpTokens.create(trimmed, expiresParsed);
      setJustIssued(issued);
      setShowCreate(false);
      setNewName("");
      setExpiresInDays("");
      await refresh();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to create MCP token", "error");
    } finally {
      setCreating(false);
    }
  };

  const handleRevoke = async (token: McpToken) => {
    const ok = await confirmAction(
      `Revoke "${token.name}"? Any MCP client using this token will stop working immediately.`,
      { destructive: true, confirmText: "Revoke", severity: "warning" },
    );
    if (!ok) return;
    try {
      await api.mcpTokens.revoke(token.id);
      toast("Token revoked", "success");
      await refresh();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to revoke token", "error");
    }
  };

  const claudeConfig = useMemo(() => {
    const plaintext = justIssued?.token ?? "<your-token>";
    return `{
  "mcpServers": {
    "checkmydata": {
      "command": "python",
      "args": ["-m", "app.mcp_server"],
      "env": {
        "MCP_ENABLED": "true",
        "CHECKMYDATA_API_KEY": "${plaintext}"
      }
    }
  }
}`;
  }, [justIssued]);

  return (
    <section className="rounded-lg border border-border-subtle bg-surface-1/50 overflow-hidden">
      <div className="px-4 py-2.5 border-b border-border-subtle flex items-center justify-between">
        <h3 className="text-xs font-medium text-text-secondary uppercase tracking-wider">
          MCP Tokens
        </h3>
        <ActionButton
          size="xs"
          icon="plus"
          title="Create new MCP token"
          label="New"
          onClick={() => setShowCreate(true)}
        />
      </div>

      <div className="px-4 py-3 text-xs text-text-tertiary border-b border-border-subtle">
        Create a personal MCP token to connect Claude Desktop, Cursor, or any MCP client to
        CheckMyData.ai. Every tool call is scoped to your account and your accessible projects.
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-6">
          <Spinner />
        </div>
      ) : tokens.length === 0 ? (
        <div className="px-4 py-6 text-center text-xs text-text-muted">
          No MCP tokens yet. Create one to start using the agent from external MCP clients.
        </div>
      ) : (
        <ul className="divide-y divide-border-subtle">
          {tokens.map((t) => {
            const status = statusOf(t);
            const isLive = !t.revoked_at;
            return (
              <li key={t.id} className="px-4 py-2.5 flex items-center gap-3">
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-sm text-text-primary truncate">{t.name}</span>
                    <span className={`text-[10px] uppercase tracking-wider ${status.tone}`}>
                      {status.label}
                    </span>
                  </div>
                  <div className="text-[11px] text-text-muted font-mono">
                    {t.token_prefix}… · created {formatRelative(t.created_at)}
                    {t.last_used_at ? ` · last used ${formatRelative(t.last_used_at)}` : ""}
                    {t.expires_at ? ` · expires ${formatRelative(t.expires_at)}` : ""}
                  </div>
                </div>
                {isLive && (
                  <button
                    type="button"
                    aria-label={`Revoke ${t.name}`}
                    onClick={() => handleRevoke(t)}
                    className="text-[11px] text-text-tertiary hover:text-rose-400 transition-colors"
                  >
                    Revoke
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}

      <FormModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        title="Create MCP token"
        maxWidth="max-w-md"
      >
        <div className="space-y-3 text-xs">
          <label className="block">
            <span className="block text-text-secondary mb-1">Name</span>
            <input
              autoFocus
              type="text"
              maxLength={255}
              value={newName}
              onChange={(e) => setNewName(e.target.value)}
              placeholder="MacBook, Cursor workspace, CI runner…"
              className={inputCls}
              aria-label="Token name"
            />
          </label>
          <label className="block">
            <span className="block text-text-secondary mb-1">
              Expires in (days){" "}
              <span className="text-text-muted font-normal">— optional, blank = never</span>
            </span>
            <input
              type="number"
              min={1}
              max={3650}
              value={expiresInDays}
              onChange={(e) => setExpiresInDays(e.target.value)}
              placeholder="e.g. 90"
              className={inputCls}
              aria-label="Token expiry in days"
            />
          </label>
          <button
            type="button"
            onClick={handleCreate}
            disabled={creating || !newName.trim()}
            className="w-full px-3 py-2 bg-accent text-white font-medium rounded-lg hover:bg-accent-hover disabled:opacity-50 transition-colors"
          >
            {creating ? "Creating…" : "Create token"}
          </button>
        </div>
      </FormModal>

      {justIssued && (
        <FormModal
          open
          onClose={() => setJustIssued(null)}
          title="Token created"
          maxWidth="max-w-lg"
        >
          <div className="space-y-3 text-xs">
            <p className="text-text-secondary">
              Copy this token now — it will not be shown again. If you lose it, revoke the
              token and create a new one.
            </p>
            <div className="rounded border border-border-subtle bg-surface-2 px-3 py-2 font-mono break-all text-text-primary">
              {justIssued.token}
              <CopyInline text={justIssued.token} ariaLabel="Copy token" />
            </div>
            <details className="rounded border border-border-subtle bg-surface-1 px-3 py-2">
              <summary className="cursor-pointer text-text-secondary">
                Claude Desktop config snippet
              </summary>
              <pre className="mt-2 whitespace-pre-wrap break-all font-mono text-[11px] text-text-tertiary">
                {claudeConfig}
              </pre>
              <CopyInline text={claudeConfig} ariaLabel="Copy Claude Desktop config" />
            </details>
            <button
              type="button"
              onClick={() => setJustIssued(null)}
              className="w-full px-3 py-2 bg-accent text-white font-medium rounded-lg hover:bg-accent-hover transition-colors"
            >
              I&apos;ve saved it
            </button>
          </div>
        </FormModal>
      )}
    </section>
  );
}
