"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";

interface NavLink {
  readonly href: string;
  readonly label: string;
  readonly external?: boolean;
}

export function MobileMenu({ links }: { links: readonly NavLink[] }) {
  const [open, setOpen] = useState(false);
  const pathname = usePathname();

  const close = useCallback(() => setOpen(false), []);

  useEffect(() => {
    close();
  }, [pathname, close]);

  useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
      return () => { document.body.style.overflow = ""; };
    }
  }, [open]);

  return (
    <>
      <button
        type="button"
        className="sm:hidden p-2 text-text-secondary hover:text-text-primary transition-colors"
        onClick={() => setOpen((v) => !v)}
        aria-label={open ? "Close menu" : "Open menu"}
        aria-expanded={open}
      >
        <svg
          width={20}
          height={20}
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          {open ? (
            <>
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </>
          ) : (
            <>
              <line x1="3" y1="6" x2="21" y2="6" />
              <line x1="3" y1="12" x2="21" y2="12" />
              <line x1="3" y1="18" x2="21" y2="18" />
            </>
          )}
        </svg>
      </button>

      {open && (
        <>
          <div
            className="fixed inset-0 z-30 bg-black/40 sm:hidden"
            onClick={close}
            aria-hidden="true"
          />
          <nav
            className="fixed top-16 left-0 right-0 z-40 bg-surface-0 border-b border-border-subtle sm:hidden animate-fade-in"
            aria-label="Mobile"
          >
            <ul className="max-w-6xl mx-auto px-6 py-4 space-y-1">
              {links.map((link) => (
                <li key={link.href}>
                  {link.external ? (
                    <a
                      href={link.href}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="block py-2.5 text-sm text-text-secondary hover:text-text-primary transition-colors"
                      onClick={close}
                    >
                      {link.label}
                    </a>
                  ) : (
                    <Link
                      href={link.href}
                      className="block py-2.5 text-sm text-text-secondary hover:text-text-primary transition-colors"
                      onClick={close}
                    >
                      {link.label}
                    </Link>
                  )}
                </li>
              ))}
              <li className="pt-2 border-t border-border-subtle">
                <Link
                  href="/login"
                  className="block py-2.5 text-sm text-text-secondary hover:text-text-primary transition-colors"
                  onClick={close}
                >
                  Log in
                </Link>
              </li>
            </ul>
          </nav>
        </>
      )}
    </>
  );
}
