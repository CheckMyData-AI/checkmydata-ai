import type { Metadata } from "next";
import Link from "next/link";
import { LogoMark } from "@/components/ui/Logo";
import { AuthRedirect } from "@/components/auth/AuthRedirect";

export const metadata: Metadata = {
  title: "CheckMyData.ai — Open-Source AI Database Agent",
  description:
    "Query your PostgreSQL, MySQL, ClickHouse, and MongoDB databases with natural language. Open-source, privacy-first, self-hostable AI database agent with data visualization.",
  openGraph: {
    title: "CheckMyData.ai — Open-Source AI Database Agent",
    description:
      "Query your databases with natural language. Open-source, privacy-first, self-hostable.",
    url: "https://checkmydata.ai",
    siteName: "CheckMyData.ai",
    images: [
      {
        url: "/og-image.png",
        width: 1200,
        height: 630,
        alt: "CheckMyData.ai — Open-source AI database agent",
      },
    ],
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "CheckMyData.ai — Open-Source AI Database Agent",
    description:
      "Query your databases with natural language. Open-source, privacy-first, self-hostable.",
    images: ["/og-image.png"],
  },
  alternates: { canonical: "https://checkmydata.ai" },
};

const FEATURES = [
  {
    icon: (
      <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
    ),
    title: "Natural Language Queries",
    desc: "Ask questions in plain English. The AI translates them into SQL, executes against your database, and returns results in real time.",
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
    desc: "Connect to PostgreSQL, MySQL, ClickHouse, and MongoDB. Direct connections or SSH tunnels — your choice.",
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
    desc: "Auto-generated charts, tables, and exportable formats. See your data, not just rows and columns.",
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
    desc: "Index your Git repositories. The AI understands your schema, models, and business logic for context-aware queries.",
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
    desc: "Run on your own infrastructure. Full control over your data, your keys, your deployment. Docker-ready.",
  },
  {
    icon: (
      <path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z" />
    ),
    title: "Privacy-First",
    desc: "Your database content never leaves your session. No telemetry, no tracking, no hidden data collection. Verify it in the source code.",
  },
] as const;

const STEPS = [
  {
    num: "01",
    title: "Connect your database",
    desc: "Add your PostgreSQL, MySQL, ClickHouse, or MongoDB connection. Credentials are encrypted at rest.",
  },
  {
    num: "02",
    title: "Ask questions in natural language",
    desc: "Type your question like you would ask a colleague. The AI generates and executes the right SQL query.",
  },
  {
    num: "03",
    title: "Get insights instantly",
    desc: "View results as tables, charts, and visualizations. Save queries, build dashboards, and share with your team.",
  },
] as const;

export default function LandingPage() {
  return (
    <>
      <AuthRedirect />
      {/* JSON-LD structured data */}
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
              "Open-source AI-powered database agent that lets you query PostgreSQL, MySQL, ClickHouse, and MongoDB with natural language.",
            url: "https://checkmydata.ai",
            downloadUrl: "https://github.com/ssheleg/checkmydata-ai",
            license: "https://opensource.org/licenses/MIT",
            offers: {
              "@type": "Offer",
              price: "0",
              priceCurrency: "USD",
            },
          }),
        }}
      />

      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,_var(--color-accent-muted)_0%,_transparent_50%)] pointer-events-none" />
        <div className="max-w-6xl mx-auto px-6 pt-24 pb-20 sm:pt-32 sm:pb-28 relative">
          <div className="max-w-3xl mx-auto text-center">
            <div className="inline-flex items-center gap-2 px-3 py-1.5 rounded-full border border-border-subtle bg-surface-1 text-xs text-text-secondary mb-8">
              <span className="w-2 h-2 rounded-full bg-success animate-pulse-dot" />
              Open Source &mdash; MIT License
            </div>

            <h1 className="text-4xl sm:text-5xl lg:text-6xl font-bold tracking-tight text-text-primary leading-[1.1]">
              AI database agent
              <br />
              <span className="text-accent">for your data</span>
            </h1>

            <p className="mt-6 text-lg sm:text-xl text-text-secondary max-w-2xl mx-auto leading-relaxed">
              Query PostgreSQL, MySQL, ClickHouse, and MongoDB with natural
              language. Understand your data through AI-powered analysis,
              visualization, and codebase context.
            </p>

            <div className="mt-10 flex flex-col sm:flex-row items-center justify-center gap-4">
              <Link
                href="/login"
                className="w-full sm:w-auto px-8 py-3 text-sm font-semibold text-white bg-accent hover:bg-accent-hover rounded-lg transition-colors text-center"
              >
                Get Started Free
              </Link>
              <a
                href="https://github.com/ssheleg/checkmydata-ai"
                target="_blank"
                rel="noopener noreferrer"
                className="w-full sm:w-auto px-8 py-3 text-sm font-semibold text-text-primary border border-border-default hover:border-accent hover:text-accent rounded-lg transition-colors text-center inline-flex items-center justify-center gap-2"
              >
                <svg
                  width={18}
                  height={18}
                  viewBox="0 0 24 24"
                  fill="currentColor"
                  aria-hidden="true"
                >
                  <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z" />
                </svg>
                View on GitHub
              </a>
            </div>

            <p className="mt-6 text-xs text-text-muted">
              No credit card required. Self-host or use our hosted version.
            </p>
          </div>
        </div>
      </section>

      {/* Features */}
      <section className="py-20 sm:py-28" id="features">
        <div className="max-w-6xl mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-text-primary">
              Everything you need to understand your data
            </h2>
            <p className="mt-4 text-text-secondary max-w-2xl mx-auto">
              A complete AI-powered toolkit for database exploration, analysis,
              and visualization.
            </p>
          </div>

          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {FEATURES.map((f) => (
              <div
                key={f.title}
                className="bg-surface-1 border border-border-subtle rounded-xl p-6 hover:border-accent/30 transition-colors group"
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
                <h3 className="text-base font-semibold text-text-primary mb-2">
                  {f.title}
                </h3>
                <p className="text-sm text-text-secondary leading-relaxed">
                  {f.desc}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* How it works */}
      <section className="py-20 sm:py-28 border-t border-border-subtle" id="how-it-works">
        <div className="max-w-6xl mx-auto px-6">
          <div className="text-center mb-16">
            <h2 className="text-3xl sm:text-4xl font-bold tracking-tight text-text-primary">
              How it works
            </h2>
            <p className="mt-4 text-text-secondary max-w-xl mx-auto">
              Three steps from database connection to actionable insights.
            </p>
          </div>

          <div className="grid sm:grid-cols-3 gap-8">
            {STEPS.map((s) => (
              <div key={s.num} className="relative">
                <div className="text-5xl font-bold text-accent/10 mb-4 font-mono">
                  {s.num}
                </div>
                <h3 className="text-lg font-semibold text-text-primary mb-2">
                  {s.title}
                </h3>
                <p className="text-sm text-text-secondary leading-relaxed">
                  {s.desc}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* Open Source CTA */}
      <section className="py-20 sm:py-28 border-t border-border-subtle">
        <div className="max-w-6xl mx-auto px-6">
          <div className="bg-surface-1 border border-border-subtle rounded-2xl p-8 sm:p-12 text-center relative overflow-hidden">
            <div className="absolute inset-0 bg-[radial-gradient(circle_at_center,_var(--color-accent-muted)_0%,_transparent_60%)] pointer-events-none" />
            <div className="relative">
              <LogoMark size={48} className="mx-auto mb-6" />
              <h2 className="text-2xl sm:text-3xl font-bold tracking-tight text-text-primary">
                100% Open Source
              </h2>
              <p className="mt-4 text-text-secondary max-w-lg mx-auto leading-relaxed">
                Every line of code is public. No hidden telemetry, no black
                boxes. Inspect how your data is processed, contribute
                improvements, or self-host on your own infrastructure.
              </p>
              <div className="mt-8 flex flex-col sm:flex-row items-center justify-center gap-4">
                <a
                  href="https://github.com/ssheleg/checkmydata-ai"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="px-6 py-3 text-sm font-semibold text-white bg-accent hover:bg-accent-hover rounded-lg transition-colors inline-flex items-center gap-2"
                >
                  <svg
                    width={18}
                    height={18}
                    viewBox="0 0 24 24"
                    fill="currentColor"
                    aria-hidden="true"
                  >
                    <path d="M12 0C5.37 0 0 5.37 0 12c0 5.31 3.435 9.795 8.205 11.385.6.105.825-.255.825-.57 0-.285-.015-1.23-.015-2.235-3.015.555-3.795-.735-4.035-1.41-.135-.345-.72-1.41-1.23-1.695-.42-.225-1.02-.78-.015-.795.945-.015 1.62.87 1.845 1.23 1.08 1.815 2.805 1.305 3.495.99.105-.78.42-1.305.765-1.605-2.67-.3-5.46-1.335-5.46-5.925 0-1.305.465-2.385 1.23-3.225-.12-.3-.54-1.53.12-3.18 0 0 1.005-.315 3.3 1.23.96-.27 1.98-.405 3-.405s2.04.135 3 .405c2.295-1.56 3.3-1.23 3.3-1.23.66 1.65.24 2.88.12 3.18.765.84 1.23 1.905 1.23 3.225 0 4.605-2.805 5.625-5.475 5.925.435.375.81 1.095.81 2.22 0 1.605-.015 2.895-.015 3.3 0 .315.225.69.825.57A12.02 12.02 0 0 0 24 12c0-6.63-5.37-12-12-12z" />
                  </svg>
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

      {/* Databases banner */}
      <section className="py-16 border-t border-border-subtle">
        <div className="max-w-6xl mx-auto px-6 text-center">
          <p className="text-xs text-text-muted uppercase tracking-wider mb-6">
            Supported databases
          </p>
          <div className="flex flex-wrap items-center justify-center gap-8 text-text-tertiary">
            {["PostgreSQL", "MySQL", "ClickHouse", "MongoDB"].map((db) => (
              <span key={db} className="text-sm font-mono font-medium">
                {db}
              </span>
            ))}
          </div>
        </div>
      </section>
    </>
  );
}
