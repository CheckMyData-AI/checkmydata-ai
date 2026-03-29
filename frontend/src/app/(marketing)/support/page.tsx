import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Support | CheckMyData.ai",
  description:
    "Get help with CheckMyData.ai — FAQs, troubleshooting, and support channels for the open-source AI database agent.",
  openGraph: {
    title: "Support | CheckMyData.ai",
    description:
      "Get help with CheckMyData.ai — FAQs, troubleshooting, and support channels.",
    url: "https://checkmydata.ai/support",
    siteName: "CheckMyData.ai",
    type: "website",
  },
  alternates: { canonical: "https://checkmydata.ai/support" },
};

const FAQS = [
  {
    q: "What databases does CheckMyData.ai support?",
    a: "Currently we support PostgreSQL, MySQL, ClickHouse, and MongoDB. You can connect via direct connections or SSH tunnels.",
  },
  {
    q: "Is my data safe?",
    a: "Yes. Query results are transient — they exist only in your browser session and are never stored on our servers. Database credentials are encrypted at rest. The entire codebase is open source so you can verify every claim.",
  },
  {
    q: "Can I self-host CheckMyData.ai?",
    a: "Absolutely. CheckMyData.ai is designed for self-hosting. Clone the repository, run the Docker setup, and you have full control over your deployment. See the installation guide on GitHub.",
  },
  {
    q: "Which LLM providers are supported?",
    a: "We support OpenAI, Anthropic, and OpenRouter out of the box. The multi-provider routing system automatically falls back to alternative providers if one is unavailable.",
  },
  {
    q: "How do I connect a Git repository?",
    a: "In the sidebar, navigate to your project settings and add a Git repository URL with an SSH key. The AI agent will index structural metadata (file names, entity names, function signatures) to provide context-aware query suggestions.",
  },
  {
    q: "Is there a usage limit?",
    a: "For the hosted version, limits depend on the LLM provider quotas configured in your deployment. For self-hosted instances, you control the limits entirely through your own API keys.",
  },
  {
    q: "How do I report a bug?",
    a: "Open an issue on our GitHub repository. Please include steps to reproduce, expected behavior, and any error messages you see.",
  },
] as const;

export default function SupportPage() {
  return (
    <article className="max-w-3xl mx-auto px-6 py-16 sm:py-24">
      <header className="space-y-4 pb-10 border-b border-border-subtle">
        <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-text-primary">
          Support
        </h1>
        <p className="text-lg text-text-secondary leading-relaxed">
          Find answers to common questions or reach out to our team for help.
        </p>
      </header>

      {/* Contact channels */}
      <section className="mt-12 space-y-6">
        <h2 className="text-xl font-semibold text-text-primary">
          Get in Touch
        </h2>
        <div className="grid sm:grid-cols-2 gap-4">
          <div className="bg-surface-1 border border-border-subtle rounded-xl p-5 space-y-2">
            <h3 className="text-sm font-semibold text-text-primary">
              Email Support
            </h3>
            <a
              href="mailto:support@checkmydata.ai"
              className="text-sm text-accent hover:text-accent-hover transition-colors font-medium"
            >
              support@checkmydata.ai
            </a>
            <p className="text-xs text-text-tertiary">
              For technical issues, setup help, and troubleshooting.
            </p>
          </div>
          <a
            href="https://github.com/ssheleg/checkmydata-ai/issues"
            target="_blank"
            rel="noopener noreferrer"
            className="bg-surface-1 border border-border-subtle rounded-xl p-5 space-y-2 hover:border-accent/30 transition-colors block"
          >
            <h3 className="text-sm font-semibold text-text-primary">
              GitHub Issues
            </h3>
            <p className="text-sm text-accent font-medium">
              github.com/ssheleg/checkmydata-ai/issues
            </p>
            <p className="text-xs text-text-tertiary">
              For bug reports, feature requests, and code contributions.
            </p>
          </a>
        </div>
      </section>

      {/* Documentation links */}
      <section className="mt-12 space-y-6">
        <h2 className="text-xl font-semibold text-text-primary">
          Documentation
        </h2>
        <div className="grid sm:grid-cols-2 gap-4">
          {[
            {
              title: "Installation Guide",
              desc: "Step-by-step setup for local and Docker deployments.",
              href: "https://github.com/ssheleg/checkmydata-ai/blob/main/INSTALLATION.md",
            },
            {
              title: "Usage Guide",
              desc: "How to connect databases, ask questions, and visualize data.",
              href: "https://github.com/ssheleg/checkmydata-ai/blob/main/USAGE.md",
            },
            {
              title: "API Reference",
              desc: "Full REST API documentation for developers.",
              href: "https://github.com/ssheleg/checkmydata-ai/blob/main/API.md",
            },
            {
              title: "FAQ",
              desc: "Common questions and troubleshooting tips.",
              href: "https://github.com/ssheleg/checkmydata-ai/blob/main/FAQ.md",
            },
          ].map((doc) => (
            <a
              key={doc.title}
              href={doc.href}
              target="_blank"
              rel="noopener noreferrer"
              className="bg-surface-1 border border-border-subtle rounded-xl p-5 hover:border-accent/30 transition-colors block"
            >
              <h3 className="text-sm font-semibold text-text-primary mb-1">
                {doc.title}
              </h3>
              <p className="text-xs text-text-tertiary">{doc.desc}</p>
            </a>
          ))}
        </div>
      </section>

      {/* FAQ */}
      <section className="mt-12 space-y-6">
        <h2 className="text-xl font-semibold text-text-primary">
          Frequently Asked Questions
        </h2>
        <div className="space-y-4">
          {FAQS.map((faq) => (
            <details
              key={faq.q}
              className="group bg-surface-1 border border-border-subtle rounded-xl"
            >
              <summary className="cursor-pointer p-5 text-sm font-semibold text-text-primary list-none flex items-center justify-between gap-4">
                {faq.q}
                <svg
                  width={16}
                  height={16}
                  viewBox="0 0 24 24"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth={2}
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  className="text-text-muted shrink-0 transition-transform group-open:rotate-180"
                  aria-hidden="true"
                >
                  <path d="M6 9l6 6 6-6" />
                </svg>
              </summary>
              <div className="px-5 pb-5 text-sm text-text-secondary leading-relaxed">
                {faq.a}
              </div>
            </details>
          ))}
        </div>
      </section>

      <section className="mt-12 pt-8 border-t border-border-subtle">
        <p className="text-sm text-text-tertiary">
          For general inquiries, visit our{" "}
          <Link
            href="/contact"
            className="text-accent hover:text-accent-hover transition-colors underline underline-offset-2"
          >
            Contact page
          </Link>
          . For legal matters, see our{" "}
          <Link
            href="/terms"
            className="text-accent hover:text-accent-hover transition-colors underline underline-offset-2"
          >
            Terms of Service
          </Link>{" "}
          and{" "}
          <Link
            href="/privacy"
            className="text-accent hover:text-accent-hover transition-colors underline underline-offset-2"
          >
            Privacy Policy
          </Link>
          .
        </p>
      </section>
    </article>
  );
}
