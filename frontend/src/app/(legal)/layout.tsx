import Link from "next/link";

export default function LegalLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-surface-0 text-text-primary flex flex-col">
      <header className="shrink-0 border-b border-border-subtle">
        <div className="max-w-3xl mx-auto px-6 py-4 flex items-center justify-between">
          <Link
            href="/"
            className="flex items-center gap-2.5 group"
          >
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-accent to-blue-700 flex items-center justify-center shrink-0">
              <svg
                width={16}
                height={16}
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth={2}
                strokeLinecap="round"
                strokeLinejoin="round"
                className="text-white"
              >
                <path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z" />
              </svg>
            </div>
            <span className="text-sm font-semibold text-text-primary group-hover:text-accent transition-colors">
              CheckMyData.ai
            </span>
          </Link>
          <Link
            href="/"
            className="text-xs text-text-tertiary hover:text-accent transition-colors flex items-center gap-1"
          >
            <svg
              width={14}
              height={14}
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth={2}
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <path d="M15 18l-6-6 6-6" />
            </svg>
            Back to app
          </Link>
        </div>
      </header>

      <main className="flex-1 py-12 px-6">
        <div className="max-w-3xl mx-auto">{children}</div>
      </main>

      <footer className="shrink-0 border-t border-border-subtle">
        <div className="max-w-3xl mx-auto px-6 py-6 flex flex-col sm:flex-row items-center justify-between gap-4">
          <p className="text-xs text-text-muted">
            &copy; {new Date().getFullYear()} CheckMyData.ai &mdash; Open
            Source Project
          </p>
          <nav className="flex items-center gap-4 text-xs">
            <Link
              href="/terms"
              className="text-text-tertiary hover:text-accent transition-colors"
            >
              Terms of Service
            </Link>
            <span className="text-text-muted/40">|</span>
            <Link
              href="/privacy"
              className="text-text-tertiary hover:text-accent transition-colors"
            >
              Privacy Policy
            </Link>
            <span className="text-text-muted/40">|</span>
            <a
              href="mailto:contact@checkmydata.ai"
              className="text-text-tertiary hover:text-accent transition-colors"
            >
              contact@checkmydata.ai
            </a>
          </nav>
        </div>
      </footer>
    </div>
  );
}
