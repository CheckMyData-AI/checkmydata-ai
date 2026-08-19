"use client";

import { useLayoutEffect, useState } from "react";

const MOBILE_BREAKPOINT = 768;

/**
 * Whether the viewport is narrower than the single `max-width: 767px` breakpoint.
 *
 * The correction is committed in `useLayoutEffect`, before the browser paints
 * (AUD-0819-10). With `useEffect` the first painted frame on a phone showed the
 * desktop shell and then snapped to the drawer layout. Seeding `useState` from
 * `matchMedia` instead would be wrong for a different reason: this renders on the
 * server, where `false` is the only answer available, so a seed would trade the
 * flash for a hydration mismatch.
 */
export function useMobileLayout() {
  const [isMobile, setIsMobile] = useState(false);

  useLayoutEffect(() => {
    const mql = window.matchMedia(`(max-width: ${MOBILE_BREAKPOINT - 1}px)`);
    setIsMobile(mql.matches);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mql.addEventListener("change", handler);
    return () => mql.removeEventListener("change", handler);
  }, []);

  return isMobile;
}
