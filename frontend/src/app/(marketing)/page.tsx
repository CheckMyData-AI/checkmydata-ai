import type React from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { LogoMark } from "@/components/ui/Logo";
import { AuthRedirect } from "@/components/auth/AuthRedirect";
import { CinematicEngine } from "@/components/marketing/CinematicEngine";
import { SchemaGraph } from "@/components/marketing/SchemaGraph";
import { DataStory } from "@/components/marketing/DataStory";
import { WordLight } from "@/components/marketing/WordLight";
import { CountUp } from "@/components/marketing/CountUp";
import { FaqAccordion } from "@/components/marketing/FaqAccordion";

export const metadata: Metadata = {
  title: "CheckMyData.ai — AI Analyst for Your Database",
  description:
    "Ask your database in plain English and get correct answers. CheckMyData reads your schema and codebase, writes the SQL, and explains the result — natural-language text-to-SQL for PostgreSQL, MySQL, ClickHouse, and MongoDB. Open-source, self-hostable, privacy-first.",
  openGraph: {
    title: "CheckMyData.ai — AI Analyst for Your Database",
    description:
      "Correct answers from your database on the first try. CheckMyData understands your schema and codebase, so plain-English questions become trustworthy SQL. Open-source, self-hostable, privacy-first.",
    url: "https://checkmydata.ai",
    siteName: "CheckMyData.ai",
    images: [
      {
        url: "/og-image.png",
        width: 1200,
        height: 630,
        alt: "CheckMyData.ai — AI analyst for your database",
      },
    ],
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "CheckMyData.ai — AI Analyst for Your Database",
    description:
      "Correct answers from your database on the first try. Plain-English questions become trustworthy SQL. Open-source & privacy-first.",
    images: ["/og-image.png"],
  },
  alternates: { canonical: "https://checkmydata.ai" },
};

const GITHUB_URL = "https://github.com/CheckMyData-AI/checkmydata-ai";

const GitHubIcon = ({ size = 18 }: { size?: number }) => (
  <svg
    width={size}
    height={size}
    viewBox="0 0 24 24"
    fill="currentColor"
    aria-hidden="true"
  >
    <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z" />
  </svg>
);

const FEATURES = [
  {
    icon: (
      <>
        <path d="M6 3v12" />
        <circle cx="18" cy="6" r="3" />
        <circle cx="6" cy="18" r="3" />
        <path d="M18 9a9 9 0 0 1-9 9" />
      </>
    ),
    title: "Codebase-aware context",
    desc: "It indexes your repository, so answers reflect your real business logic — soft-deletes, enums, money-in-cents — not just raw column names. That context is the difference between a correct answer and a confident wrong one.",
    highlight: true,
  },
  {
    icon: (
      <>
        <polyline points="1 4 1 10 7 10" />
        <path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10" />
      </>
    ),
    title: "Self-healing queries",
    desc: "When a query errors, it reads the failure, pulls in the missing context, and repairs itself — so you get a working answer instead of a stack trace.",
  },
  {
    icon: (
      <>
        <circle cx="12" cy="12" r="9" />
        <polyline points="12 7 12 12 15 14" />
      </>
    ),
    title: "Institutional memory",
    desc: "It learns the patterns of each connection over time, confirms what's right, and lets go of stale assumptions — so the more you use it, the sharper it gets.",
  },
  {
    icon: (
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    ),
    title: "Natural-language queries",
    desc: "Ask in plain English and get back the SQL, the result, and an explanation — so anyone on the team can answer their own data questions.",
  },
  {
    icon: (
      <>
        <ellipse cx="12" cy="5" rx="9" ry="3" />
        <path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5" />
        <path d="M3 12c0 1.7 4 3 9 3s9-1.3 9-3" />
      </>
    ),
    title: "Multi-database support",
    desc: "Connect PostgreSQL, MySQL, ClickHouse, and MongoDB — directly or over an SSH tunnel — and query them all the same way.",
  },
  {
    icon: (
      <>
        <line x1="18" y1="20" x2="18" y2="10" />
        <line x1="12" y1="20" x2="12" y2="4" />
        <line x1="6" y1="20" x2="6" y2="14" />
      </>
    ),
    title: "Automatic visualization",
    desc: "Charts, tables, and exports are generated for you, so you see the shape of the answer without building a dashboard.",
  },
  {
    icon: (
      <>
        <rect x="2" y="2" width="20" height="8" rx="2" ry="2" />
        <rect x="2" y="14" width="20" height="8" rx="2" ry="2" />
        <line x1="6" y1="6" x2="6.01" y2="6" />
        <line x1="6" y1="18" x2="6.01" y2="18" />
      </>
    ),
    title: "Self-hostable",
    desc: "Deploy anywhere with Docker and keep full control of your environment — no vendor lock-in, no data leaving your infrastructure.",
  },
  {
    icon: (
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    ),
    title: "Privacy-first by design",
    desc: "No tracking, no telemetry, read-only by default — and the source is open, so you can verify exactly how your data is handled.",
  },
] as { icon: React.ReactNode; title: string; desc: string; highlight?: boolean }[];

const TRUST_SIGNALS = [
  "MIT open source",
  "Read-only by default",
  "Credentials encrypted at rest",
  "Self-host or hosted",
  "Transparent SQL you can inspect",
] as const;

const CONTEXT_INPUTS = [
  {
    title: "Your schema",
    desc: "Tables, columns, types, and relationships — read directly from your database.",
  },
  {
    title: "Your codebase",
    desc: "Business logic from your repository: what \u201cactive\u201d, \u201camount\u201d, or \u201cdeleted\u201d really mean.",
  },
  {
    title: "Your rules",
    desc: "Conventions and guardrails you set, applied to every query it writes.",
  },
  {
    title: "Its memory",
    desc: "Patterns it has confirmed on this connection over time, reused on the next question.",
  },
] as const;

const COMPARISONS = [
  {
    title: "vs. a plain SQL editor",
    points: [
      { ok: false, text: "Has no idea what your columns mean — you supply all the context." },
      { ok: false, text: "You hand-write and debug every query yourself." },
      { ok: true, text: "CheckMyData knows your schema and code, then writes the SQL for you." },
    ],
  },
  {
    title: "vs. a generic chatbot",
    points: [
      { ok: false, text: "Guesses your schema and invents table and column names." },
      { ok: false, text: "Can't run the query or check whether the result is right." },
      { ok: true, text: "CheckMyData grounds every answer in your real schema, then runs and validates it." },
    ],
  },
] as const;

const LANDING_FAQS = [
  {
    q: "Is it safe to connect my production database?",
    a: "Yes. CheckMyData is read-only by default, your credentials are encrypted at rest, and you can connect over an SSH tunnel. The entire project is open source, so you can audit exactly how connections are handled — or self-host it so nothing leaves your infrastructure.",
  },
  {
    q: "How is this different from asking ChatGPT to write SQL?",
    a: "A generic chatbot guesses your schema and can't run the query. CheckMyData reads your real schema and your codebase first, writes SQL grounded in that context, then executes and validates the result — and repairs itself if a query fails.",
  },
  {
    q: "Do I need to know SQL to use it?",
    a: "No. Ask your question in plain English and you get the answer, a chart, and an explanation. The generated SQL is always shown if you want to inspect, copy, or tweak it.",
  },
  {
    q: "What does connecting my codebase actually send?",
    a: "It indexes structural metadata — file names, entity and function names, and signatures — to learn what your data means. It is used to write better, more correct queries, and you stay in control of which repository is connected.",
  },
  {
    q: "Can I self-host, or is it only hosted?",
    a: "Both. Use the hosted version to start in minutes, or clone the repository and run the Docker setup for full control. The same open-source code powers both.",
  },
  {
    q: "Which databases and LLM providers are supported?",
    a: "Databases: PostgreSQL, MySQL, ClickHouse, and MongoDB. LLM providers: OpenAI, Anthropic, and OpenRouter, with automatic fallback if one is unavailable.",
  },
] as const;

async function getGitHubStars(): Promise<number | null> {
  try {
    const res = await fetch(
      "https://api.github.com/repos/CheckMyData-AI/checkmydata-ai",
      {
        next: { revalidate: 3600 },
        headers: { Accept: "application/vnd.github+json" },
      },
    );
    if (!res.ok) return null;
    const data = (await res.json()) as { stargazers_count?: number };
    const stars = data?.stargazers_count;
    return typeof stars === "number" && stars > 0 ? stars : null;
  } catch {
    return null;
  }
}

const USE_CASES = [
  "Find why revenue dropped last week",
  "Analyze user behavior without writing SQL",
  "Explore data across multiple databases",
  "Debug backend logic with real data",
  "Build internal dashboards in minutes",
] as const;

const STEPS = [
  {
    num: "01",
    title: "Connect",
    desc: "Plug in your database. Securely.",
  },
  {
    num: "02",
    title: "Ask",
    desc: "Type your question in plain English.",
  },
  {
    num: "03",
    title: "Get answers",
    desc: "Queries, charts, and insights, instantly.",
  },
] as const;

export default async function LandingPage() {
  const stars = await getGitHubStars();

  return (
    <>
      <AuthRedirect />
      <CinematicEngine />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify({
            "@context": "https://schema.org",
            "@graph": [
              {
                "@type": "Organization",
                "@id": "https://checkmydata.ai/#organization",
                name: "CheckMyData.ai",
                url: "https://checkmydata.ai",
                logo: "https://checkmydata.ai/icon-512.png",
                description:
                  "Open-source AI database agent that turns plain-English questions into correct, validated SQL using your schema and codebase as context.",
                sameAs: [GITHUB_URL],
              },
              {
                "@type": "SoftwareApplication",
                "@id": "https://checkmydata.ai/#software",
                name: "CheckMyData.ai",
                applicationCategory: "DeveloperApplication",
                operatingSystem: "Web, Docker, Linux, macOS",
                description:
                  "Open-source AI analyst for your database. Ask in plain English and get correct, validated SQL grounded in your schema and codebase — for PostgreSQL, MySQL, ClickHouse, and MongoDB.",
                url: "https://checkmydata.ai",
                downloadUrl: GITHUB_URL,
                license: "https://opensource.org/licenses/MIT",
                publisher: { "@id": "https://checkmydata.ai/#organization" },
                offers: {
                  "@type": "Offer",
                  price: "0",
                  priceCurrency: "USD",
                },
              },
              {
                "@type": "FAQPage",
                "@id": "https://checkmydata.ai/#faq",
                mainEntity: LANDING_FAQS.map((faq) => ({
                  "@type": "Question",
                  name: faq.q,
                  acceptedAnswer: {
                    "@type": "Answer",
                    text: faq.a,
                  },
                })),
              },
            ],
          }),
        }}
      />

      {/* ── HERO ── */}
      <section className="relative overflow-hidden cmd-stage">
        {/* depth-0 — drifting technical grid */}
        <div className="cmd-grid" aria-hidden="true" />

        {/* depth-1 — atmospheric glow blobs (parallax + pulse) */}
        <div
          className="pointer-events-none absolute inset-0 overflow-hidden"
          aria-hidden="true"
        >
          <div
            data-cmd-parallax="0.05"
            className="cmd-parallax absolute"
            style={{ top: -180, left: "6%", width: 520, height: 520 }}
          >
            <div
              className="cmd-glow"
              style={{
                inset: 0,
                width: "100%",
                height: "100%",
                background:
                  "color-mix(in srgb, var(--color-accent) 30%, transparent)",
              }}
            />
          </div>
          <div
            data-cmd-parallax="0.08"
            className="cmd-parallax absolute"
            style={{ top: 80, right: "2%", width: 440, height: 440 }}
          >
            <div
              className="cmd-glow"
              style={{
                inset: 0,
                width: "100%",
                height: "100%",
                background:
                  "color-mix(in srgb, var(--color-info) 26%, transparent)",
                animationDelay: "-4s",
              }}
            />
          </div>
          <div
            data-cmd-parallax="0.03"
            className="cmd-parallax absolute"
            style={{ bottom: -140, left: "42%", width: 380, height: 380 }}
          >
            <div
              className="cmd-glow"
              style={{
                inset: 0,
                width: "100%",
                height: "100%",
                background:
                  "color-mix(in srgb, var(--color-success) 18%, transparent)",
                animationDelay: "-8s",
              }}
            />
          </div>
        </div>

        <div className="max-w-6xl mx-auto px-6 pt-24 pb-16 sm:pt-32 sm:pb-20 relative">
          <div className="max-w-3xl mx-auto text-center">
            <div className="cmd-reveal inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-border-subtle bg-surface-1 text-xs text-text-secondary mb-8">
              <span className="w-2 h-2 rounded-full bg-success animate-pulse-dot" />
              Open Source &middot; MIT License
            </div>

            <p
              className="cmd-reveal text-sm sm:text-base text-accent font-medium mb-4"
              style={{ ["--cmd-i"]: 1 } as React.CSSProperties}
            >
              Like ChatGPT, but for your database.
            </p>

            <h1
              className="cmd-reveal font-display text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight text-text-primary leading-[1.08] text-balance"
              style={{ ["--cmd-i"]: 2 } as React.CSSProperties}
            >
              Correct answers from
              <br />
              your database.
              <br />
              <span className="text-text-tertiary">On the first try.</span>
            </h1>

            <p
              className="cmd-reveal mt-8 text-lg sm:text-xl text-text-secondary max-w-2xl mx-auto leading-relaxed text-pretty"
              style={{ ["--cmd-i"]: 3 } as React.CSSProperties}
            >
              CheckMyData reads your schema <em className="not-italic text-text-primary">and</em>{" "}
              your codebase, so it knows your cents-vs-dollars, soft-deletes, and
              enums. Ask in plain English; get SQL and answers you can trust.
            </p>

            <div
              className="cmd-reveal mt-4 flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-sm text-text-tertiary font-mono"
              style={{ ["--cmd-i"]: 4 } as React.CSSProperties}
            >
              <span>PostgreSQL</span>
              <span className="text-border-default">&middot;</span>
              <span>MySQL</span>
              <span className="text-border-default">&middot;</span>
              <span>ClickHouse</span>
              <span className="text-border-default">&middot;</span>
              <span>MongoDB</span>
            </div>

            <div
              className="cmd-reveal mt-10 flex flex-col sm:flex-row items-center justify-center gap-4"
              style={{ ["--cmd-i"]: 5 } as React.CSSProperties}
            >
              <Link
                href="/login"
                className="w-full sm:w-auto px-8 py-3.5 text-sm font-semibold text-white bg-accent hover:bg-accent-hover rounded-lg transition-colors text-center"
              >
                Get Started Free
              </Link>
              <a
                href={GITHUB_URL}
                target="_blank"
                rel="noopener noreferrer"
                className="w-full sm:w-auto px-8 py-3.5 text-sm font-semibold text-text-primary border border-border-default hover:border-accent hover:text-accent rounded-lg transition-colors text-center inline-flex items-center justify-center gap-2"
              >
                <GitHubIcon />
                View on GitHub
              </a>
            </div>

            <p
              className="cmd-reveal mt-5 text-xs text-text-tertiary"
              style={{ ["--cmd-i"]: 6 } as React.CSSProperties}
            >
              No credit card. Deploy in minutes. Self-host or use hosted.
            </p>
          </div>

        </div>
      </section>

      {/* ── DATA STORY — pinned scrollytelling on desktop, static core elsewhere ── */}
      <section className="relative pb-16 sm:pb-20" aria-label="How CheckMyData answers a question">
        <DataStory
          fallback={
            <div className="max-w-4xl mx-auto px-6">
              <div
                className="cmd-reveal cmd-reveal-rise"
                style={{ ["--cmd-i"]: 1 } as React.CSSProperties}
              >
                <div className="cmd-float relative overflow-hidden rounded-2xl border border-border-subtle bg-surface-1/40 backdrop-blur-sm p-4 sm:p-8">
                  {/* scan sweep */}
                  <div
                    aria-hidden="true"
                    className="cmd-scan pointer-events-none absolute inset-x-0 top-0 h-24"
                    style={{
                      background:
                        "linear-gradient(to bottom, var(--color-accent), transparent)",
                      opacity: 0.06,
                    }}
                  />
                  <SchemaGraph />
                </div>
              </div>
            </div>
          }
        />
      </section>

      {/* ── TRUST SIGNALS BAR ── */}
      <section className="border-y border-border-subtle bg-surface-1/50">
        <div className="cmd-reveal max-w-6xl mx-auto px-6 py-6 flex flex-wrap items-center justify-center gap-x-6 gap-y-3 text-sm text-text-secondary">
          {stars !== null && (
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1.5 text-text-primary hover:text-accent transition-colors"
            >
              <svg width={16} height={16} viewBox="0 0 24 24" fill="currentColor" className="text-warning" aria-hidden="true">
                <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
              </svg>
              <CountUp value={stars} className="font-semibold tabular-nums" />
              <span className="text-text-tertiary">stars on GitHub</span>
            </a>
          )}
          {TRUST_SIGNALS.map((signal) => (
            <span key={signal} className="inline-flex items-center gap-1.5">
              <svg
                width={15}
                height={15}
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={2.5}
                strokeLinecap="round"
                strokeLinejoin="round"
                className="text-accent shrink-0"
                aria-hidden="true"
              >
                <polyline points="20 6 9 17 4 12" />
              </svg>
              {signal}
            </span>
          ))}
        </div>
      </section>

      {/* ── WHY CORRECT — context engine + comparison ── */}
      <section className="py-20 sm:py-28 border-t border-border-subtle" id="why-correct">
        <div className="max-w-6xl mx-auto px-6">
          <div className="cmd-reveal text-center mb-4">
            <p className="text-sm font-medium text-accent mb-3">The context engine</p>
            <h2 className="font-display text-3xl sm:text-4xl font-bold tracking-tight text-text-primary">
              Why the answers are{" "}
              <span className="text-accent">actually correct</span>
            </h2>
          </div>
          <WordLight
            as="p"
            text="Data is abundant. The context needed to query it correctly is scarce. CheckMyData assembles that context before it writes a single line of SQL."
            className="cmd-reveal text-center text-lg text-text-primary max-w-2xl mx-auto mb-16 leading-relaxed text-pretty block"
          />

          <div className="grid lg:grid-cols-2 gap-10 lg:gap-12 items-center">
            <ul className="space-y-4">
              {CONTEXT_INPUTS.map((input, i) => (
                <li
                  key={input.title}
                  style={{ ["--cmd-i"]: i + 1 } as React.CSSProperties}
                  className="cmd-reveal cmd-reveal-left flex items-start gap-4 bg-surface-1 border border-border-subtle rounded-xl p-4 sm:p-5"
                >
                  <span className="mt-0.5 w-8 h-8 shrink-0 rounded-lg bg-accent-muted text-accent font-mono text-xs font-semibold flex items-center justify-center">
                    {String(i + 1).padStart(2, "0")}
                  </span>
                  <div>
                    <h3 className="text-sm font-semibold text-text-primary">
                      {input.title}
                    </h3>
                    <p className="text-sm text-text-secondary leading-relaxed mt-0.5">
                      {input.desc}
                    </p>
                  </div>
                </li>
              ))}
            </ul>

            <div
              className="cmd-reveal cmd-reveal-right relative overflow-hidden rounded-2xl border border-accent/40 ring-1 ring-accent/10 bg-surface-1 p-8 text-center"
              style={{ ["--cmd-i"]: 2 } as React.CSSProperties}
            >
              <div
                aria-hidden="true"
                className="pointer-events-none absolute"
                style={{
                  top: -100,
                  left: "50%",
                  width: 360,
                  height: 240,
                  transform: "translateX(-50%)",
                }}
              >
                <div
                  className="cmd-glow"
                  style={{
                    inset: 0,
                    width: "100%",
                    height: "100%",
                    background:
                      "color-mix(in srgb, var(--color-accent) 24%, transparent)",
                  }}
                />
              </div>
              <div className="relative">
                <svg
                  width={28}
                  height={28}
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="text-accent mx-auto mb-4"
                  aria-hidden="true"
                >
                  <polyline points="20 6 9 17 4 12" />
                </svg>
                <p className="text-base font-semibold text-text-primary">
                  Validated, dialect-aware SQL
                </p>
                <p className="mt-2 text-sm text-text-secondary leading-relaxed text-pretty">
                  The query is checked against your real schema and run for you —
                  and if it fails, it self-heals and tries again. You get an answer
                  you can trust, with the SQL shown so you can verify it.
                </p>
              </div>
            </div>
          </div>

          {/* comparison */}
          <div className="mt-16 sm:mt-20 grid sm:grid-cols-2 gap-6">
            {COMPARISONS.map((c, i) => (
              <div
                key={c.title}
                style={{ ["--cmd-i"]: i } as React.CSSProperties}
                className="cmd-reveal cmd-reveal-scale bg-surface-1 border border-border-subtle rounded-xl p-6"
              >
                <h3 className="text-base font-semibold text-text-primary mb-4">
                  {c.title}
                </h3>
                <ul className="space-y-3">
                  {c.points.map((p) => (
                    <li key={p.text} className="flex items-start gap-3 text-sm leading-relaxed">
                      {p.ok ? (
                        <svg
                          width={18}
                          height={18}
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth={2.5}
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          className="text-success shrink-0 mt-0.5"
                          aria-hidden="true"
                        >
                          <polyline points="20 6 9 17 4 12" />
                        </svg>
                      ) : (
                        <svg
                          width={18}
                          height={18}
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth={2.5}
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          className="text-text-muted shrink-0 mt-0.5"
                          aria-hidden="true"
                        >
                          <line x1="18" y1="6" x2="6" y2="18" />
                          <line x1="6" y1="6" x2="18" y2="18" />
                        </svg>
                      )}
                      <span className={p.ok ? "text-text-primary" : "text-text-secondary"}>
                        {p.text}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── VALUE SECTION ── */}
      <section className="py-20 sm:py-28" id="features">
        <div className="max-w-6xl mx-auto px-6">
          <div className="cmd-reveal text-center mb-6">
            <h2 className="font-display text-3xl sm:text-4xl font-bold tracking-tight text-text-primary">
              Everything you need to actually
              <br className="hidden sm:block" />{" "}
              <span className="text-accent">understand your data</span>
            </h2>
          </div>
          <p
            className="cmd-reveal text-center text-text-secondary max-w-xl mx-auto mb-16 leading-relaxed text-pretty"
            style={{ ["--cmd-i"]: 1 } as React.CSSProperties}
          >
            Context-aware answers, self-healing queries, and explanations you can
            trust — backed by readable SQL and exportable charts.
          </p>

          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {FEATURES.map((f, i) => (
              <div
                key={f.title}
                style={{ ["--cmd-i"]: i % 3 } as React.CSSProperties}
                className={`cmd-reveal cmd-reveal-scale bg-surface-1 border rounded-xl p-6 transition-colors group ${
                  f.highlight
                    ? "sm:col-span-2 border-accent/40 ring-1 ring-accent/10"
                    : "border-border-subtle hover:border-accent/30"
                }`}
              >
                <div className="flex items-start gap-4">
                  <div className="w-10 h-10 shrink-0 rounded-lg bg-accent-muted flex items-center justify-center group-hover:bg-accent/20 transition-colors">
                    <svg
                      width={20}
                      height={20}
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth={2}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      className="text-accent"
                    >
                      {f.icon}
                    </svg>
                  </div>
                  <div>
                    {f.highlight && (
                      <span className="mb-1 inline-block text-xs font-medium text-accent">
                        Core differentiator
                      </span>
                    )}
                    <h3 className="text-base font-semibold text-text-primary mb-1">
                      {f.title}
                    </h3>
                    <p className="text-sm text-text-secondary leading-relaxed">
                      {f.desc}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── USE CASES ── */}
      <section className="py-20 sm:py-28 border-t border-border-subtle" id="use-cases">
        <div className="max-w-6xl mx-auto px-6">
          <div className="grid lg:grid-cols-2 gap-12 items-center">
            <div className="cmd-reveal cmd-reveal-left">
              <h2 className="font-display text-3xl sm:text-4xl font-bold tracking-tight text-text-primary mb-4">
                What can you do with it?
              </h2>
              <p className="text-text-secondary leading-relaxed mb-8 text-pretty">
                Ask questions in everyday language and get back the rigor of a
                data scientist: the query, the result, and the reasoning behind
                it.
              </p>
              <ul className="space-y-4">
                {USE_CASES.map((uc, i) => (
                  <li
                    key={uc}
                    style={{ ["--cmd-i"]: i + 1 } as React.CSSProperties}
                    className="cmd-reveal flex items-start gap-3 text-text-primary"
                  >
                    <svg
                      width={20}
                      height={20}
                      viewBox="0 0 24 24"
                      fill="none"
                      stroke="currentColor"
                      strokeWidth={2.5}
                      strokeLinecap="round"
                      strokeLinejoin="round"
                      className="text-accent shrink-0 mt-0.5"
                    >
                      <polyline points="9 11 12 14 22 4" />
                      <path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11" />
                    </svg>
                    <span className="text-sm sm:text-base leading-snug">{uc}</span>
                  </li>
                ))}
              </ul>
            </div>

            <div className="cmd-reveal cmd-reveal-right cmd-float bg-surface-1 border border-border-subtle rounded-xl p-6 sm:p-8 font-mono text-sm">
              <div className="flex items-center gap-2 mb-4 text-text-muted text-xs">
                <span className="w-3 h-3 rounded-full bg-error/50" />
                <span className="w-3 h-3 rounded-full bg-warning/50" />
                <span className="w-3 h-3 rounded-full bg-success/50" />
                <span className="ml-2">checkmydata</span>
              </div>
              <div className="space-y-3 text-text-secondary">
                <p
                  className="cmd-reveal"
                  style={{ ["--cmd-i"]: 2 } as React.CSSProperties}
                >
                  <span className="text-text-muted">you:</span>{" "}
                  <span className="text-text-primary">Why did revenue drop last week?</span>
                </p>
                <p
                  className="cmd-reveal"
                  style={{ ["--cmd-i"]: 4 } as React.CSSProperties}
                >
                  <span className="text-text-muted">ai:</span>{" "}
                  <span className="text-accent">Analyzing orders table...</span>
                </p>
                <p
                  className="cmd-reveal text-text-tertiary text-xs pl-4 border-l border-border-subtle"
                  style={{ ["--cmd-i"]: 6 } as React.CSSProperties}
                >
                  SELECT date, SUM(amount) FROM orders
                  <br />
                  WHERE date &gt;= &apos;2026-03-17&apos;
                  <br />
                  GROUP BY date ORDER BY date
                </p>
                <p
                  className="cmd-reveal"
                  style={{ ["--cmd-i"]: 8 } as React.CSSProperties}
                >
                  <span className="text-text-muted">ai:</span>{" "}
                  Revenue dropped 23% on March 20.
                  <br />
                  <span className="text-text-tertiary">
                    Root cause: payment gateway timeout affected 142 orders.
                  </span>
                </p>
                <p
                  className="cmd-reveal text-success text-xs"
                  style={{ ["--cmd-i"]: 10 } as React.CSSProperties}
                >
                  + Chart generated &middot; Exportable
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── HOW IT WORKS ── */}
      <section className="py-20 sm:py-28 border-t border-border-subtle" id="how-it-works">
        <div className="max-w-6xl mx-auto px-6">
          <div className="cmd-reveal text-center mb-16">
            <h2 className="font-display text-3xl sm:text-4xl font-bold tracking-tight text-text-primary">
              From zero to insight in{" "}
              <span className="text-accent">30 seconds</span>
            </h2>
          </div>

          <div className="grid sm:grid-cols-3 gap-8">
            {STEPS.map((s, i) => (
              <div
                key={s.num}
                style={{ ["--cmd-i"]: i } as React.CSSProperties}
                className="cmd-reveal relative text-center sm:text-left"
              >
                <div className="flex items-center justify-center sm:justify-start mb-4">
                  <span className="w-9 h-9 rounded-lg bg-accent-muted text-accent font-mono text-sm font-semibold flex items-center justify-center">
                    {s.num}
                  </span>
                </div>
                <h3 className="text-xl font-semibold text-text-primary mb-2">
                  {s.title}
                </h3>
                <p className="text-sm text-text-secondary leading-relaxed">
                  {s.desc}
                </p>
                {i < STEPS.length - 1 && (
                  <div className="hidden sm:block absolute top-8 -right-4 text-border-default">
                    <svg width={24} height={24} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} aria-hidden="true">
                      <path d="M5 12h14M12 5l7 7-7 7" />
                    </svg>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── OPEN SOURCE ── */}
      <section className="py-20 sm:py-28 border-t border-border-subtle">
        <div className="max-w-6xl mx-auto px-6">
          <div className="cmd-reveal cmd-reveal-scale relative overflow-hidden bg-surface-1 border border-border-subtle rounded-2xl p-8 sm:p-12 text-center">
            <div
              aria-hidden="true"
              className="pointer-events-none absolute"
              style={{
                top: -120,
                left: "50%",
                width: 420,
                height: 280,
                transform: "translateX(-50%)",
              }}
            >
              <div
                className="cmd-glow"
                style={{
                  inset: 0,
                  width: "100%",
                  height: "100%",
                  background:
                    "color-mix(in srgb, var(--color-accent) 26%, transparent)",
                }}
              />
            </div>
            <div className="relative">
              <LogoMark size={48} className="mx-auto mb-6" />
              <h2 className="font-display text-2xl sm:text-3xl font-bold tracking-tight text-text-primary">
                Built in public, fully transparent
              </h2>
              <p className="mt-4 text-lg text-text-secondary max-w-lg mx-auto leading-relaxed text-pretty">
                The entire source is on GitHub under the MIT license.
              </p>
              <p className="mt-4 text-sm text-text-tertiary max-w-md mx-auto">
                Inspect exactly how your data is processed, contribute
                improvements, or self-host on your own infrastructure.
              </p>
              <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
                <a
                  href={GITHUB_URL}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="px-6 py-3 text-sm font-semibold text-white bg-accent hover:bg-accent-hover rounded-lg transition-colors inline-flex items-center gap-2"
                >
                  <GitHubIcon />
                  Star on GitHub
                </a>
                <Link
                  href="/login"
                  className="px-6 py-3 text-sm font-semibold text-text-primary border border-border-default hover:border-accent hover:text-accent rounded-lg transition-colors"
                >
                  Try it now
                </Link>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── FAQ ── */}
      <section className="py-20 sm:py-28 border-t border-border-subtle" id="faq">
        <div className="max-w-3xl mx-auto px-6">
          <div className="cmd-reveal text-center mb-12">
            <h2 className="font-display text-3xl sm:text-4xl font-bold tracking-tight text-text-primary">
              Questions, <span className="text-accent">answered</span>
            </h2>
          </div>
          <FaqAccordion items={LANDING_FAQS} />
          <p className="cmd-reveal mt-8 text-center text-sm text-text-tertiary">
            More questions? Visit{" "}
            <Link
              href="/support"
              className="text-accent hover:text-accent-hover transition-colors underline underline-offset-2"
            >
              Support
            </Link>{" "}
            or{" "}
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="text-accent hover:text-accent-hover transition-colors underline underline-offset-2"
            >
              ask on GitHub
            </a>
            .
          </p>
        </div>
      </section>

      {/* ── FINAL CTA ── */}
      <section className="py-20 sm:py-28 border-t border-border-subtle">
        <div className="cmd-reveal max-w-6xl mx-auto px-6 text-center">
          <h2 className="font-display text-3xl sm:text-4xl font-bold tracking-tight text-text-primary mb-4">
            Start exploring <span className="text-accent">your data</span> today
          </h2>
          <p className="text-text-secondary max-w-md mx-auto mb-10">
            No credit card. Deploy in minutes.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              href="/login"
              className="px-10 py-3.5 text-sm font-semibold text-white bg-accent hover:bg-accent-hover rounded-lg transition-colors"
            >
              Get Started Free
            </Link>
            <a
              href={GITHUB_URL}
              target="_blank"
              rel="noopener noreferrer"
              className="px-8 py-3.5 text-sm font-semibold text-text-primary border border-border-default hover:border-accent hover:text-accent rounded-lg transition-colors inline-flex items-center gap-2"
            >
              <GitHubIcon />
              Star on GitHub
            </a>
          </div>
        </div>
      </section>
    </>
  );
}
