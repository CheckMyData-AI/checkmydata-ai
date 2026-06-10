"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { getGsap } from "@/lib/motion/gsap";
import { SchemaGraph } from "@/components/marketing/SchemaGraph";

/**
 * Pinned hero scrollytelling — the product's pipeline told in four beats,
 * scrubbed by scroll:
 *
 *   01 You ask            — plain-English question types itself in
 *   02 It gathers context — schema/codebase/rules/memory converge (graph)
 *   03 It writes SQL      — dialect-aware SQL, fails once, self-heals
 *   04 Verified answer    — chart grows, insight lands
 *
 * Visibility is gated in CSS (`.cmd-story` / `.cmd-story-fallback`):
 * only large, fine-pointer, motion-allowed viewports get the pinned
 * scene. Everyone else (mobile, touch, reduced-motion, no-JS) gets the
 * static fallback passed as `fallback`. SSR renders both; CSS picks one.
 *
 * GSAP timeline scrubs opacity/transform only (GPU-safe). The stage is
 * `position: sticky` — no GSAP pinning, which keeps Lenis happy.
 */

const BEATS = [
  {
    num: "01",
    title: "You ask",
    desc: "A question in plain English. No SQL, no schema browsing — just what you actually want to know.",
  },
  {
    num: "02",
    title: "It gathers context",
    desc: "Your schema, your codebase, your rules, and its own memory of this connection converge before a single line of SQL is written.",
  },
  {
    num: "03",
    title: "It writes & validates SQL",
    desc: "Dialect-aware SQL, executed read-only. When a query fails, it reads the error, repairs itself, and retries.",
  },
  {
    num: "04",
    title: "You get a verified answer",
    desc: "The result, the chart, and the reasoning — with the SQL shown, so you can verify every step.",
  },
] as const;

const QUESTION = "Why did revenue drop last week?";

const SQL_LINES = [
  { text: "SELECT date_trunc('day', created_at) AS day,", tone: "default" },
  { text: "       SUM(amount_cents) / 100.0     AS revenue", tone: "context" },
  { text: "FROM orders", tone: "default" },
  { text: "WHERE created_at >= now() - interval '14 days'", tone: "default" },
  { text: "  AND deleted_at IS NULL  -- soft-deletes", tone: "context" },
  { text: "GROUP BY 1 ORDER BY 1;", tone: "default" },
] as const;

/** Answer chart: 7 days of revenue, one collapsed bar = the drop. */
const ANSWER_BARS = [72, 78, 70, 84, 26, 64, 76] as const;

export function DataStory({ fallback }: { fallback: ReactNode }) {
  const trackRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    const track = trackRef.current;
    if (!track) return;
    // Mirror the CSS gate — don't build a timeline nobody can see.
    const capable = window.matchMedia(
      "(min-width: 1024px) and (prefers-reduced-motion: no-preference) and (pointer: fine)",
    );
    if (!capable.matches) return;

    const { gsap } = getGsap();

    const ctx = gsap.context((self) => {
      const q = self.selector;
      if (!q) return;

      const tl = gsap.timeline({
        defaults: { ease: "none" },
        scrollTrigger: {
          trigger: track,
          start: "top top",
          end: "bottom bottom",
          scrub: 0.6,
        },
      });

      const scenes = q("[data-scene]") as HTMLElement[];
      const captions = q("[data-beat]") as HTMLElement[];

      // Initial state: only scene 0 visible, only caption 0 active.
      gsap.set(scenes.slice(1), { autoAlpha: 0, y: 26, scale: 0.985 });
      gsap.set(captions.slice(1), { opacity: 0.32 });
      gsap.set(q("[data-q-word]"), { opacity: 0 });
      gsap.set(q("[data-sql-line]"), { opacity: 0, x: -10 });
      gsap.set(q("[data-status]"), { autoAlpha: 0, y: 6 });
      gsap.set(q("[data-bar]"), { scaleY: 0.06, transformOrigin: "bottom" });
      gsap.set(q("[data-answer-meta]"), { opacity: 0, y: 10 });

      const switchScene = (from: number, to: number, at: number) => {
        tl.to(scenes[from], { autoAlpha: 0, y: -22, scale: 0.985, duration: 0.5 }, at);
        tl.to(scenes[to], { autoAlpha: 1, y: 0, scale: 1, duration: 0.5 }, at + 0.18);
        tl.to(captions[from], { opacity: 0.32, duration: 0.4 }, at);
        tl.to(captions[to], { opacity: 1, duration: 0.4 }, at + 0.18);
      };

      // ── Beat 1 (0 → 2.2): question types itself in ──
      tl.to(q("[data-q-word]"), { opacity: 1, stagger: 0.28, duration: 0.3 }, 0.2);

      // ── Beat 2 (2.2 → 4.6): context graph converges ──
      switchScene(0, 1, 2.2);

      // ── Beat 3 (4.6 → 7.6): SQL writes, fails, self-heals ──
      switchScene(1, 2, 4.6);
      tl.to(q("[data-sql-line]"), { opacity: 1, x: 0, stagger: 0.22, duration: 0.3 }, 5.0);
      // status chips: running → error → self-heal → validated
      tl.to(q('[data-status="run"]'), { autoAlpha: 1, y: 0, duration: 0.2 }, 5.2);
      tl.to(q('[data-status="run"]'), { autoAlpha: 0, duration: 0.15 }, 6.1);
      tl.to(q('[data-status="error"]'), { autoAlpha: 1, y: 0, duration: 0.2 }, 6.2);
      tl.to(q('[data-status="error"]'), { autoAlpha: 0, duration: 0.15 }, 6.85);
      tl.to(q('[data-status="heal"]'), { autoAlpha: 1, y: 0, duration: 0.2 }, 6.95);
      tl.to(q('[data-status="heal"]'), { autoAlpha: 0, duration: 0.15 }, 7.45);
      tl.to(q('[data-status="ok"]'), { autoAlpha: 1, y: 0, duration: 0.2 }, 7.55);

      // ── Beat 4 (7.9 → 10): verified answer ──
      switchScene(2, 3, 7.9);
      tl.to(
        q("[data-bar]"),
        { scaleY: 1, stagger: 0.12, duration: 0.6, ease: "power3.out" },
        8.3,
      );
      tl.to(q("[data-answer-meta]"), { opacity: 1, y: 0, stagger: 0.2, duration: 0.4 }, 9.0);

      // Progress rail fill across the whole story.
      tl.fromTo(
        q("[data-rail-fill]"),
        { scaleY: 0 },
        { scaleY: 1, duration: 10, transformOrigin: "top" },
        0,
      );
    }, track);

    return () => ctx.revert();
  }, []);

  return (
    <>
      {/* Static fallback — mobile / touch / reduced-motion / no-JS */}
      <div className="cmd-story-fallback">{fallback}</div>

      {/* Pinned story — desktop, fine pointer, motion allowed */}
      <div ref={trackRef} className="cmd-story relative h-[340vh]" aria-hidden="true">
        <div className="sticky top-0 h-screen flex items-center">
          <div className="max-w-6xl mx-auto px-6 w-full grid grid-cols-[340px_minmax(0,1fr)] gap-14 items-center">
            {/* ── Captions + progress rail ── */}
            <div className="relative pl-7">
              <div
                className="absolute left-0 top-1 bottom-1 w-px bg-border-subtle"
                aria-hidden="true"
              >
                <div
                  data-rail-fill=""
                  className="absolute inset-0 bg-accent"
                  style={{ transform: "scaleY(0)", transformOrigin: "top" }}
                />
              </div>
              <ol className="space-y-9">
                {BEATS.map((b) => (
                  <li key={b.num} data-beat="">
                    <p className="font-mono text-xs text-accent mb-1.5">{b.num}</p>
                    <h3 className="font-display text-xl font-semibold text-text-primary tracking-tight">
                      {b.title}
                    </h3>
                    <p className="mt-1.5 text-sm text-text-secondary leading-relaxed">
                      {b.desc}
                    </p>
                  </li>
                ))}
              </ol>
            </div>

            {/* ── Stage ── */}
            <div className="relative overflow-hidden rounded-2xl border border-border-subtle bg-surface-1/40 backdrop-blur-sm aspect-[16/10]">
              {/* scan sweep, consistent with the hero card */}
              <div
                className="cmd-scan pointer-events-none absolute inset-x-0 top-0 h-24 z-10"
                style={{
                  background: "linear-gradient(to bottom, var(--color-accent), transparent)",
                  opacity: 0.06,
                }}
              />

              {/* Scene 1 — the question */}
              <div data-scene="" className="absolute inset-0 flex items-center justify-center p-12">
                <div className="w-full max-w-xl">
                  <div className="flex items-center gap-2 mb-6 text-text-muted text-xs font-mono">
                    <span className="w-3 h-3 rounded-full bg-error/50" />
                    <span className="w-3 h-3 rounded-full bg-warning/50" />
                    <span className="w-3 h-3 rounded-full bg-success/50" />
                    <span className="ml-2">checkmydata — ask anything</span>
                  </div>
                  <p className="font-mono text-2xl leading-relaxed text-text-primary">
                    <span className="text-text-muted select-none">&gt; </span>
                    {QUESTION.split(" ").map((w, i) => (
                      <span key={`${w}-${i}`} data-q-word="" className="inline-block">
                        {w}
                        {"\u00A0"}
                      </span>
                    ))}
                    <span className="cmd-caret" />
                  </p>
                  <p className="mt-6 text-sm text-text-tertiary">
                    No SQL. No schema browsing. Just the question.
                  </p>
                </div>
              </div>

              {/* Scene 2 — context converges (reuses the intelligence core) */}
              <div data-scene="" className="absolute inset-0 flex items-center justify-center p-6">
                <SchemaGraph className="w-full max-w-3xl" />
              </div>

              {/* Scene 3 — SQL + self-heal */}
              <div data-scene="" className="absolute inset-0 flex items-center justify-center p-12">
                <div className="w-full max-w-xl">
                  <div className="rounded-xl border border-border-subtle bg-surface-0/70 p-6 font-mono text-[13px] leading-7">
                    {SQL_LINES.map((line) => (
                      <div
                        key={line.text}
                        data-sql-line=""
                        className={
                          line.tone === "context" ? "text-accent-hover" : "text-text-secondary"
                        }
                      >
                        {line.text}
                      </div>
                    ))}
                  </div>
                  {/* Status chip stack — one visible at a time */}
                  <div className="relative h-10 mt-4">
                    <span
                      data-status="run"
                      className="absolute left-0 inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-border-subtle bg-surface-1 text-xs text-text-secondary font-mono"
                    >
                      <span className="w-1.5 h-1.5 rounded-full bg-accent animate-pulse-dot" />
                      running read-only…
                    </span>
                    <span
                      data-status="error"
                      className="absolute left-0 inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-error/40 bg-error-muted text-xs text-error font-mono"
                    >
                      ✕ ERROR: column &quot;amount&quot; does not exist
                    </span>
                    <span
                      data-status="heal"
                      className="absolute left-0 inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-warning/40 bg-warning-muted text-xs text-warning font-mono"
                    >
                      ↻ self-heal: codebase says it&apos;s amount_cents
                    </span>
                    <span
                      data-status="ok"
                      className="absolute left-0 inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-success/40 bg-success-muted text-xs text-success font-mono"
                    >
                      ✓ validated against your schema
                    </span>
                  </div>
                </div>
              </div>

              {/* Scene 4 — verified answer */}
              <div data-scene="" className="absolute inset-0 flex items-center justify-center p-12">
                <div className="w-full max-w-xl">
                  <div className="flex items-center gap-2 mb-5">
                    <span className="w-2 h-2 rounded-full bg-success" />
                    <span className="text-xs font-semibold text-text-secondary uppercase tracking-wider">
                      Verified answer
                    </span>
                  </div>
                  <p className="font-display text-2xl font-semibold text-text-primary tracking-tight mb-6">
                    Revenue dropped 23% on March&nbsp;20.
                  </p>
                  <div className="flex items-end gap-3 h-32 mb-2" aria-hidden="true">
                    {ANSWER_BARS.map((h, i) => (
                      <div
                        key={i}
                        data-bar=""
                        className={`flex-1 rounded-t-md ${
                          h < 40 ? "bg-warning" : "bg-accent"
                        }`}
                        style={{ height: `${h}%` }}
                      />
                    ))}
                  </div>
                  <div className="h-px bg-border-subtle mb-4" />
                  <p data-answer-meta="" className="text-sm text-text-secondary leading-relaxed">
                    Root cause: payment gateway timeouts affected{" "}
                    <span className="text-text-primary font-semibold">142 orders</span>.
                  </p>
                  <p data-answer-meta="" className="mt-2 text-xs font-mono text-success">
                    + Chart generated · SQL inspectable · Exportable
                  </p>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
