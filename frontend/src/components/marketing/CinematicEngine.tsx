"use client";

import { useEffect } from "react";

/**
 * Drives the cinematic landing effects:
 *  - Reveals `.cmd-reveal` elements once they enter the viewport (IntersectionObserver).
 *  - Applies depth parallax to `[data-cmd-parallax]` layers on scroll (rAF-throttled).
 *
 * Accessibility / performance guards:
 *  - `prefers-reduced-motion`: reveals are shown immediately, parallax is skipped.
 *  - `pointer: coarse` (touch): parallax is disabled to save battery / avoid jank.
 *  - Only `transform`/`opacity` are mutated (GPU-safe).
 *
 * Renders nothing — it only orchestrates DOM already present on the page.
 */
export function CinematicEngine() {
  useEffect(() => {
    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    const coarsePointer = window.matchMedia("(pointer: coarse)").matches;

    const reveals = Array.from(
      document.querySelectorAll<HTMLElement>(".cmd-reveal"),
    );

    // Reduced motion: snap everything to its final state, no observers/listeners.
    if (reduceMotion) {
      reveals.forEach((el) => el.classList.add("is-visible"));
      return;
    }

    // ── Scroll reveals ──────────────────────────────────────────────
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add("is-visible");
            observer.unobserve(entry.target);
          }
        }
      },
      { rootMargin: "0px 0px -10% 0px", threshold: 0.15 },
    );
    reveals.forEach((el) => observer.observe(el));

    // ── Depth parallax (skipped on touch) ───────────────────────────
    const parallaxEls = coarsePointer
      ? []
      : Array.from(
          document.querySelectorAll<HTMLElement>("[data-cmd-parallax]"),
        );

    let frame = 0;
    const applyParallax = () => {
      frame = 0;
      const viewportCenter = window.innerHeight / 2;
      for (const el of parallaxEls) {
        const rect = el.getBoundingClientRect();
        const elCenter = rect.top + rect.height / 2;
        const factor = Number.parseFloat(
          el.dataset.cmdParallax ?? "0",
        );
        const offset = (viewportCenter - elCenter) * factor;
        el.style.transform = `translate3d(0, ${offset.toFixed(1)}px, 0)`;
      }
    };
    const requestParallax = () => {
      if (!frame) frame = requestAnimationFrame(applyParallax);
    };

    if (parallaxEls.length > 0) {
      applyParallax();
      window.addEventListener("scroll", requestParallax, { passive: true });
      window.addEventListener("resize", requestParallax, { passive: true });
    }

    return () => {
      observer.disconnect();
      if (frame) cancelAnimationFrame(frame);
      window.removeEventListener("scroll", requestParallax);
      window.removeEventListener("resize", requestParallax);
    };
  }, []);

  return null;
}
