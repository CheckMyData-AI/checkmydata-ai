// Sentry server-side init (Node runtime). No-op unless the DSN is set.
// PII posture: no default PII, request bodies/headers/cookies stripped.
import * as Sentry from "@sentry/nextjs";

import { scrubEvent } from "./src/lib/sentry-scrub";

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  enabled: Boolean(process.env.NEXT_PUBLIC_SENTRY_DSN),
  environment:
    process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT || process.env.NODE_ENV,
  sendDefaultPii: false,
  tracesSampleRate: Number(
    process.env.NEXT_PUBLIC_SENTRY_TRACES_SAMPLE_RATE ?? "0",
  ),
  beforeSend: scrubEvent,
});
