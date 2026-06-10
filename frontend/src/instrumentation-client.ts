// Sentry browser init. Loaded automatically by Next.js (>=15.3) on the client.
// No-op unless NEXT_PUBLIC_SENTRY_DSN is set at build time.
import * as Sentry from "@sentry/nextjs";

import { scrubEvent } from "./lib/sentry-scrub";

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
  beforeBreadcrumb(breadcrumb) {
    // XHR/fetch breadcrumbs may carry query strings with tokens; keep only
    // method + status, drop bodies/urls' query parts.
    if (breadcrumb.category === "xhr" || breadcrumb.category === "fetch") {
      if (typeof breadcrumb.data?.url === "string") {
        breadcrumb.data.url = breadcrumb.data.url.split("?")[0];
      }
      delete breadcrumb.data?.request_body;
      delete breadcrumb.data?.response_body;
    }
    return breadcrumb;
  },
});

export const onRouterTransitionStart = Sentry.captureRouterTransitionStart;
