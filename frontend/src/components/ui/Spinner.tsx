"use client";

export function Spinner({ className = "" }: { className?: string }) {
  return (
    <div className={`flex justify-center py-3 ${className}`}>
      <div className="w-4 h-4 border-2 border-zinc-600 border-t-zinc-300 rounded-full animate-spin" />
    </div>
  );
}
