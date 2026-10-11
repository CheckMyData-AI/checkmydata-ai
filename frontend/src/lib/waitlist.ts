/**
 * Waitlist sign-up — shared by the form and the route handler that mails it.
 *
 * The hosted product was switched off on 2026-10-11 and the site now collects a
 * waitlist instead. There is no backend and no database behind it: a sign-up is
 * one email to the team inbox, so this validation is the only gate it passes.
 */

export const WAITLIST_LIMITS = {
  email: 254,
  name: 100,
  company: 120,
  note: 1000,
} as const;

export interface WaitlistEntry {
  email: string;
  name: string;
  company: string;
  note: string;
}

export type WaitlistParse =
  | { ok: true; entry: WaitlistEntry }
  /** A bot filled the hidden field: answer as if it worked, send nothing. */
  | { ok: false; reason: "bot" }
  | { ok: false; reason: "invalid"; field: keyof WaitlistEntry; message: string };

// Deliberately plain: one @, something on each side, a dot in the domain, no spaces.
// The address is proved by the reply, not by a regex.
const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

function text(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

export function parseWaitlist(body: unknown): WaitlistParse {
  const raw = (body && typeof body === "object" ? body : {}) as Record<string, unknown>;

  // Honeypot: a field people never see. Anything in it is a script.
  if (text(raw.website)) return { ok: false, reason: "bot" };

  const entry: WaitlistEntry = {
    email: text(raw.email).toLowerCase(),
    name: text(raw.name),
    company: text(raw.company),
    note: text(raw.note),
  };

  if (!entry.email) {
    return { ok: false, reason: "invalid", field: "email", message: "Enter your work email." };
  }
  if (entry.email.length > WAITLIST_LIMITS.email || !EMAIL_RE.test(entry.email)) {
    return {
      ok: false,
      reason: "invalid",
      field: "email",
      message: "That doesn't look like an email address.",
    };
  }
  for (const field of ["name", "company", "note"] as const) {
    if (entry[field].length > WAITLIST_LIMITS[field]) {
      return {
        ok: false,
        reason: "invalid",
        field,
        message: `Keep it under ${WAITLIST_LIMITS[field]} characters.`,
      };
    }
  }
  return { ok: true, entry };
}

/** The message the team receives. Plain text: nothing the submitter typed is rendered as HTML. */
export function waitlistEmail(entry: WaitlistEntry): { subject: string; text: string } {
  const who = entry.name || entry.email;
  return {
    subject: `Waitlist: ${who}${entry.company ? ` (${entry.company})` : ""}`,
    text: [
      "New CheckMyData waitlist sign-up",
      "",
      `Email:   ${entry.email}`,
      `Name:    ${entry.name || "—"}`,
      `Company: ${entry.company || "—"}`,
      "",
      "What they want to ask their data:",
      entry.note || "—",
      "",
      "Reply to this message to answer them directly.",
    ].join("\n"),
  };
}
