import Link from "next/link";

export default function NotFound() {
  return (
    <div className="min-h-screen bg-surface-0 flex items-center justify-center p-8">
      <div className="max-w-md w-full text-center">
        <div className="text-6xl font-bold text-text-muted mb-2">404</div>
        <h1 className="text-xl font-semibold text-text-primary mb-2">
          Page not found
        </h1>
        <p className="text-sm text-text-secondary mb-6">
          The page you&apos;re looking for doesn&apos;t exist or has been moved.
        </p>
        <Link
          href="/"
          className="inline-flex px-5 py-2.5 bg-accent text-white text-sm font-medium rounded-lg hover:bg-accent-hover transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent focus-visible:ring-offset-2 focus-visible:ring-offset-surface-0"
        >
          Back to CheckMyData
        </Link>
      </div>
    </div>
  );
}
