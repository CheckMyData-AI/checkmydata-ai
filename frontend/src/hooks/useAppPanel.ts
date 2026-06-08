"use client";

import { useCallback, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";

export const APP_PANELS = [
  "overview",
  "chat",
  "connections",
  "logs",
  "settings",
  "insights",
  "knowledge",
] as const;

export type AppPanel = (typeof APP_PANELS)[number];

export function isAppPanel(value: string | null): value is AppPanel {
  return value !== null && (APP_PANELS as readonly string[]).includes(value);
}

export function useAppPanel() {
  const router = useRouter();
  const searchParams = useSearchParams();

  const panelParam = searchParams.get("panel");
  const panel: AppPanel | null = useMemo(
    () => (isAppPanel(panelParam) ? panelParam : null),
    [panelParam],
  );

  const setPanel = useCallback(
    (next: AppPanel | null) => {
      const params = new URLSearchParams(searchParams.toString());
      if (next && next !== "overview") {
        params.set("panel", next);
      } else {
        params.delete("panel");
      }
      const qs = params.toString();
      router.replace(qs ? `/app?${qs}` : "/app", { scroll: false });
    },
    [router, searchParams],
  );

  return { panel, setPanel };
}
