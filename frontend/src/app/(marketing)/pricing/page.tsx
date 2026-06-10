import type { Metadata } from "next";
import { PricingTable } from "@/components/marketing/PricingTable";

export const metadata: Metadata = {
  title: "Pricing",
  description:
    "Simple, transparent pricing for CheckMyData.ai. Start free, upgrade when your team needs more connections, projects, and LLM capacity.",
  openGraph: {
    title: "Pricing | CheckMyData.ai",
    description:
      "Start free, upgrade when your team needs more connections, projects, and LLM capacity.",
    url: "https://checkmydata.ai/pricing",
    siteName: "CheckMyData.ai",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: "Pricing | CheckMyData.ai",
    description:
      "Start free, upgrade when your team needs more connections, projects, and LLM capacity.",
  },
  alternates: { canonical: "https://checkmydata.ai/pricing" },
};

const FAQ = [
  {
    q: "Can I use CheckMyData for free?",
    a: "Yes — the Free plan includes one project and one database connection, forever. You can also self-host the open-source version with no plan limits.",
  },
  {
    q: "What counts against the token limit?",
    a: "LLM tokens consumed by the agent while answering your questions (planning, SQL generation, validation, and summaries). Query results themselves are not metered.",
  },
  {
    q: "Can I cancel anytime?",
    a: "Yes. Manage or cancel your subscription from the billing portal — you keep paid features until the end of the billing period.",
  },
  {
    q: "Do paid plans have a trial?",
    a: "Pro and Team include a 14-day free trial. You won't be charged until the trial ends, and you can cancel before that.",
  },
] as const;

export default function PricingPage() {
  return (
    <article className="max-w-5xl mx-auto px-6 py-16 sm:py-24">
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify({
            "@context": "https://schema.org",
            "@type": "BreadcrumbList",
            itemListElement: [
              { "@type": "ListItem", position: 1, name: "Home", item: "https://checkmydata.ai" },
              {
                "@type": "ListItem",
                position: 2,
                name: "Pricing",
                item: "https://checkmydata.ai/pricing",
              },
            ],
          }),
        }}
      />

      <header className="text-center">
        <h1 className="font-display text-4xl sm:text-5xl font-bold tracking-tight text-text-primary text-balance">
          Simple, transparent pricing
        </h1>
        <p className="mt-4 text-lg text-text-secondary max-w-2xl mx-auto text-pretty">
          Start free. Upgrade when your team needs more connections, projects, and LLM
          capacity. Self-hosting the open-source version is always free.
        </p>
      </header>

      <PricingTable />

      <section className="mt-20 max-w-3xl mx-auto" aria-labelledby="pricing-faq">
        <h2 id="pricing-faq" className="text-lg font-semibold text-text-primary text-center">
          Frequently asked questions
        </h2>
        <dl className="mt-8 space-y-6">
          {FAQ.map((item) => (
            <div
              key={item.q}
              className="bg-surface-1 rounded-xl border border-border-subtle p-5"
            >
              <dt className="text-sm font-semibold text-text-primary">{item.q}</dt>
              <dd className="mt-2 text-sm text-text-secondary leading-relaxed">{item.a}</dd>
            </div>
          ))}
        </dl>
      </section>
    </article>
  );
}
