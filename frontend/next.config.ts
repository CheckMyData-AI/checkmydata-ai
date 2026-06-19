import { withSentryConfig } from "@sentry/nextjs";
import type { NextConfig } from "next";

const isProd = process.env.NODE_ENV === "production";

// API + WS origins the browser is allowed to talk to (connect-src).
const apiOrigin = (() => {
  try {
    return new URL(process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api").origin;
  } catch {
    return "http://localhost:8000";
  }
})();
const wsOrigin = apiOrigin.replace(/^http/, "ws");

// CSP for the Next shell. Next.js injects inline bootstrap scripts, so
// 'unsafe-inline' is required for script-src without a nonce pipeline;
// 'unsafe-eval' is only needed for dev (react-refresh).
// Google Identity Services (Sign in with Google) needs accounts.google.com in
// script-src/connect-src/frame-src — mirror backend SECURITY_CSP allowlist.
const csp = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline' https://accounts.google.com https://apis.google.com${isProd ? "" : " 'unsafe-eval'"}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https://*.googleusercontent.com",
  "font-src 'self' data:",
  `connect-src 'self' ${apiOrigin} ${wsOrigin} https://accounts.google.com https://*.ingest.sentry.io https://*.ingest.us.sentry.io https://*.ingest.de.sentry.io`,
  "frame-src https://accounts.google.com",
  "frame-ancestors 'none'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  ...(isProd
    ? [
        {
          key: "Strict-Transport-Security",
          value: "max-age=63072000; includeSubDomains",
        },
      ]
    : []),
];

const nextConfig: NextConfig = {
  output: "standalone",
  async headers() {
    return [
      {
        source: "/:path*",
        headers: securityHeaders,
      },
    ];
  },
};

// Sentry build-time wrapper (T-OBS-1). Source-map upload only happens when
// SENTRY_AUTH_TOKEN / SENTRY_ORG / SENTRY_PROJECT are set in the build env;
// otherwise this is a no-op wrapper and the build stays unchanged.
export default withSentryConfig(nextConfig, {
  org: process.env.SENTRY_ORG,
  project: process.env.SENTRY_PROJECT,
  authToken: process.env.SENTRY_AUTH_TOKEN,
  silent: !process.env.CI,
  sourcemaps: {
    disable: !process.env.SENTRY_AUTH_TOKEN,
  },
  disableLogger: true,
  // Tunnel disabled: the API origin is cross-domain and the backend already
  // reports its own errors. Enable a /monitoring tunnel only if ad-blockers
  // become a measurable problem.
});
