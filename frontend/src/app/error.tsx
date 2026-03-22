"use client";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-8">
      <div className="max-w-md w-full bg-zinc-900 border border-zinc-700 rounded-lg p-6">
        <h2 className="text-lg font-semibold text-red-400 mb-2">
          Something went wrong
        </h2>
        <p className="text-sm text-zinc-400 mb-4">
          {error.message || "An unexpected error occurred."}
        </p>
        <div className="flex gap-3">
          <button
            onClick={reset}
            className="px-4 py-2.5 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-500 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-900"
            autoFocus
          >
            Try again
          </button>
          <button
            onClick={() => (window.location.href = "/")}
            className="px-4 py-2.5 bg-zinc-700 text-white text-sm rounded-lg hover:bg-zinc-600 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-zinc-400 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-900"
          >
            Go home
          </button>
        </div>
      </div>
    </div>
  );
}
