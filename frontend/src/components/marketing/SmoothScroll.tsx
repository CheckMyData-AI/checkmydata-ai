"use client";

import { useEffect } from "react";
import Lenis from "lenis";
import { getGsap } from "@/lib/motion/gsap";

/**
 * Lenis smooth scrolling for marketing pages, driven by the GSAP ticker and
 * kept in sync with ScrollTrigger (the canonical Lenis + GSAP recipe).
 *
 * Guards:
 *  - prefers-reduced-motion → native scrolling, nothing initialized
 *  - pointer: coarse (touch) → native scrolling (momentum is already good,
 *    and Lenis on touch costs battery for no gain)
 *
 * Renders nothing.
 */
export function SmoothScroll() {
  useEffect(() => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    if (window.matchMedia("(pointer: coarse)").matches) return;

    const { gsap, ScrollTrigger } = getGsap();

    const lenis = new Lenis({
      lerp: 0.12,
      smoothWheel: true,
      anchors: true,
    });

    lenis.on("scroll", ScrollTrigger.update);

    const raf = (time: number) => lenis.raf(time * 1000);
    gsap.ticker.add(raf);
    gsap.ticker.lagSmoothing(0);

    return () => {
      gsap.ticker.remove(raf);
      lenis.destroy();
      ScrollTrigger.refresh();
    };
  }, []);

  return null;
}
