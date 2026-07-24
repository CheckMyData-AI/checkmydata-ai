"use client";

import dynamic from "next/dynamic";
import type { Components } from "react-markdown";

export interface MarkdownProps {
  children: string;
  components?: Components;
}

/**
 * Lazy markdown renderer. react-markdown AND remark-gfm are fetched together
 * in the async chunk — importing remark-gfm statically next to a dynamic()
 * react-markdown pulls the whole micromark/gfm tree (~28 kB gzip) into the
 * eager /app bundle and defeats the code split (audit F-2).
 */
export const Markdown = dynamic<MarkdownProps>(
  () =>
    Promise.all([import("react-markdown"), import("remark-gfm")]).then(
      ([md, gfm]) => {
        const ReactMarkdown = md.default;
        const remarkGfm = gfm.default;
        return function MarkdownImpl({ children, components }: MarkdownProps) {
          return (
            <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
              {children}
            </ReactMarkdown>
          );
        };
      },
    ),
  {
    loading: () => <span className="text-sm text-text-tertiary">Loading…</span>,
  },
);

/** Shared component map for chat markdown (assistant text + streaming). */
export const mdComponents: Components = {
  p: ({ children }) => <p className="text-sm mb-2 last:mb-0">{children}</p>,
  h1: ({ children }) => <h1 className="text-lg font-semibold mb-2 mt-3 first:mt-0 break-words">{children}</h1>,
  h2: ({ children }) => <h2 className="text-base font-semibold mb-2 mt-3 first:mt-0 break-words">{children}</h2>,
  h3: ({ children }) => <h3 className="text-sm font-semibold mb-1.5 mt-2.5 first:mt-0 break-words">{children}</h3>,
  h4: ({ children }) => <h4 className="text-sm font-medium mb-1 mt-2 first:mt-0 break-words">{children}</h4>,
  ul: ({ children }) => <ul className="list-disc pl-4 mb-2 last:mb-0 space-y-0.5 text-sm">{children}</ul>,
  ol: ({ children }) => <ol className="list-decimal pl-4 mb-2 last:mb-0 space-y-0.5 text-sm">{children}</ol>,
  li: ({ children }) => <li className="text-sm">{children}</li>,
  strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  a: ({ href, children }) => {
    const safeHref = href && /^https?:\/\//i.test(href) ? href : undefined;
    return (
      <a href={safeHref} target="_blank" rel="noopener noreferrer" className="text-accent underline hover:text-accent-hover break-all">
        {children}
      </a>
    );
  },
  blockquote: ({ children }) => (
    <blockquote className="border-l-2 border-border-default pl-3 my-2 text-text-secondary italic overflow-hidden break-words">{children}</blockquote>
  ),
  code: ({ className, children }) => {
    const isBlock = className?.includes("language-");
    if (isBlock) {
      return <code className="text-xs font-mono">{children}</code>;
    }
    return <code className="bg-surface-1 text-text-primary px-1 py-0.5 rounded text-xs font-mono break-all">{children}</code>;
  },
  pre: ({ children }) => (
    <pre className="bg-surface-1 p-3 rounded-lg overflow-x-auto max-w-full mb-2 last:mb-0">{children}</pre>
  ),
  table: ({ children }) => (
    <div className="overflow-x-auto mb-2 last:mb-0">
      <table className="text-xs border-collapse w-full">{children}</table>
    </div>
  ),
  thead: ({ children }) => <thead className="border-b border-border-default">{children}</thead>,
  th: ({ children }) => <th className="text-left px-2 py-1 text-text-secondary font-medium">{children}</th>,
  td: ({ children }) => <td className="px-2 py-1 border-t border-border-subtle">{children}</td>,
  hr: () => <hr className="border-border-default my-3" />,
  img: () => null,
};
