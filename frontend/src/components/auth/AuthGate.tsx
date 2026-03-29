"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/auth-store";

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { user, restore } = useAuthStore();
  const [restoring, setRestoring] = useState(true);
  const router = useRouter();

  useEffect(() => {
    restore().finally(() => setRestoring(false));
  }, [restore]);

  useEffect(() => {
    if (!restoring && !user) {
      router.replace("/login");
    }
  }, [restoring, user, router]);

  if (restoring) {
    return (
      <div className="min-h-screen bg-surface-0 flex items-center justify-center">
        <p className="text-sm text-text-muted animate-pulse">Loading...</p>
      </div>
    );
  }

  if (!user) {
    return (
      <div className="min-h-screen bg-surface-0 flex items-center justify-center">
        <p className="text-sm text-text-muted animate-pulse">Redirecting...</p>
      </div>
    );
  }

  return <>{children}</>;
}
