"use client";

import { useState } from "react";

import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { useAuthStore } from "@/stores/auth-store";
import { toast } from "@/stores/toast-store";

/**
 * Load the demo project, from anywhere, at any time.
 *
 * `POST /api/demo/setup` had exactly one caller: the onboarding wizard, which
 * mounts only while `!user.is_onboarded && projects.length === 0 && !dismissed`.
 * Every exit from that wizard — including pressing Escape — calls
 * `completeOnboarding()`, so the demo was reachable once and then never again. A
 * user who skipped onboarding to look around lost the fastest path to a working
 * product permanently.
 */
export function LoadDemoDataButton({ className = "" }: { className?: string }) {
  const [loading, setLoading] = useState(false);
  const setProjects = useAppStore((s) => s.setProjects);
  const setActiveProject = useAppStore((s) => s.setActiveProject);

  const handleLoad = async () => {
    setLoading(true);
    try {
      await api.demo.setup();
      const [projects, fresh] = await Promise.all([api.projects.list(), api.auth.me()]);
      setProjects(projects);
      const demo = projects.find((p) => p.name?.toLowerCase().includes("demo")) ?? projects[0];
      if (demo) setActiveProject(demo);
      useAuthStore.setState({ user: fresh });
      toast("Demo project loaded — ask it something.", "success");
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "Could not load the demo project.",
        "error",
      );
    } finally {
      setLoading(false);
    }
  };

  return (
    <button type="button" onClick={handleLoad} disabled={loading} className={className}>
      {loading ? "Loading demo…" : "Load demo data"}
    </button>
  );
}
