import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Contact",
  description:
    "Get in touch with the CheckMyData.ai team. General inquiries, technical support, and community links.",
  openGraph: {
    title: "Contact | CheckMyData.ai",
    description:
      "Get in touch with the CheckMyData.ai team. General inquiries, technical support, and community links.",
    url: "https://checkmydata.ai/contact",
    siteName: "CheckMyData.ai",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: "Contact | CheckMyData.ai",
    description:
      "Get in touch with the CheckMyData.ai team. General inquiries, technical support, and community links.",
  },
  alternates: { canonical: "https://checkmydata.ai/contact" },
};

const CHANNELS = [
  {
    title: "General Inquiries",
    email: "contact@checkmydata.ai",
    desc: "For partnership opportunities, press, or general questions about CheckMyData.ai.",
  },
  {
    title: "Technical Support",
    email: "support@checkmydata.ai",
    desc: "Need help with setup, configuration, or troubleshooting? Our support team is here to assist.",
  },
] as const;

export default function ContactPage() {
  return (
    <article className="max-w-3xl mx-auto px-6 py-16 sm:py-24">
      <header className="space-y-4 pb-10 border-b border-border-subtle">
        <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-text-primary">
          Contact Us
        </h1>
        <p className="text-lg text-text-secondary leading-relaxed">
          We would love to hear from you. Choose the channel that best fits
          your needs.
        </p>
      </header>

      <div className="mt-12 grid gap-6">
        {CHANNELS.map((ch) => (
          <div
            key={ch.email}
            className="bg-surface-1 border border-border-subtle rounded-xl p-6 space-y-3"
          >
            <h2 className="text-lg font-semibold text-text-primary">
              {ch.title}
            </h2>
            <p className="text-sm text-text-secondary leading-relaxed">
              {ch.desc}
            </p>
            <a
              href={`mailto:${ch.email}`}
              className="inline-flex items-center gap-2 text-sm text-accent hover:text-accent-hover transition-colors font-medium"
            >
              <svg
                width={16}
                height={16}
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
                <path d="M22 6l-10 7L2 6" />
              </svg>
              {ch.email}
            </a>
          </div>
        ))}
      </div>

      <section className="mt-12 space-y-6">
        <h2 className="text-xl font-semibold text-text-primary">
          Community &amp; Open Source
        </h2>
        <p className="text-sm text-text-secondary leading-relaxed">
          CheckMyData.ai is an open-source project. The best way to report
          bugs, request features, or contribute code is through GitHub.
        </p>
        <div className="grid sm:grid-cols-2 gap-4">
          <a
            href="https://github.com/CheckMyData-AI/checkmydata-ai/issues"
            target="_blank"
            rel="noopener noreferrer"
            className="bg-surface-1 border border-border-subtle rounded-xl p-5 hover:border-accent/30 transition-colors block"
          >
            <h3 className="text-sm font-semibold text-text-primary mb-1">
              Bug Reports &amp; Features
            </h3>
            <p className="text-xs text-text-tertiary">
              Open an issue on GitHub Issues
            </p>
          </a>
          <a
            href="https://github.com/CheckMyData-AI/checkmydata-ai/discussions"
            target="_blank"
            rel="noopener noreferrer"
            className="bg-surface-1 border border-border-subtle rounded-xl p-5 hover:border-accent/30 transition-colors block"
          >
            <h3 className="text-sm font-semibold text-text-primary mb-1">
              Discussions &amp; Q&amp;A
            </h3>
            <p className="text-xs text-text-tertiary">
              Join the conversation on GitHub Discussions
            </p>
          </a>
        </div>
      </section>

      <section className="mt-12 pt-8 border-t border-border-subtle">
        <p className="text-sm text-text-tertiary">
          Looking for help with setup or technical issues? Visit our{" "}
          <Link
            href="/support"
            className="text-accent hover:text-accent-hover transition-colors underline underline-offset-2"
          >
            Support page
          </Link>{" "}
          for FAQs and troubleshooting guides.
        </p>
      </section>
    </article>
  );
}
