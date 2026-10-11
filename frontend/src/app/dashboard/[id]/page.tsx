import { Suspense } from "react";
import DashboardView from "./DashboardView";

// checkmydata.ai is a static export (SITE_EXPORT=1, 2026-10-12), which needs a dynamic
// segment's pages named at build time and `dynamicParams = false`. A shared dashboard's
// id is only known at runtime, so ONE placeholder is generated. On the hosted site
// `/dashboard/*` redirects to the waitlist before this page is served; a self-hosted
// server rewrites `/dashboard/<id>` to `/dashboard/_?id=<id>` (next.config.ts) and
// DashboardView reads the id from the query.
export const dynamicParams = false;

export function generateStaticParams() {
  return [{ id: "_" }];
}

export default function DashboardPage() {
  return (
    <Suspense fallback={null}>
      <DashboardView />
    </Suspense>
  );
}
