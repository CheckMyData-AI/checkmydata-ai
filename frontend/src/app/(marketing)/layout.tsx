import Link from "next/link";
import { LogoMark } from "@/components/ui/Logo";
import { MobileMenu } from "@/components/ui/MobileMenu";

const NAV_LINKS = [
  { href: "/about", label: "About" },
  { href: "/support", label: "Support" },
  {
    href: "https://github.com/CheckMyData-AI/checkmydata-ai",
    label: "GitHub",
    external: true,
  },
] as const;

const FOOTER_PRODUCT = [
  { href: "/about", label: "About" },
  { href: "/contact", label: "Contact" },
  { href: "/support", label: "Support" },
] as const;

const FOOTER_LEGAL = [
  { href: "/terms", label: "Terms of Service" },
  { href: "/privacy", label: "Privacy Policy" },
] as const;

const FOOTER_COMMUNITY = [
  {
    href: "https://github.com/CheckMyData-AI/checkmydata-ai",
    label: "GitHub",
    external: true,
  },
  {
    href: "https://github.com/CheckMyData-AI/checkmydata-ai/issues",
    label: "Issues",
    external: true,
  },
  {
    href: "https://github.com/CheckMyData-AI/checkmydata-ai/discussions",
    label: "Discussions",
    external: true,
  },
] as const;

export default function MarketingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-surface-0 text-text-primary flex flex-col">
      {/* Header */}
      <header className="sticky top-0 z-40 border-b border-border-subtle/60 bg-surface-0/80 backdrop-blur-lg">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <Link href="/" className="flex items-center gap-2.5 group shrink-0">
            <LogoMark size={32} />
            <span className="text-sm font-semibold text-text-primary group-hover:text-accent transition-colors tracking-tight">
              CheckMyData<span className="text-accent">.ai</span>
            </span>
          </Link>

          <nav className="hidden sm:flex items-center gap-6" aria-label="Main">
            {NAV_LINKS.map((link) =>
              "external" in link && link.external ? (
                <a
                  key={link.href}
                  href={link.href}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-sm text-text-secondary hover:text-text-primary transition-colors"
                >
                  {link.label}
                </a>
              ) : (
                <Link
                  key={link.href}
                  href={link.href}
                  className="text-sm text-text-secondary hover:text-text-primary transition-colors"
                >
                  {link.label}
                </Link>
              ),
            )}
          </nav>

          <div className="flex items-center gap-3">
            <Link
              href="/login"
              className="text-sm text-text-secondary hover:text-text-primary transition-colors hidden sm:inline-flex"
            >
              Log in
            </Link>
            <Link
              href="/login"
              className="px-4 py-2 text-sm font-semibold text-white bg-accent hover:bg-accent-hover rounded-lg transition-colors"
            >
              Get Started
            </Link>
            <MobileMenu links={NAV_LINKS} />
          </div>
        </div>
      </header>

      {/* Main content */}
      <main id="main-content" className="flex-1">{children}</main>

      {/* Footer */}
      <footer className="border-t border-border-subtle">
        <div className="max-w-6xl mx-auto px-6 py-12">
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-8">
            {/* Brand column */}
            <div className="col-span-2 sm:col-span-1">
              <Link href="/" className="inline-flex items-center gap-2 mb-4">
                <LogoMark size={28} />
                <span className="text-sm font-semibold tracking-tight">
                  CheckMyData<span className="text-accent">.ai</span>
                </span>
              </Link>
              <p className="text-xs text-text-tertiary leading-relaxed">
                AI analyst for your database. Ask questions like a human, get
                answers like a data scientist.
              </p>
            </div>

            {/* Product */}
            <div>
              <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-3">
                Product
              </h3>
              <ul className="space-y-2">
                {FOOTER_PRODUCT.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      className="text-sm text-text-tertiary hover:text-accent transition-colors"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>

            {/* Legal */}
            <div>
              <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-3">
                Legal
              </h3>
              <ul className="space-y-2">
                {FOOTER_LEGAL.map((link) => (
                  <li key={link.href}>
                    <Link
                      href={link.href}
                      className="text-sm text-text-tertiary hover:text-accent transition-colors"
                    >
                      {link.label}
                    </Link>
                  </li>
                ))}
                <li>
                  <a
                    href="mailto:contact@checkmydata.ai"
                    className="text-sm text-text-tertiary hover:text-accent transition-colors"
                  >
                    contact@checkmydata.ai
                  </a>
                </li>
              </ul>
            </div>

            {/* Community */}
            <div>
              <h3 className="text-xs font-semibold text-text-secondary uppercase tracking-wider mb-3">
                Community
              </h3>
              <ul className="space-y-2">
                {FOOTER_COMMUNITY.map((link) => (
                  <li key={link.href}>
                    <a
                      href={link.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-sm text-text-tertiary hover:text-accent transition-colors"
                    >
                      {link.label}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </div>

          <div className="mt-10 pt-6 border-t border-border-subtle flex flex-col sm:flex-row items-center justify-between gap-4">
            <p className="text-xs text-text-tertiary">
              &copy; {new Date().getFullYear()} CheckMyData.ai &mdash; Open
              Source Project. MIT License.
            </p>
            <div className="flex items-center gap-4 text-xs">
              <a
                href="mailto:support@checkmydata.ai"
                className="text-text-tertiary hover:text-accent transition-colors"
              >
                support@checkmydata.ai
              </a>
              <span className="text-text-muted/40">|</span>
              <a
                href="https://github.com/CheckMyData-AI/checkmydata-ai"
                target="_blank"
                rel="noopener noreferrer"
                className="text-text-tertiary hover:text-accent transition-colors"
              >
                Star on GitHub
              </a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
