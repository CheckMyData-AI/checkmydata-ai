import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Terms of Service",
  description:
    "Terms of Service for CheckMyData.ai — an open-source AI-powered database query agent.",
  openGraph: {
    title: "Terms of Service | CheckMyData.ai",
    description:
      "Terms of Service for CheckMyData.ai — an open-source AI-powered database query agent.",
    url: "https://checkmydata.ai/terms",
    siteName: "CheckMyData.ai",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: "Terms of Service | CheckMyData.ai",
    description:
      "Terms of Service for CheckMyData.ai — an open-source AI-powered database query agent.",
  },
  alternates: { canonical: "https://checkmydata.ai/terms" },
};

const LAST_UPDATED = "March 19, 2026";

export default function TermsPage() {
  return (
    <article className="space-y-10">
      {/* Page title */}
      <header className="space-y-3 pb-8 border-b border-border-subtle">
        <h1 className="text-2xl font-bold tracking-tight">
          Terms of Service
        </h1>
        <p className="text-sm text-text-tertiary">
          Last updated: {LAST_UPDATED}
        </p>
      </header>

      {/* 1. Acceptance */}
      <Section id="acceptance" title="1. Acceptance of Terms">
        <p>
          By accessing or using CheckMyData.ai (the &ldquo;Service&rdquo;),
          whether through our hosted instance or a self-hosted deployment, you
          agree to be bound by these Terms of Service (the
          &ldquo;Terms&rdquo;). If you do not agree with any part of these
          Terms, you must not use the Service.
        </p>
        <p>
          These Terms constitute a legally binding agreement between you
          (&ldquo;User,&rdquo; &ldquo;you&rdquo;) and the operators of
          CheckMyData.ai (&ldquo;we,&rdquo; &ldquo;us,&rdquo;
          &ldquo;our&rdquo;).
        </p>
      </Section>

      {/* 2. Description of Service */}
      <Section id="service" title="2. Description of Service">
        <p>
          CheckMyData.ai is an <strong>open-source</strong>, AI-powered
          database query agent. The Service enables you to:
        </p>
        <ul>
          <li>
            Connect to your own databases (PostgreSQL, MySQL, MongoDB,
            ClickHouse) via direct connections or SSH tunnels;
          </li>
          <li>
            Index Git repositories to build contextual knowledge about your
            codebase;
          </li>
          <li>
            Ask natural-language questions that are translated into SQL queries
            and executed against your databases in real time;
          </li>
          <li>
            Visualize query results through tables, charts, and exportable
            formats.
          </li>
        </ul>
        <p>
          The source code of CheckMyData.ai is publicly available. You may
          inspect, audit, and verify exactly how the Service processes your
          data at any time by reviewing the repository.
        </p>
      </Section>

      {/* 3. User Accounts */}
      <Section id="accounts" title="3. User Accounts">
        <p>
          To use the Service you must create an account by providing a valid
          email address and a password, or by authenticating through a
          supported third-party provider (e.g., Google OAuth).
        </p>
        <p>You are responsible for:</p>
        <ul>
          <li>
            Maintaining the confidentiality of your account credentials;
          </li>
          <li>
            All activities that occur under your account;
          </li>
          <li>
            Notifying us immediately at{" "}
            <a href="mailto:contact@checkmydata.ai" className="text-accent hover:text-accent-hover transition-colors underline underline-offset-2">
              contact@checkmydata.ai
            </a>{" "}
            if you suspect unauthorized access.
          </li>
        </ul>
        <p>
          We reserve the right to suspend or terminate accounts that violate
          these Terms.
        </p>
      </Section>

      {/* 4. Open Source */}
      <Section id="open-source" title="4. Open Source License">
        <p>
          CheckMyData.ai is an <strong>open-source project</strong>. The
          source code is distributed under its published license, which you
          can review in the project repository. This means:
        </p>
        <ul>
          <li>
            You can inspect every line of code that processes your data;
          </li>
          <li>
            There are no hidden data-collection mechanisms, backdoors, or
            proprietary black boxes;
          </li>
          <li>
            You are free to self-host the Service on your own infrastructure
            under the terms of the applicable license;
          </li>
          <li>
            Community contributions and security audits are welcomed.
          </li>
        </ul>
      </Section>

      {/* 5. User Data & Database Connections */}
      <Section id="user-data" title="5. User Data and Database Connections">
        <p>
          This is the core commitment of CheckMyData.ai regarding your data:
        </p>
        <div className="bg-surface-1 border border-border-subtle rounded-lg p-4 space-y-3">
          <p className="font-semibold text-text-primary">
            We do NOT store, retain, copy, or have independent access to the
            contents of your databases.
          </p>
          <p className="text-text-secondary text-sm">
            The Service acts as a real-time conduit: your natural-language
            question is translated into a SQL query, executed against your
            database via the connection <em>you</em> provide, and the results
            are returned directly to your browser session. Query results are
            transient and are not persisted on our servers beyond the active
            session.
          </p>
        </div>
        <p>Specifically:</p>
        <ul>
          <li>
            <strong>Connection metadata</strong> (host, port, database name,
            database type) is stored to maintain your configured connections.
            The actual data inside your databases is never copied or stored by
            us.
          </li>
          <li>
            <strong>Database credentials</strong> (usernames, passwords) are
            encrypted at rest using industry-standard encryption and are only
            decrypted at the moment a connection is established on your
            behalf.
          </li>
          <li>
            <strong>Query results</strong> exist only in-memory for the
            duration of your session and are discarded afterward.
          </li>
          <li>
            <strong>Chat history</strong> (your questions and the AI
            responses) is stored to provide conversation continuity. This does
            not include raw database rows — only the questions you asked and
            the AI&apos;s textual/SQL responses.
          </li>
        </ul>
      </Section>

      {/* 6. SSH Keys & Credentials */}
      <Section id="ssh-keys" title="6. SSH Keys and Credentials">
        <p>
          If you provide SSH keys to establish tunneled database connections:
        </p>
        <ul>
          <li>
            Private keys are encrypted at rest and stored solely for the
            purpose of establishing SSH tunnels to your specified hosts;
          </li>
          <li>
            Keys are never transmitted to third parties, logged in plaintext,
            or used for any purpose other than the connections you
            configure;
          </li>
          <li>
            You may delete your SSH keys at any time through the application
            interface.
          </li>
        </ul>
      </Section>

      {/* 7. Acceptable Use */}
      <Section id="acceptable-use" title="7. Acceptable Use">
        <p>You agree not to use the Service to:</p>
        <ul>
          <li>
            Violate any applicable law, regulation, or third-party right;
          </li>
          <li>
            Access databases or systems for which you do not have proper
            authorization;
          </li>
          <li>
            Attempt to reverse-engineer, compromise, or disrupt the Service
            infrastructure;
          </li>
          <li>
            Transmit malicious code, SQL injection attacks, or other harmful
            payloads through the chat interface;
          </li>
          <li>
            Use the Service to extract, scrape, or exfiltrate data from
            databases you do not own or have explicit permission to query;
          </li>
          <li>
            Impersonate another person or misrepresent your affiliation with
            any entity;
          </li>
          <li>
            Use the Service in a manner that could damage, disable, or impair
            its functionality for other users.
          </li>
        </ul>
      </Section>

      {/* 8. Intellectual Property */}
      <Section id="ip" title="8. Intellectual Property">
        <p>
          <strong>Your data is yours.</strong> You retain full ownership of
          all data in your databases, the queries you compose, and any results
          derived from those queries. The Service claims no ownership or
          license over your data.
        </p>
        <p>
          The CheckMyData.ai brand, logo, and associated visual identity are
          the property of the project maintainers. The open-source codebase
          is governed by its published license.
        </p>
      </Section>

      {/* 9. Third-Party Services */}
      <Section id="third-party" title="9. Third-Party Services">
        <p>
          The Service integrates with third-party providers to deliver its
          functionality:
        </p>
        <ul>
          <li>
            <strong>LLM Providers</strong> (OpenAI, Anthropic, OpenRouter):
            Your natural-language questions and database schema metadata may
            be sent to these providers to generate SQL queries and
            conversational responses.{" "}
            <em>
              Raw database content (actual rows and values) is not sent to LLM
              providers.
            </em>{" "}
            Each provider&apos;s use of data is governed by their own terms of
            service and privacy policies.
          </li>
          <li>
            <strong>Git Hosting Providers</strong> (GitHub, GitLab, Bitbucket):
            Repository access is performed using the SSH keys you provide,
            solely for the purpose of indexing your codebase.
          </li>
          <li>
            <strong>Google OAuth</strong> (optional): If you choose to sign in
            with Google, your basic profile information (email, name) is
            received from Google. We do not access any other Google services
            or data.
          </li>
        </ul>
        <p>
          We are not responsible for the practices or policies of third-party
          services. We encourage you to review their respective terms.
        </p>
      </Section>

      {/* 10. Disclaimer of Warranties */}
      <Section id="warranties" title="10. Disclaimer of Warranties">
        <p className="uppercase text-xs text-text-secondary tracking-wide leading-relaxed">
          The Service is provided &ldquo;as is&rdquo; and &ldquo;as
          available,&rdquo; without warranties of any kind, express or
          implied, including but not limited to implied warranties of
          merchantability, fitness for a particular purpose, and
          non-infringement.
        </p>
        <p>
          We do not warrant that the Service will be uninterrupted,
          error-free, or secure. AI-generated SQL queries may contain errors
          or produce unexpected results. You are solely responsible for
          reviewing and validating any queries before executing them against
          production databases.
        </p>
        <div className="bg-warning-muted border border-warning/20 rounded-lg p-4">
          <p className="text-sm text-text-secondary">
            <strong className="text-warning">Important:</strong> Always review
            AI-generated SQL before running it on production systems. The
            Service includes safety validations, but no automated system can
            guarantee the safety of every query against every schema.
          </p>
        </div>
      </Section>

      {/* 11. Limitation of Liability */}
      <Section id="liability" title="11. Limitation of Liability">
        <p className="uppercase text-xs text-text-secondary tracking-wide leading-relaxed">
          To the maximum extent permitted by applicable law, in no event
          shall the operators of CheckMyData.ai be liable for any indirect,
          incidental, special, consequential, or punitive damages, or any
          loss of profits, data, use, goodwill, or other intangible losses,
          arising from or related to your use of, or inability to use, the
          Service.
        </p>
        <p>
          This limitation applies regardless of whether the damages are based
          on warranty, contract, tort, statute, or any other legal theory,
          and whether or not we have been advised of the possibility of such
          damages.
        </p>
      </Section>

      {/* 12. Indemnification */}
      <Section id="indemnification" title="12. Indemnification">
        <p>
          You agree to indemnify, defend, and hold harmless CheckMyData.ai
          and its maintainers, contributors, and affiliates from any claims,
          damages, losses, liabilities, and expenses (including reasonable
          legal fees) arising from:
        </p>
        <ul>
          <li>Your use of the Service;</li>
          <li>Your violation of these Terms;</li>
          <li>
            Your violation of any rights of a third party, including
            unauthorized access to databases or systems;
          </li>
          <li>
            Any data you process through the Service.
          </li>
        </ul>
      </Section>

      {/* 13. Modifications */}
      <Section id="modifications" title="13. Modifications to Terms">
        <p>
          We may update these Terms from time to time. When we make material
          changes, we will update the &ldquo;Last updated&rdquo; date at the
          top of this page and, where possible, notify registered users via
          email.
        </p>
        <p>
          Your continued use of the Service after changes become effective
          constitutes acceptance of the revised Terms. If you do not agree
          with the updated Terms, you must discontinue use of the Service.
        </p>
      </Section>

      {/* 14. Governing Law */}
      <Section id="governing-law" title="14. Governing Law">
        <p>
          These Terms shall be governed by and construed in accordance with
          applicable law, without regard to conflict-of-law principles. Any
          disputes arising from these Terms or the Service shall be resolved
          in the appropriate jurisdiction.
        </p>
      </Section>

      {/* 15. Severability */}
      <Section id="severability" title="15. Severability">
        <p>
          If any provision of these Terms is found to be unenforceable or
          invalid, that provision will be limited or eliminated to the
          minimum extent necessary, and the remaining provisions will
          continue in full force and effect.
        </p>
      </Section>

      {/* 16. Contact */}
      <Section id="contact" title="16. Contact Information">
        <p>
          If you have any questions, concerns, or requests regarding these
          Terms, please contact us at:
        </p>
        <div className="bg-surface-1 border border-border-subtle rounded-lg p-4 flex items-center gap-3">
          <svg
            width={18}
            height={18}
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth={2}
            strokeLinecap="round"
            strokeLinejoin="round"
            className="text-accent shrink-0"
          >
            <path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z" />
            <path d="M22 6l-10 7L2 6" />
          </svg>
          <a
            href="mailto:contact@checkmydata.ai"
            className="text-accent hover:text-accent-hover transition-colors text-sm font-medium"
          >
            contact@checkmydata.ai
          </a>
        </div>
      </Section>

      {/* Cross-link */}
      <div className="pt-6 border-t border-border-subtle">
        <p className="text-sm text-text-tertiary">
          See also our{" "}
          <Link
            href="/privacy"
            className="text-accent hover:text-accent-hover transition-colors underline underline-offset-2"
          >
            Privacy Policy
          </Link>{" "}
          for details on how we handle your personal information.
        </p>
      </div>
    </article>
  );
}

function Section({
  id,
  title,
  children,
}: {
  id: string;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section
      id={id}
      className="space-y-4 scroll-mt-8 [&_p]:text-sm [&_p]:text-text-secondary [&_p]:leading-relaxed [&_ul]:list-disc [&_ul]:pl-5 [&_ul]:space-y-2 [&_ul]:text-sm [&_ul]:text-text-secondary [&_li]:leading-relaxed"
    >
      <h2 className="text-lg font-semibold text-text-primary">{title}</h2>
      {children}
    </section>
  );
}
