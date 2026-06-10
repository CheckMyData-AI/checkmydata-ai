"use client";

import { useEffect, useRef } from "react";
import { getGsap } from "@/lib/motion/gsap";

/**
 * Counts a number up from 0 when it scrolls into view.
 * Renders the final value by default (SEO / no-JS / reduced-motion safe);
 * motion-allowed clients see the count-up once.
 */
export function CountUp({
  value,
  className = "",
  duration = 1.4,
}: {
  value: number;
  className?: string;
  duration?: number;
}) {
  const ref = useRef<HTMLSpanElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const { gsap } = getGsap();
    const state = { n: 0 };

    const ctx = gsap.context(() => {
      gsap.to(state, {
        n: value,
        duration,
        ease: "power3.out",
        scrollTrigger: { trigger: el, start: "top 90%", once: true },
        onUpdate: () => {
          el.textContent = Math.round(state.n).toLocaleString("en-US");
        },
      });
    }, el);

    return () => ctx.revert();
  }, [value, duration]);

  return (
    <span ref={ref} className={className}>
      {value.toLocaleString("en-US")}
    </span>
  );
}
