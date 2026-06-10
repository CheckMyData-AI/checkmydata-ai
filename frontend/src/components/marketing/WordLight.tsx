"use client";

import { useEffect, useRef } from "react";
import { getGsap } from "@/lib/motion/gsap";

/**
 * Scroll-driven word lighting for marketing headlines and statement copy.
 *
 * Words render fully lit by default (SEO / no-JS / reduced-motion safe).
 * When motion is allowed, GSAP dims them and scrubs them back to full
 * brightness word-by-word as the block crosses the viewport.
 *
 * Animates `opacity` only — GPU-safe, no layout shift.
 */
export function WordLight({
  text,
  className = "",
  as: Tag = "span",
  /** Opacity words start from before they are "lit". */
  dim = 0.22,
}: {
  text: string;
  className?: string;
  as?: "span" | "p" | "h2" | "h3";
  dim?: number;
}) {
  const ref = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;

    const { gsap } = getGsap();
    const words = el.querySelectorAll<HTMLElement>("[data-wl]");
    if (words.length === 0) return;

    const ctx = gsap.context(() => {
      gsap.fromTo(
        words,
        { opacity: dim },
        {
          opacity: 1,
          ease: "none",
          stagger: 0.06,
          scrollTrigger: {
            trigger: el,
            start: "top 82%",
            end: "top 38%",
            scrub: 0.5,
          },
        },
      );
    }, el);

    return () => ctx.revert();
  }, [dim]);

  const words = text.split(" ");

  return (
    <Tag ref={ref as React.Ref<never>} className={className}>
      {words.map((word, i) => (
        <span key={`${word}-${i}`} data-wl="" className="inline-block">
          {word}
          {i < words.length - 1 ? "\u00A0" : ""}
        </span>
      ))}
    </Tag>
  );
}
