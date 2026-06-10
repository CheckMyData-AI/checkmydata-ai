import type React from "react";
import type { Metadata } from "next";
import Link from "next/link";
import { CinematicEngine } from "@/components/marketing/CinematicEngine";

export const metadata: Metadata = {
  title: "About",
  description:
    "Learn about CheckMyData.ai — the open-source AI database agent that reads your schema and codebase as context to turn plain-English questions into correct SQL.",
  openGraph: {
    title: "About | CheckMyData.ai",
    description:
      "The open-source AI database agent that understands your schema and codebase, so plain-English questions become correct, trustworthy SQL.",
    url: "https://checkmydata.ai/about",
    siteName: "CheckMyData.ai",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: "About | CheckMyData.ai",
    description:
      "The open-source AI database agent that understands your schema and codebase, so plain-English questions become correct, trustworthy SQL.",
  },
  alternates: { canonical: "https://checkmydata.ai/about" },
};

const TECH_STACK = [
  { category: "Frontend", items: "Next.js 15, React 19, Tailwind CSS 4, Zustand, Chart.js" },
  { category: "Backend", items: "Python, FastAPI, SQLAlchemy, Alembic" },
  { category: "AI / LLM", items: "OpenAI, Anthropic, OpenRouter — multi-provider routing with fallback" },
  { category: "Databases", items: "PostgreSQL, MySQL, ClickHouse, MongoDB — query via natural language" },
  { category: "Storage", items: "SQLite (app data), ChromaDB (vector embeddings)" },
  { category: "Infrastructure", items: "Docker, standalone deployment, SSH tunneling" },
] as const;

export default function AboutPage() {
  return (
    <article className="max-w-3xl mx-auto px-6 py-16 sm:py-24">
      <CinematicEngine />
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify({
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            itemListElement: [
              {
                "@type": "ListItem",
                position: 1,
                name: "Home",
                item: "https://checkmydata.ai",
              },
              {
                "@type": "ListItem",
                position: 2,
                name: "About",
                item: "https://checkmydata.ai/about",
              },
            ],
          }),
        }}
      />
      <header className="space-y-4 pb-10 border-b border-border-subtle">
        <h1 className="cmd-reveal font-display text-3xl sm:text-4xl font-bold tracking-tight text-text-primary">
          About CheckMyData.ai
        </h1>
        <p className="cmd-reveal text-lg text-text-secondary leading-relaxed">
          An open-source AI database agent that reads your schema and codebase as
          context — so plain-English questions become correct, trustworthy SQL
          for developers and data teams.
        </p>
      </header>

      <section className="mt-12 space-y-6">
        <h2 className="cmd-reveal font-display text-xl font-semibold text-text-primary">Our Mission</h2>
        <p className="text-sm text-text-secondary leading-relaxed">
          We believe the hard part of working with data isn&rsquo;t writing SQL —
          it&rsquo;s knowing the context to query it correctly. CheckMyData.ai
          captures that context — your schema, your codebase, your conventions —
          and learns it over time, so anyone on the team can ask a question and
          trust the answer.
        </p>
        <p className="text-sm text-text-secondary leading-relaxed">
          As an open-source project, we are committed to full transparency.
          There are no hidden data-collection mechanisms, no proprietary black
          boxes, and no vendor lock-in. You own your data, your queries, and
          your deployment.
        </p>
      </section>

      <section className="mt-12 space-y-6">
        <h2 className="cmd-reveal font-display text-xl font-semibold text-text-primary">
          How It Works
        </h2>
        <div className="space-y-4 text-sm text-text-secondary leading-relaxed">
          <p>
            CheckMyData.ai connects to your existing databases — PostgreSQL,
            MySQL, ClickHouse, or MongoDB — via direct connections or SSH
            tunnels. You ask questions in plain English, and the AI agent
            translates them into SQL, executes the query against your database,
            and returns the results with auto-generated visualizations.
          </p>
          <p>
            The agent can also index your Git repositories to understand your
            codebase context — models, schemas, and business logic — so it
            gives you smarter, more relevant answers.
          </p>
          <p>
            Query results are transient. They exist only in your browser
            session and are never stored on our servers. Your database
            credentials are encrypted at rest and decrypted only at connection
            time.
          </p>
        </div>
      </section>

      <section className="mt-12 space-y-6">
        <h2 className="cmd-reveal font-display text-xl font-semibold text-text-primary">
          Technology Stack
        </h2>
        <div className="grid gap-4">
          {TECH_STACK.map((row, i) => (
            <div
              key={row.category}
              className="cmd-reveal bg-surface-1 border border-border-subtle rounded-xl p-4"
              style={{ ["--cmd-i"]: i } as React.CSSProperties}
            >
              <h3 className="text-sm font-semibold text-text-primary mb-1">
                {row.category}
              </h3>
              <p className="text-xs text-text-secondary">{row.items}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="mt-12 space-y-6">
        <h2 className="cmd-reveal font-display text-xl font-semibold text-text-primary">
          Open Source
        </h2>
        <p className="text-sm text-text-secondary leading-relaxed">
          CheckMyData.ai is released under the MIT License. The entire codebase
          is publicly available on GitHub. We welcome contributions,
          bug reports, and feature requests from the community.
        </p>
        <div className="cmd-reveal cmd-reveal-scale flex flex-col sm:flex-row gap-4">
          <a
            href="https://github.com/CheckMyData-AI/checkmydata-ai"
            target="_blank"
            rel="noopener noreferrer"
            className="px-5 py-2.5 text-sm font-semibold text-white bg-accent hover:bg-accent-hover rounded-lg transition-colors text-center"
          >
            View on GitHub
          </a>
          <Link
            href="/login"
            className="px-5 py-2.5 text-sm font-semibold text-text-primary border border-border-default hover:border-accent hover:text-accent rounded-lg transition-colors text-center"
          >
            Get Started
          </Link>
        </div>
      </section>

      <section className="mt-12 space-y-4">
        <h2 className="cmd-reveal font-display text-xl font-semibold text-text-primary">Contact</h2>
        <p className="text-sm text-text-secondary leading-relaxed">
          Have questions or want to get in touch? Reach out at{" "}
          <a
            href="mailto:contact@checkmydata.ai"
            className="text-accent hover:text-accent-hover transition-colors underline underline-offset-2"
          >
            contact@checkmydata.ai
          </a>{" "}
          or visit our{" "}
          <Link
            href="/contact"
            className="text-accent hover:text-accent-hover transition-colors underline underline-offset-2"
          >
            contact page
          </Link>
          .
        </p>
      </section>
    </article>
  );
}
