"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useAuthStore } from "@/stores/auth-store";

export function AuthRedirect() {
  const { user, restore } = useAuthStore();
  const router = useRouter();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    restore().finally(() => setChecked(true));
  }, [restore]);

  useEffect(() => {
    if (checked && user) {
      router.replace("/app");
    }
  }, [checked, user, router]);

  return null;
}
