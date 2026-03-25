"use client";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="min-h-screen bg-surface-0 flex items-center justify-center p-8">
      <div className="max-w-md w-full bg-surface-1 border border-border-default rounded-lg p-6">
        <h2 className="text-lg font-semibold text-error mb-2">
          Something went wrong
        </h2>
        <p className="text-sm text-text-secondary mb-4">
          {error.message || "An unexpected error occurred."}
        </p>
        <div className="flex gap-3">
          <button
            onClick={reset}
            className="px-4 py-2.5 bg-accent text-white text-sm rounded-lg hover:bg-accent-hover transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface-1"
            autoFocus
          >
            Try again
          </button>
          <button
            onClick={() => (window.location.href = "/")}
            className="px-4 py-2.5 bg-surface-3 text-white text-sm rounded-lg hover:bg-surface-3 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface-1"
          >
            Go home
          </button>
        </div>
      </div>
    </div>
  );
}
