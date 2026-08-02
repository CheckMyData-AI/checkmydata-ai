"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useAppStore } from "@/stores/app-store";
import { confirmAction } from "@/components/ui/ConfirmModal";
import { toast } from "@/stores/toast-store";
import { ActionButton } from "@/components/ui/ActionButton";
import { FormModal } from "@/components/ui/FormModal";
import { Icon } from "@/components/ui/Icon";
import { ListError } from "@/components/ui/ListError";
import { Spinner } from "@/components/ui/Spinner";
import { inputBaseCls as inputCls } from "@/components/ui/Input";
import {
  GA4_PROVIDER,
  VENDOR_PROVIDERS,
  credentialAccountEmail,
  isCredentialInUseError,
  shortFingerprint,
  vendorCredentials,
  vendorProviderLabel,
  vendorProviderSecretHint,
  vendorProviderSecretLabel,
  type VendorCredential,
} from "@/lib/api/vendor-credentials";

/**
 * Vendor credentials panel (spec §6, SCN-114 / SCN-116).
 *
 * Deliberately shaped like `components/ssh/SshKeyManager` — same list/add/delete
 * rhythm, same ActionButton + ConfirmModal idioms — because the two solve the
 * same problem: hold a secret the user can identify but never read back.
 *
 * The write-only rule is enforced here, not just on the server: the pasted
 * secret lives in local state for exactly as long as the create call takes and
 * is dropped the moment it succeeds. Nothing in the list view can render it,
 * because {@link VendorCredential} has no field that carries it.
 */

interface VendorCredentialFieldsProps {
  onCreated: (credential: VendorCredential) => void;
  /** Pin the provider (the GA4 connection form only ever wants `ga4`). */
  lockProvider?: string;
  onCancel?: () => void;
  submitLabel?: string;
}

/**
 * The add-a-credential form, extracted so the GA4 connection form can offer
 * "＋ new credential" inline without duplicating the write-only handling.
 */
export function VendorCredentialFields({
  onCreated,
  lockProvider,
  onCancel,
  submitLabel = "Add credential",
}: VendorCredentialFieldsProps) {
  const [name, setName] = useState("");
  const [provider, setProvider] = useState(lockProvider ?? GA4_PROVIDER);
  const [secret, setSecret] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const effectiveProvider = lockProvider ?? provider;
  const nameMissing = name.trim().length === 0;
  const secretMissing = secret.trim().length === 0;

  /**
   * Validation happens on submit, not by disabling the button. A greyed-out
   * control is a refusal with no explanation — the user clicks a dead button
   * and is told nothing — and it also makes the message below and both
   * `aria-invalid` expressions unreachable. The sibling GA4 form treats a
   * silent no-op on submit as the one outcome it must never produce (SCN-113);
   * this form follows the same rule.
   */
  const handleCreate = async () => {
    if (creating) return;
    if (nameMissing || secretMissing) {
      setError(
        nameMissing && secretMissing
          ? "A name and the credential itself are both required."
          : nameMissing
            ? "A name is required — it is how you will recognise this credential later."
            : `Paste the ${vendorProviderSecretLabel(effectiveProvider).toLowerCase()} — there is nothing to store yet.`,
      );
      return;
    }
    setError(null);
    setCreating(true);
    try {
      const created = await vendorCredentials.create({
        name: name.trim(),
        provider: effectiveProvider,
        secret,
      });
      // Write-only: drop the plaintext before anything else can re-render.
      setSecret("");
      setName("");
      setError(null);
      onCreated(created);
      toast("Vendor credential added", "success");
    } catch (err) {
      // Keep the pasted value: a 422 usually means one bad line, not a retype.
      setError(err instanceof Error ? err.message : "Failed to add credential");
    } finally {
      setCreating(false);
    }
  };

  return (
    <div className="space-y-2.5 text-xs">
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Credential name (e.g. analytics-sa)"
        aria-label="Credential name"
        aria-required="true"
        aria-invalid={error !== null && nameMissing ? "true" : undefined}
        className={inputCls}
        maxLength={255}
      />

      {lockProvider ? (
        <p className="text-[10px] text-text-muted px-1">
          Provider: {vendorProviderLabel(lockProvider)}
        </p>
      ) : (
        <select
          value={provider}
          onChange={(e) => setProvider(e.target.value)}
          aria-label="Credential provider"
          className={inputCls}
        >
          {VENDOR_PROVIDERS.map((p) => (
            <option key={p.value} value={p.value}>
              {p.label}
            </option>
          ))}
        </select>
      )}

      <textarea
        value={secret}
        onChange={(e) => setSecret(e.target.value)}
        placeholder={vendorProviderSecretHint(effectiveProvider)}
        aria-label={vendorProviderSecretLabel(effectiveProvider)}
        aria-required="true"
        aria-invalid={error !== null && secretMissing ? "true" : undefined}
        rows={5}
        spellCheck={false}
        autoComplete="off"
        className={inputCls + " font-mono text-[10px] leading-relaxed resize-y"}
      />
      <p className="text-[10px] text-text-muted px-1">
        Stored encrypted and never shown again — only its fingerprint and the
        service-account address come back.
      </p>

      {error && (
        <p role="alert" className="text-error text-[10px] flex items-start gap-1">
          <Icon name="x" size={10} />
          <span>{error}</span>
        </p>
      )}

      <div className="flex gap-2">
        <button
          type="button"
          onClick={handleCreate}
          disabled={creating}
          className="flex-1 px-3 py-2.5 bg-accent text-white font-medium rounded-lg hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
        >
          {creating ? "Adding…" : submitLabel}
        </button>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="px-3 py-2.5 text-text-tertiary hover:text-text-primary transition-colors"
          >
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}

/** Name the referencing connection when the app store happens to know it. */
function describeInUse(credentialId: string, fallback: string): string {
  const connections = useAppStore.getState().connections ?? [];
  const match = connections.find((c) => c.vendor_credential_id === credentialId);
  return match ? `In use by connection "${match.name}". ${fallback}` : fallback;
}

export function VendorCredentialsPanel() {
  const [credentials, setCredentials] = useState<VendorCredential[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [rowErrors, setRowErrors] = useState<Record<string, string>>({});

  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
    };
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const rows = await vendorCredentials.list();
      if (mountedRef.current) setCredentials(rows);
    } catch (err) {
      if (mountedRef.current) {
        setLoadError(
          err instanceof Error ? err.message : "Failed to load vendor credentials",
        );
      }
    } finally {
      if (mountedRef.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleDelete = async (e: React.MouseEvent, credential: VendorCredential) => {
    e.stopPropagation();
    if (
      !(await confirmAction(`Delete vendor credential "${credential.name}"?`, {
        severity: "warning",
        detail:
          "Connections still using this credential will stop collecting. " +
          "The delete is refused while any connection references it.",
      }))
    )
      return;
    try {
      await vendorCredentials.delete(credential.id);
      setCredentials((prev) => prev.filter((c) => c.id !== credential.id));
      setRowErrors((prev) => {
        const next = { ...prev };
        delete next[credential.id];
        return next;
      });
      toast("Vendor credential deleted", "success");
    } catch (err) {
      const raw = err instanceof Error ? err.message : "Failed to delete credential";
      // 409 / FK RESTRICT: say which connection blocks it, never a bare failure.
      const message = isCredentialInUseError(err)
        ? describeInUse(credential.id, raw)
        : raw;
      setRowErrors((prev) => ({ ...prev, [credential.id]: message }));
      toast(message, "error");
    }
  };

  return (
    <div className="px-1">
      <div className="flex justify-end px-1 mb-1">
        <button
          type="button"
          onClick={() => setShowCreate(true)}
          className="flex items-center gap-1 text-[11px] text-accent hover:text-accent-hover transition-colors"
        >
          <Icon name="plus" size={12} />
          Add
        </button>
      </div>

      <FormModal
        open={showCreate}
        onClose={() => setShowCreate(false)}
        title="Add Vendor Credential"
        maxWidth="max-w-md"
      >
        <VendorCredentialFields
          onCreated={(created) => {
            setCredentials((prev) => [created, ...prev]);
            setShowCreate(false);
          }}
        />
      </FormModal>

      {loading && <Spinner />}

      {!loading && loadError && (
        <ListError
          message={loadError}
          onRetry={() => void load()}
          className="px-2 py-3 text-center text-[10px] text-error flex flex-col items-center gap-1"
        />
      )}

      {!loading && !loadError && credentials.length === 0 && (
        <p className="text-[10px] text-text-muted px-3 py-1">
          No vendor credentials added yet
        </p>
      )}

      <div>
        {credentials.map((c) => {
          const email = credentialAccountEmail(c);
          const rowError = rowErrors[c.id];
          return (
            <div key={c.id}>
              <div className="group relative flex items-center gap-2 pl-3 pr-1.5 py-1.5 rounded-md hover:bg-surface-1 transition-colors">
                <Icon name="key" size={12} className="text-text-muted shrink-0" />
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-1.5">
                    <span className="text-xs font-medium text-text-secondary truncate">
                      {c.name}
                    </span>
                    <span
                      className="shrink-0 text-[10px] px-1 py-px rounded-full bg-accent-muted text-accent leading-none font-mono"
                      title={vendorProviderLabel(c.provider)}
                    >
                      {c.provider.toUpperCase()}
                    </span>
                  </div>
                  <span
                    className="text-[10px] text-text-muted font-mono truncate block mt-0.5"
                    title={c.fingerprint}
                  >
                    {shortFingerprint(c.fingerprint)}
                  </span>
                  {email && (
                    <span className="text-[10px] text-text-tertiary truncate block">
                      {email}
                    </span>
                  )}
                </div>
                <div className="shrink-0 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity duration-150">
                  <ActionButton
                    icon="trash"
                    title="Delete credential"
                    onClick={(e) => void handleDelete(e, c)}
                    variant="danger"
                    size="xs"
                  />
                </div>
              </div>
              {rowError && (
                <p
                  role="alert"
                  className="mx-3 mb-1 px-2 py-1 rounded bg-error-muted text-error text-[10px]"
                >
                  {rowError}
                </p>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
