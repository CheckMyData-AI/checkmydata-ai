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
      <body className="bg-zinc-950 text-white">
        <div className="min-h-screen flex items-center justify-center p-8">
          <div className="max-w-md w-full bg-zinc-900 border border-zinc-700 rounded-lg p-6">
            <h2 className="text-lg font-semibold text-red-400 mb-2">
              Application Error
            </h2>
            <p className="text-sm text-zinc-400 mb-4">
              {error.message || "A critical error occurred. Please reload the page."}
            </p>
            <div className="flex gap-3">
              <button
                onClick={reset}
                className="px-4 py-2.5 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-500 transition-colors"
                autoFocus
              >
                Try again
              </button>
              <button
                onClick={() => (window.location.href = "/")}
                className="px-4 py-2.5 bg-zinc-700 text-white text-sm rounded-lg hover:bg-zinc-600 transition-colors"
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
