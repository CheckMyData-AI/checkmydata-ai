import { request } from "./_client";

/**
 * Vendor credentials (spec §1.1, §5) — owner-scoped, reusable across
 * connections, and **write-only**: the secret goes up once and the API never
 * hands anything key-shaped back. Everything in {@link VendorCredential} is
 * identity, not material — `fingerprint` answers "is this the same key?" and
 * `meta` carries the non-secret extras the backend lifted out of the payload
 * (for a Google service account, its `client_email`).
 *
 * Re-exported from the `api` barrel (`api.vendorCredentials`); importing this
 * module directly is equally fine.
 */
export interface VendorCredential {
  id: string;
  name: string;
  provider: string;
  fingerprint: string;
  meta?: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
}

/** Create payload. `secret` is the only field that is never echoed back. */
export interface VendorCredentialCreatePayload {
  name: string;
  provider: string;
  secret: string;
}

export interface VendorProviderOption {
  value: string;
  label: string;
  /** Accessible name of the paste area — what this provider's secret *is*. */
  secretLabel: string;
  /** What the user is expected to paste, shown as the textarea placeholder. */
  secretHint: string;
}

/** Mirrors `SUPPORTED_PROVIDERS` in `app/services/vendor_credential_service.py`. */
export const VENDOR_PROVIDERS: readonly VendorProviderOption[] = [
  {
    value: "ga4",
    label: "Google Analytics 4",
    secretLabel: "Service account JSON",
    secretHint: '{\n  "type": "service_account",\n  "client_email": "…",\n  …\n}',
  },
  {
    value: "appstore",
    label: "App Store Connect",
    secretLabel: "Private key (.p8)",
    secretHint: "-----BEGIN PRIVATE KEY-----\n…\n-----END PRIVATE KEY-----",
  },
  {
    value: "googleplay",
    label: "Google Play",
    secretLabel: "Service account JSON",
    secretHint: '{\n  "type": "service_account",\n  "client_email": "…",\n  …\n}',
  },
] as const;

export const GA4_PROVIDER = "ga4";

export function vendorProviderLabel(provider: string): string {
  return VENDOR_PROVIDERS.find((p) => p.value === provider)?.label ?? provider;
}

export function vendorProviderSecretHint(provider: string): string {
  return (
    VENDOR_PROVIDERS.find((p) => p.value === provider)?.secretHint ??
    "Paste the credential"
  );
}

/** Accessible name for the write-only paste area of a given provider. */
export function vendorProviderSecretLabel(provider: string): string {
  return (
    VENDOR_PROVIDERS.find((p) => p.value === provider)?.secretLabel ?? "Credential secret"
  );
}

/**
 * The service-account address the backend lifted into `meta`. This is the only
 * human-readable identity a credential has beyond its name — never the key.
 */
export function credentialAccountEmail(credential: VendorCredential): string | null {
  const email = credential.meta?.client_email;
  return typeof email === "string" && email.length > 0 ? email : null;
}

/** Fingerprints are already short (16 hex); elide anything longer for display. */
export function shortFingerprint(fingerprint: string): string {
  return fingerprint.length > 20
    ? `${fingerprint.slice(0, 8)}…${fingerprint.slice(-8)}`
    : fingerprint;
}

/**
 * True when a delete was refused because a connection still points at the
 * credential (HTTP 409 / FK RESTRICT). The client throws away the status code,
 * so this matches on the backend's message (SCN-116).
 */
export function isCredentialInUseError(err: unknown): boolean {
  const message = err instanceof Error ? err.message : String(err ?? "");
  return /in use by a connection/i.test(message);
}

export const vendorCredentials = {
  list: () => request<VendorCredential[]>("/vendor-credentials"),
  create: (data: VendorCredentialCreatePayload) =>
    request<VendorCredential>("/vendor-credentials", {
      method: "POST",
      body: JSON.stringify(data),
    }),
  delete: (id: string) =>
    request<{ ok: boolean }>(`/vendor-credentials/${id}`, { method: "DELETE" }),
};
