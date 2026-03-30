import type React from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { LogoMark } from "@/components/ui/Logo";
import { AuthRedirect } from "@/components/auth/AuthRedirect";

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
    tagline: "Talk to your database like a teammate",
    desc: "No SQL? No problem. We generate, execute, and explain queries for you.",
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
    tagline: "All your data, one interface",
    desc: "PostgreSQL, MySQL, ClickHouse, MongoDB. Connect directly or via SSH.",
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
    tagline: "See patterns instantly",
    desc: "Charts, tables, exports — auto-generated. No dashboard setup needed.",
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
    tagline: "Understands your code, not just your data",
    desc: "We index your repo. Queries actually match your business logic.",
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
    tagline: "Your data stays yours",
    desc: "Deploy anywhere. Full control. No lock-in. Docker-ready.",
  },
  {
    icon: (
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    ),
    title: "Privacy-First",
    tagline: "Zero data leakage. Period.",
    desc: "No tracking. No telemetry. Verify everything in the code.",
  },
] as { icon: React.ReactNode; title: string; tagline: string; desc: string; highlight?: boolean }[];

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
    desc: "Queries, charts, insights — instantly.",
  },
] as const;

export default function LandingPage() {
  return (
    <>
      <AuthRedirect />
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
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--color-accent-muted)_0%,_transparent_50%)] pointer-events-none" />
        <div className="max-w-6xl mx-auto px-6 pt-24 pb-20 sm:pt-32 sm:pb-28 relative">
          <div className="max-w-3xl mx-auto text-center">
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-border-subtle bg-surface-1 text-xs text-text-secondary mb-8">
              <span className="w-2 h-2 rounded-full bg-success animate-pulse-dot" />
              Open Source &mdash; MIT License
            </div>

            <p className="text-sm sm:text-base text-accent font-semibold tracking-wide uppercase mb-4">
              Like ChatGPT, but for your database
            </p>

            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight text-text-primary leading-[1.1]">
              Your data already
              <br />
              has answers.
              <br />
              <span className="text-text-tertiary">You just don&rsquo;t know how to ask.</span>
            </h1>

            <p className="mt-8 text-lg sm:text-xl text-text-secondary max-w-2xl mx-auto leading-relaxed">
              Query any database in plain English.
              <br className="hidden sm:block" />{" "}
              Get insights, charts, and explanations instantly.
            </p>

            <div className="mt-4 flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-sm text-text-tertiary font-mono">
              <span>PostgreSQL</span>
              <span className="text-border-default">&middot;</span>
              <span>MySQL</span>
              <span className="text-border-default">&middot;</span>
              <span>ClickHouse</span>
              <span className="text-border-default">&middot;</span>
              <span>MongoDB</span>
            </div>

            <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
              <Link
                href="/login"
                className="w-full sm:w-auto px-8 py-3.5 text-sm font-semibold text-white bg-accent hover:bg-accent-hover rounded-lg transition-colors text-center shadow-[0_0_20px_var(--color-accent-muted)]"
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

            <p className="mt-5 text-xs text-text-tertiary">
              No credit card. Deploy in minutes. Self-host or use hosted.
            </p>
          </div>
        </div>
      </section>

      {/* ── SOCIAL PROOF BAR ── */}
      <section className="border-y border-border-subtle bg-surface-1/50">
        <div className="max-w-6xl mx-auto px-6 py-6 flex flex-wrap items-center justify-center gap-x-10 gap-y-3 text-sm text-text-secondary">
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
          <div className="text-center mb-6">
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-text-primary">
              Everything you need to actually
              <br className="hidden sm:block" />{" "}
              <span className="text-accent">understand your data</span>
            </h2>
          </div>
          <p className="text-center text-text-secondary max-w-xl mx-auto mb-16 leading-relaxed">
            Not just queries.
            <br />
            Real insights, context, and decisions.
          </p>

          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {FEATURES.map((f) => (
              <div
                key={f.title}
                className={`bg-surface-1 border rounded-xl p-6 transition-colors group ${
                  f.highlight
                    ? "border-accent/40 ring-1 ring-accent/10"
                    : "border-border-subtle hover:border-accent/30"
                }`}
              >
                <div className="w-10 h-10 rounded-lg bg-accent-muted flex items-center justify-center mb-4 group-hover:bg-accent/20 transition-colors">
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
                <h3 className="text-base font-semibold text-text-primary mb-1">
                  {f.title}
                </h3>
                <p className="text-sm font-medium text-accent/80 mb-2">
                  {f.tagline}
                </p>
                <p className="text-sm text-text-secondary leading-relaxed">
                  {f.desc}
                </p>
                {f.highlight && (
                  <span className="mt-3 inline-block text-[10px] font-semibold text-accent uppercase tracking-wider">
                    Killer feature
                  </span>
                )}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── USE CASES ── */}
      <section className="py-20 sm:py-28 border-t border-border-subtle" id="use-cases">
        <div className="max-w-6xl mx-auto px-6">
          <div className="grid lg:grid-cols-2 gap-12 items-center">
            <div>
              <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-text-primary mb-4">
                What can you do with it?
              </h2>
              <p className="text-text-secondary leading-relaxed mb-8">
                Ask questions like a human.
                <br />
                Get answers like a data scientist.
              </p>
              <ul className="space-y-4">
                {USE_CASES.map((uc) => (
                  <li
                    key={uc}
                    className="flex items-start gap-3 text-text-primary"
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

            <div className="bg-surface-1 border border-border-subtle rounded-xl p-6 sm:p-8 font-mono text-sm">
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
          <div className="text-center mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-text-primary">
              From zero to insight in <span className="text-accent">30 seconds</span>
            </h2>
          </div>

          <div className="grid sm:grid-cols-3 gap-8">
            {STEPS.map((s, i) => (
              <div key={s.num} className="relative text-center sm:text-left">
                <div className="text-6xl font-bold text-accent/10 mb-3 font-mono">
                  {s.num}
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
          <div className="bg-surface-1 border border-border-subtle rounded-2xl p-8 sm:p-12 text-center relative overflow-hidden">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,_var(--color-accent-muted)_0%,_transparent_60%)] pointer-events-none" />
            <div className="relative">
              <LogoMark size={48} className="mx-auto mb-6" />
              <h2 className="text-2xl sm:text-3xl font-bold tracking-tight text-text-primary">
                Built in public. Fully transparent.
              </h2>
              <p className="mt-4 text-lg text-text-secondary max-w-lg mx-auto leading-relaxed">
                No black boxes.<br />
                No hidden logic.<br />
                No bullshit.
              </p>
              <p className="mt-4 text-sm text-text-tertiary max-w-md mx-auto">
                Every line of code is public. Inspect how your data is processed,
                contribute improvements, or self-host on your own infrastructure.
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
        <div className="max-w-6xl mx-auto px-6 text-center">
          <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-text-primary mb-4">
            Start exploring your data today
          </h2>
          <p className="text-text-secondary max-w-md mx-auto mb-10">
            No credit card. Deploy in minutes.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              href="/login"
              className="px-10 py-3.5 text-sm font-semibold text-white bg-accent hover:bg-accent-hover rounded-lg transition-colors shadow-[0_0_20px_var(--color-accent-muted)]"
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
