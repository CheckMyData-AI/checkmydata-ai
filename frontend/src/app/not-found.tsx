import Link from "next/link";

export default function NotFound() {
  return (
    <div className="min-h-screen bg-zinc-950 flex items-center justify-center p-8">
      <div className="max-w-md w-full text-center">
        <div className="text-6xl font-bold text-zinc-700 mb-2">404</div>
        <h1 className="text-xl font-semibold text-zinc-200 mb-2">
          Page not found
        </h1>
        <p className="text-sm text-zinc-400 mb-6">
          The page you&apos;re looking for doesn&apos;t exist or has been moved.
        </p>
        <Link
          href="/"
          className="inline-flex px-5 py-2.5 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-500 transition-colors outline-none focus-visible:ring-2 focus-visible:ring-blue-400 focus-visible:ring-offset-2 focus-visible:ring-offset-zinc-950"
        >
          Back to CheckMyData
        </Link>
      </div>
    </div>
  );
}
