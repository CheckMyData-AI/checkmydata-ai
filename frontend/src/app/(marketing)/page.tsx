import type React from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { LogoMark } from "@/components/ui/Logo";
import { AuthRedirect } from "@/components/auth/AuthRedirect";
import { CinematicEngine } from "@/components/marketing/CinematicEngine";
import { SchemaGraph } from "@/components/marketing/SchemaGraph";

export const metadata: Metadata = {
  title: "CheckMyData.ai — AI Analyst for Your Database",
  description:
    "Like ChatGPT, but for your database. Query PostgreSQL, MySQL, ClickHouse, and MongoDB in plain English. Get insights, charts, and explanations instantly. Open-source, self-hostable, privacy-first.",
  openGraph: {
    title: "CheckMyData.ai — AI Analyst for Your Database",
    description:
      "Your data already has answers. Query any database in plain English. Open-source, self-hostable, privacy-first.",
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
      "Your data already has answers. Query any database in plain English. Open-source & privacy-first.",
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
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    ),
    title: "Natural Language Queries",
    desc: "Ask in plain English and get generated SQL, results, and an explanation of what each query does.",
  },
  {
    icon: (
      <>
        <ellipse cx="12" cy="5" rx="9" ry="3" />
        <path d="M3 5v14c0 1.7 4 3 9 3s9-1.3 9-3V5" />
        <path d="M3 12c0 1.7 4 3 9 3s9-1.3 9-3" />
      </>
    ),
    title: "Multi-Database Support",
    desc: "Connect PostgreSQL, MySQL, ClickHouse, and MongoDB directly or through an SSH tunnel.",
  },
  {
    icon: (
      <>
        <line x1="18" y1="20" x2="18" y2="10" />
        <line x1="12" y1="20" x2="12" y2="4" />
        <line x1="6" y1="20" x2="6" y2="14" />
      </>
    ),
    title: "Data Visualization",
    desc: "Charts, tables, and exports are generated automatically, with no dashboard setup required.",
  },
  {
    icon: (
      <>
        <path d="M6 3v12" />
        <circle cx="18" cy="6" r="3" />
        <circle cx="6" cy="18" r="3" />
        <path d="M18 9a9 9 0 0 1-9 9" />
      </>
    ),
    title: "Codebase Knowledge",
    desc: "It indexes your repository, so answers reflect your actual business logic, not just raw table names. This context is what separates a useful answer from a misleading one.",
    highlight: true,
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
    title: "Self-Hostable",
    desc: "Deploy anywhere with Docker and keep full control of your environment, with no vendor lock-in.",
  },
  {
    icon: (
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    ),
    title: "Privacy-First",
    desc: "No tracking and no telemetry. You can verify exactly how your data is handled in the source code.",
  },
] as { icon: React.ReactNode; title: string; desc: string; highlight?: boolean }[];

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

export default function LandingPage() {
  return (
    <>
      <AuthRedirect />
      <CinematicEngine />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify({
            "@context": "https://schema.org",
            "@type": "SoftwareApplication",
            name: "CheckMyData.ai",
            applicationCategory: "DeveloperApplication",
            operatingSystem: "Web, Docker, Linux, macOS",
            description:
              "Open-source AI analyst for your database. Query PostgreSQL, MySQL, ClickHouse, and MongoDB with natural language. Get insights, charts, and explanations instantly.",
            url: "https://checkmydata.ai",
            downloadUrl: GITHUB_URL,
            license: "https://opensource.org/licenses/MIT",
            offers: {
              "@type": "Offer",
              price: "0",
              priceCurrency: "USD",
            },
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
              className="cmd-reveal text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight text-text-primary leading-[1.1] text-balance"
              style={{ ["--cmd-i"]: 2 } as React.CSSProperties}
            >
              Your data already
              <br />
              has answers.
              <br />
              <span className="text-text-tertiary">You just don&rsquo;t know how to ask.</span>
            </h1>

            <p
              className="cmd-reveal mt-8 text-lg sm:text-xl text-text-secondary max-w-2xl mx-auto leading-relaxed text-pretty"
              style={{ ["--cmd-i"]: 3 } as React.CSSProperties}
            >
              Query any database in plain English. Get insights, charts, and
              explanations instantly.
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

          {/* Showcase — the intelligence core rises into view on scroll */}
          <div
            className="cmd-reveal cmd-reveal-rise mt-16 sm:mt-20 max-w-4xl mx-auto"
            style={{ ["--cmd-i"]: 7 } as React.CSSProperties}
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
      </section>

      {/* ── SOCIAL PROOF BAR ── */}
      <section className="border-y border-border-subtle bg-surface-1/50">
        <div className="cmd-reveal max-w-6xl mx-auto px-6 py-6 flex flex-wrap items-center justify-center gap-x-10 gap-y-3 text-sm text-text-secondary">
          <span className="inline-flex items-center gap-2">
            <svg width={16} height={16} viewBox="0 0 24 24" fill="currentColor" className="text-warning" aria-hidden="true">
              <path d="M12 2l3.09 6.26L22 9.27l-5 4.87 1.18 6.88L12 17.77l-6.18 3.25L7 14.14 2 9.27l6.91-1.01L12 2z" />
            </svg>
            Open-source community growing fast
          </span>
          <span className="text-border-default hidden sm:inline">&middot;</span>
          <span>Used by data teams &amp; founders</span>
          <span className="text-border-default hidden sm:inline">&middot;</span>
          <span>Privacy-first architecture</span>
        </div>
      </section>

      {/* ── VALUE SECTION ── */}
      <section className="py-20 sm:py-28" id="features">
        <div className="max-w-6xl mx-auto px-6">
          <div className="cmd-reveal text-center mb-6">
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-text-primary">
              Everything you need to actually
              <br className="hidden sm:block" />{" "}
              <span className="cmd-shimmer-text">understand your data</span>
            </h2>
          </div>
          <p
            className="cmd-reveal text-center text-text-secondary max-w-xl mx-auto mb-16 leading-relaxed text-pretty"
            style={{ ["--cmd-i"]: 1 } as React.CSSProperties}
          >
            Readable SQL, exportable charts, and plain-English explanations of
            what the numbers actually mean.
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
                        Most loved feature
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
              <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-text-primary mb-4">
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
                <p>
                  <span className="text-text-muted">you:</span>{" "}
                  <span className="text-text-primary">Why did revenue drop last week?</span>
                </p>
                <p>
                  <span className="text-text-muted">ai:</span>{" "}
                  <span className="text-accent">Analyzing orders table...</span>
                </p>
                <p className="text-text-tertiary text-xs pl-4 border-l border-border-subtle">
                  SELECT date, SUM(amount) FROM orders
                  <br />
                  WHERE date &gt;= &apos;2026-03-17&apos;
                  <br />
                  GROUP BY date ORDER BY date
                </p>
                <p>
                  <span className="text-text-muted">ai:</span>{" "}
                  Revenue dropped 23% on March 20.
                  <br />
                  <span className="text-text-tertiary">
                    Root cause: payment gateway timeout affected 142 orders.
                  </span>
                </p>
                <p className="text-success text-xs">
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
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-text-primary">
              From zero to insight in{" "}
              <span className="cmd-shimmer-text">30 seconds</span>
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
              <h2 className="text-2xl sm:text-3xl font-bold tracking-tight text-text-primary">
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

      {/* ── FINAL CTA ── */}
      <section className="py-20 sm:py-28 border-t border-border-subtle">
        <div className="cmd-reveal max-w-6xl mx-auto px-6 text-center">
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-text-primary mb-4">
            Start exploring <span className="cmd-shimmer-text">your data</span> today
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
