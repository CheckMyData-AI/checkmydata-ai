// PII / secret scrubbing shared by all Sentry runtimes (client, server, edge).
// Mirrors the backend posture (app/core/sentry.py): no request payloads,
// headers or cookies; user reduced to an opaque id; secret-looking substrings
// redacted from messages.

const REDACTED = "[redacted]";

const SECRET_PATTERNS: Array<{ re: RegExp; replacement: string }> = [
  { re: /(bearer\s+)[a-z0-9._-]{8,}/gi, replacement: `$1${REDACTED}` },
  {
    re: /((?:api[_-]?key|token|secret|password|passwd|pwd)\s*[=:]\s*)\S+/gi,
    replacement: `$1${REDACTED}`,
  },
  // Credentials embedded in URLs: scheme://user:pass@host
  { re: /(:\/\/[^/:@\s]+:)[^@\s]+(@)/g, replacement: `$1${REDACTED}$2` },
];

export function scrubText(value: string): string {
  let out = value;
  for (const { re, replacement } of SECRET_PATTERNS) {
    out = out.replace(re, replacement);
  }
  return out;
}

// Typed loosely on purpose: the event shape differs per runtime and we only
// touch well-known optional fields.
export function scrubEvent(event: any): any {
  if (!event || typeof event !== "object") return event;

  if (event.request && typeof event.request === "object") {
    delete event.request.data;
    delete event.request.headers;
    delete event.request.cookies;
    delete event.request.query_string;
    delete event.request.env;
  }

  if (event.user && typeof event.user === "object") {
    event.user = event.user.id ? { id: event.user.id } : {};
  }

  const excValues = event.exception?.values;
  if (Array.isArray(excValues)) {
    for (const exc of excValues) {
      if (exc && typeof exc.value === "string") {
        exc.value = scrubText(exc.value);
      }
    }
  }

  if (event.message && typeof event.message === "string") {
    event.message = scrubText(event.message);
  }

  const crumbs = event.breadcrumbs;
  const crumbList = Array.isArray(crumbs) ? crumbs : crumbs?.values;
  if (Array.isArray(crumbList)) {
    for (const crumb of crumbList) {
      if (!crumb || typeof crumb !== "object") continue;
      if (typeof crumb.message === "string") {
        crumb.message = scrubText(crumb.message);
      }
      delete crumb.data;
    }
  }

  return event;
}
