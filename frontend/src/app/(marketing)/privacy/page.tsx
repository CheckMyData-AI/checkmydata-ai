import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Privacy Policy | CheckMyData.ai",
  description:
    "Privacy Policy for CheckMyData.ai — how we handle your data in our open-source AI database query agent.",
  openGraph: {
    title: "Privacy Policy | CheckMyData.ai",
    description:
      "Privacy Policy for CheckMyData.ai — how we handle your data in our open-source AI database query agent.",
    url: "https://checkmydata.ai/privacy",
    siteName: "CheckMyData.ai",
    type: "website",
  },
  alternates: { canonical: "https://checkmydata.ai/privacy" },
};

const LAST_UPDATED = "March 19, 2026";

export default function PrivacyPage() {
  return (
    <article className="space-y-10">
      {/* Page title */}
      <header className="space-y-3 pb-8 border-b border-border-subtle">
        <h1 className="text-2xl font-bold tracking-tight">Privacy Policy</h1>
        <p className="text-sm text-text-tertiary">
          Last updated: {LAST_UPDATED}
        </p>
      </header>

      {/* 1. Introduction */}
      <Section id="introduction" title="1. Introduction">
        <p>
          CheckMyData.ai (&ldquo;we,&rdquo; &ldquo;us,&rdquo;
          &ldquo;our&rdquo;) is committed to protecting your privacy. This
          Privacy Policy explains what information we collect, what we
          explicitly <em>do not</em> collect, how we use the information we
          have, and your rights regarding that information.
        </p>
        <p>
          CheckMyData.ai is an{" "}
          <strong>open-source project</strong>. Our entire codebase is
          publicly available for review. This means you can verify every
          claim in this policy by inspecting the source code yourself — there
          are no hidden data-collection mechanisms.
        </p>
      </Section>

      {/* 2. What We Collect */}
      <Section id="what-we-collect" title="2. Information We Collect">
        <p>We collect only the minimum information necessary to operate the Service:</p>

        <h3 className="text-sm font-semibold text-text-primary pt-2">
          2.1 Account Information
        </h3>
        <ul>
          <li>
            <strong>Email address</strong> — used for authentication and
            account recovery;
          </li>
          <li>
            <strong>Display name</strong> (optional) — shown in the interface
            and to project collaborators;
          </li>
          <li>
            <strong>Password hash</strong> — your password is hashed using
            industry-standard algorithms (bcrypt) before storage. We never
            store plaintext passwords.
          </li>
        </ul>

        <h3 className="text-sm font-semibold text-text-primary pt-2">
          2.2 Connection Metadata
        </h3>
        <ul>
          <li>
            <strong>Database connection details</strong> — host, port,
            database name, database type (PostgreSQL, MySQL, MongoDB,
            ClickHouse). These are required to establish connections on your
            behalf.
          </li>
          <li>
            <strong>Database credentials</strong> — usernames and passwords
            for your databases are encrypted at rest and decrypted only at the
            moment a connection is established.
          </li>
        </ul>

        <h3 className="text-sm font-semibold text-text-primary pt-2">
          2.3 SSH Keys
        </h3>
        <ul>
          <li>
            If you provide SSH keys for tunneled connections, they are stored
            encrypted and used exclusively for establishing SSH tunnels to
            hosts you specify.
          </li>
        </ul>

        <h3 className="text-sm font-semibold text-text-primary pt-2">
          2.4 Chat History
        </h3>
        <ul>
          <li>
            Your natural-language questions and the AI-generated responses
            (including generated SQL) are stored to provide conversation
            continuity across sessions.
          </li>
          <li>
            Chat history does <em>not</em> include raw database rows or query
            result sets.
          </li>
        </ul>

        <h3 className="text-sm font-semibold text-text-primary pt-2">
          2.5 Repository Metadata
        </h3>
        <ul>
          <li>
            When you connect a Git repository, the Service indexes structural
            metadata (file names, entity names, function signatures) and
            generates enriched documentation for RAG retrieval. This metadata
            is stored in a local vector database (ChromaDB).
          </li>
        </ul>

        <h3 className="text-sm font-semibold text-text-primary pt-2">
          2.6 Saved Queries (Notes)
        </h3>
        <ul>
          <li>
            Queries you explicitly save as &ldquo;notes&rdquo; are stored so
            you can reference them later. These contain the SQL and your
            annotation, not the result data.
          </li>
        </ul>
      </Section>

      {/* 3. What We Do NOT Collect */}
      <Section id="what-we-dont-collect" title="3. Information We Do NOT Collect">
        <div className="bg-surface-1 border border-border-subtle rounded-lg p-4 space-y-3">
          <p className="font-semibold text-text-primary">
            We do not collect, store, copy, or retain access to:
          </p>
          <ul className="!pl-5">
            <li>
              <strong>Your database content</strong> — the actual rows,
              columns, and values inside your databases are never stored by
              us. Query results are transient: they exist only in memory
              during your active session and are discarded when the session
              ends.
            </li>
            <li>
              <strong>Raw source code</strong> — repository indexing extracts
              structural metadata (names, signatures, relationships) but does
              not store your full source files.
            </li>
            <li>
              <strong>Analytics or tracking data</strong> — we do not use
              third-party analytics trackers, advertising pixels, or
              fingerprinting technologies.
            </li>
            <li>
              <strong>Behavioral profiling data</strong> — we do not build
              user profiles for advertising, marketing, or sale to third
              parties.
            </li>
          </ul>
        </div>
      </Section>

      {/* 4. How We Use Information */}
      <Section id="how-we-use" title="4. How We Use Your Information">
        <p>The information we collect is used solely to:</p>
        <ul>
          <li>
            <strong>Provide and operate the Service</strong> — authenticate
            your identity, establish database connections, execute queries,
            and render results;
          </li>
          <li>
            <strong>Maintain conversation context</strong> — store chat
            history so you can revisit previous questions and the AI can
            provide contextually relevant follow-ups;
          </li>
          <li>
            <strong>Enable collaboration</strong> — allow project owners to
            invite collaborators who share the same project configuration;
          </li>
          <li>
            <strong>Improve the Service</strong> — identify and fix bugs,
            improve AI agent accuracy, and enhance the user experience. Any
            improvements are made to the open-source codebase and benefit all
            users.
          </li>
        </ul>
        <p>
          We do <strong>not</strong> sell, rent, or trade your personal
          information to any third party. Ever.
        </p>
      </Section>

      {/* 5. Data Storage & Security */}
      <Section id="storage-security" title="5. Data Storage and Security">
        <p>
          CheckMyData.ai follows a <strong>local-first architecture</strong>:
        </p>
        <ul>
          <li>
            Internal application data is stored in SQLite (for structured
            data) and ChromaDB (for vector embeddings), both running
            alongside the application;
          </li>
          <li>
            All sensitive credentials (database passwords, SSH private keys)
            are encrypted at rest using a per-deployment encryption key;
          </li>
          <li>
            Authentication tokens are transmitted over HTTPS and stored
            securely;
          </li>
          <li>
            Password hashes use bcrypt with appropriate cost factors.
          </li>
        </ul>
        <p>
          While we implement industry-standard security measures, no method
          of electronic storage or transmission is 100% secure. We encourage
          self-hosting for maximum control over your data security.
        </p>
      </Section>

      {/* 6. Third-Party Services */}
      <Section id="third-party" title="6. Third-Party Services">
        <p>
          To power its AI capabilities, CheckMyData.ai communicates with
          external Large Language Model (LLM) providers. Here is exactly what
          data is shared:
        </p>

        <h3 className="text-sm font-semibold text-text-primary pt-2">
          6.1 LLM Providers (OpenAI, Anthropic, OpenRouter)
        </h3>
        <div className="overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="border-b border-border-subtle">
                <th className="text-left py-2 pr-4 text-text-tertiary font-medium">
                  Sent to LLM
                </th>
                <th className="text-left py-2 text-text-tertiary font-medium">
                  NOT sent to LLM
                </th>
              </tr>
            </thead>
            <tbody className="text-text-secondary">
              <tr className="border-b border-border-subtle/50">
                <td className="py-2 pr-4">Your natural-language question</td>
                <td className="py-2">Raw database rows/values</td>
              </tr>
              <tr className="border-b border-border-subtle/50">
                <td className="py-2 pr-4">
                  Database schema metadata (table names, column names, types)
                </td>
                <td className="py-2">Database credentials or passwords</td>
              </tr>
              <tr className="border-b border-border-subtle/50">
                <td className="py-2 pr-4">
                  Conversation context (previous Q&A in the session)
                </td>
                <td className="py-2">SSH keys or private keys</td>
              </tr>
              <tr>
                <td className="py-2 pr-4">
                  Repository structural metadata (for knowledge-based queries)
                </td>
                <td className="py-2">
                  Your full source code files
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p>
          Each LLM provider has its own privacy policy and data handling
          practices. We recommend reviewing them if you have concerns about
          how your query text is processed.
        </p>

        <h3 className="text-sm font-semibold text-text-primary pt-2">
          6.2 Google OAuth (Optional)
        </h3>
        <p>
          If you choose to sign in with Google, we receive your email address
          and display name from Google. We do not access your Google Drive,
          Gmail, Calendar, or any other Google services.
        </p>
      </Section>

      {/* 7. Open Source Transparency */}
      <Section id="transparency" title="7. Open Source Transparency">
        <div className="bg-accent-muted border border-accent/20 rounded-lg p-4 space-y-2">
          <p className="text-sm text-text-secondary leading-relaxed">
            Because CheckMyData.ai is open source, every claim in this
            Privacy Policy is verifiable. You can audit the codebase to
            confirm:
          </p>
          <ul className="!pl-5 text-sm text-text-secondary">
            <li>What data is collected and where it is stored;</li>
            <li>What data is sent to LLM providers;</li>
            <li>How credentials are encrypted;</li>
            <li>That no hidden telemetry or tracking exists.</li>
          </ul>
          <p className="text-sm text-text-secondary leading-relaxed">
            We believe transparency is the strongest form of privacy
            assurance.
          </p>
        </div>
      </Section>

      {/* 8. Data Retention & Deletion */}
      <Section id="retention" title="8. Data Retention and Deletion">
        <p>
          We retain your data only for as long as your account is active or as
          needed to provide the Service:
        </p>
        <ul>
          <li>
            <strong>Account data</strong> — retained until you delete your
            account;
          </li>
          <li>
            <strong>Chat history</strong> — retained until you delete
            individual sessions or your entire account;
          </li>
          <li>
            <strong>Connection configurations</strong> — retained until you
            remove them or delete your account;
          </li>
          <li>
            <strong>SSH keys</strong> — retained until you delete them
            through the interface or delete your account;
          </li>
          <li>
            <strong>Repository index data</strong> — retained until you
            remove the project or delete your account.
          </li>
        </ul>
        <p>
          Upon account deletion, all data associated with your account is
          permanently removed. For self-hosted deployments, data lifecycle is
          entirely under your control.
        </p>
      </Section>

      {/* 9. Cookies & Local Storage */}
      <Section id="cookies" title="9. Cookies and Local Storage">
        <p>
          CheckMyData.ai uses only essential, functional storage mechanisms:
        </p>
        <ul>
          <li>
            <strong>Authentication token</strong> — stored in your
            browser&apos;s local storage to keep you signed in across
            sessions;
          </li>
          <li>
            <strong>UI preferences</strong> — sidebar collapse state and
            similar layout preferences, stored in local storage for your
            convenience.
          </li>
        </ul>
        <p>
          We do <strong>not</strong> use third-party cookies, advertising
          cookies, or tracking cookies of any kind.
        </p>
      </Section>

      {/* 10. Children's Privacy */}
      <Section id="children" title="10. Children&rsquo;s Privacy">
        <p>
          The Service is not directed at individuals under the age of 13 (or
          the applicable age of digital consent in your jurisdiction). We do
          not knowingly collect personal information from children. If you
          believe a child has provided us with personal information, please
          contact us at{" "}
          <a
            href="mailto:contact@checkmydata.ai"
            className="text-accent hover:text-accent-hover transition-colors underline underline-offset-2"
          >
            contact@checkmydata.ai
          </a>{" "}
          and we will promptly delete the information.
        </p>
      </Section>

      {/* 11. International Data */}
      <Section id="international" title="11. International Data Transfers">
        <p>
          If you access the hosted version of CheckMyData.ai from outside the
          country where our servers are located, your information may be
          transferred across international borders. By using the Service, you
          consent to such transfers.
        </p>
        <p>
          For users in the European Economic Area (EEA), we process data
          based on legitimate interest (providing the Service you requested)
          and consent (where applicable). You have the right to access,
          rectify, erase, restrict processing of, and port your personal
          data. Contact us at{" "}
          <a
            href="mailto:contact@checkmydata.ai"
            className="text-accent hover:text-accent-hover transition-colors underline underline-offset-2"
          >
            contact@checkmydata.ai
          </a>{" "}
          to exercise these rights.
        </p>
        <p>
          If you require full data sovereignty, we recommend self-hosting
          CheckMyData.ai on infrastructure within your jurisdiction.
        </p>
      </Section>

      {/* 12. Your Rights */}
      <Section id="your-rights" title="12. Your Rights">
        <p>
          Depending on your jurisdiction, you may have the following rights
          regarding your personal data:
        </p>
        <ul>
          <li>
            <strong>Access</strong> — request a copy of the personal data we
            hold about you;
          </li>
          <li>
            <strong>Rectification</strong> — request correction of inaccurate
            data;
          </li>
          <li>
            <strong>Erasure</strong> — request deletion of your account and
            all associated data;
          </li>
          <li>
            <strong>Restriction</strong> — request that we limit how we
            process your data;
          </li>
          <li>
            <strong>Portability</strong> — request your data in a structured,
            machine-readable format;
          </li>
          <li>
            <strong>Objection</strong> — object to processing of your data in
            certain circumstances.
          </li>
        </ul>
        <p>
          To exercise any of these rights, contact us at{" "}
          <a
            href="mailto:contact@checkmydata.ai"
            className="text-accent hover:text-accent-hover transition-colors underline underline-offset-2"
          >
            contact@checkmydata.ai
          </a>
          . We will respond to your request within 30 days.
        </p>
      </Section>

      {/* 13. Changes */}
      <Section id="changes" title="13. Changes to This Privacy Policy">
        <p>
          We may update this Privacy Policy from time to time. When we make
          material changes, we will:
        </p>
        <ul>
          <li>
            Update the &ldquo;Last updated&rdquo; date at the top of this
            page;
          </li>
          <li>
            Where possible, notify registered users via email;
          </li>
          <li>
            Commit the changes to the open-source repository so they are
            publicly visible and auditable.
          </li>
        </ul>
        <p>
          We encourage you to review this page periodically. Your continued
          use of the Service after changes become effective constitutes
          acceptance of the revised Privacy Policy.
        </p>
      </Section>

      {/* 14. Contact */}
      <Section id="contact" title="14. Contact Us">
        <p>
          If you have any questions, concerns, or requests regarding this
          Privacy Policy or our data practices, please reach out:
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
            href="/terms"
            className="text-accent hover:text-accent-hover transition-colors underline underline-offset-2"
          >
            Terms of Service
          </Link>{" "}
          for the full terms governing your use of CheckMyData.ai.
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
