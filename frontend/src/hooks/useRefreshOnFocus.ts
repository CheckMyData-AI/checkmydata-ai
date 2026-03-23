"use client";

import { useEffect, useRef } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";

const THROTTLE_MS = 30_000;

/**
 * Re-fetches projects and connections when the browser tab regains focus.
 * Throttled to at most once per 30 seconds to avoid excessive API calls.
 */
export function useRefreshOnFocus(isAuthenticated: boolean) {
  const lastRefresh = useRef(0);

  useEffect(() => {
    if (!isAuthenticated) return;

    const handleVisibilityChange = async () => {
      if (document.visibilityState !== "visible") return;
      const now = Date.now();
      if (now - lastRefresh.current < THROTTLE_MS) return;
      lastRefresh.current = now;

      const { activeProject, setProjects, setConnections, setChatSessions } =
        useAppStore.getState();

      try {
        const projects = await api.projects.list();
        setProjects(projects);

        if (activeProject) {
          const [conns, sessions] = await Promise.all([
            api.connections.listByProject(activeProject.id),
            api.chat.listSessions(activeProject.id),
          ]);
          setConnections(conns);
          setChatSessions(sessions);
        }
      } catch {
        /* network unavailable — will retry on next focus */
      }
    };

    document.addEventListener("visibilitychange", handleVisibilityChange);
    return () => document.removeEventListener("visibilitychange", handleVisibilityChange);
  }, [isAuthenticated]);
}
