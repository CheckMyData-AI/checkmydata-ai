"use client";

import { useSyncExternalStore } from "react";

type Subscribe = (onChange: () => void) => () => void;

const subscribers = new Map<string, Subscribe>();

function getSubscriber(query: string): Subscribe {
  let sub = subscribers.get(query);
  if (!sub) {
    sub = (onChange) => {
      const mql = window.matchMedia(query);
      mql.addEventListener("change", onChange);
      return () => mql.removeEventListener("change", onChange);
    };
    subscribers.set(query, sub);
  }
  return sub;
}

/** SSR-safe media query hook (server snapshot = `serverDefault`). */
export function useMediaQuery(query: string, serverDefault = false): boolean {
  return useSyncExternalStore(
    getSubscriber(query),
    () => window.matchMedia(query).matches,
    () => serverDefault,
  );
}

/** True when the user asked the OS to reduce motion. */
export function useReducedMotion(): boolean {
  return useMediaQuery("(prefers-reduced-motion: reduce)");
}

/** True on touch-primary devices — skip pointer-driven effects there. */
export function useCoarsePointer(): boolean {
  return useMediaQuery("(pointer: coarse)");
}

/**
 * One-stop guard for expensive choreography (pinned scenes, smooth scroll).
 * Returns true only on motion-allowed, fine-pointer, large viewports.
 */
export function useCinematicCapable(): boolean {
  const reduced = useReducedMotion();
  const coarse = useCoarsePointer();
  const wide = useMediaQuery("(min-width: 1024px)");
  return !reduced && !coarse && wide;
}
