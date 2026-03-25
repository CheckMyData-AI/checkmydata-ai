"use client";

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <html lang="en">
      <body className="bg-surface-0 text-white">
        <div className="min-h-screen flex items-center justify-center p-8">
          <div className="max-w-md w-full bg-surface-1 border border-border-default rounded-lg p-6">
            <h2 className="text-lg font-semibold text-error mb-2">
              Application Error
            </h2>
            <p className="text-sm text-text-secondary mb-4">
              {error.message || "A critical error occurred. Please reload the page."}
            </p>
            <div className="flex gap-3">
              <button
                onClick={reset}
                className="px-4 py-2.5 bg-accent text-white text-sm rounded-lg hover:bg-accent-hover transition-colors"
                autoFocus
              >
                Try again
              </button>
              <button
                onClick={() => (window.location.href = "/")}
                className="px-4 py-2.5 bg-surface-3 text-white text-sm rounded-lg hover:bg-surface-3 transition-colors"
              >
                Go home
              </button>
            </div>
          </div>
        </div>
      </body>
    </html>
  );
}
