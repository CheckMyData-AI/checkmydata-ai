"use client";

interface Props {
  days: number;
  onChange: (days: number) => void;
}

const OPTIONS = [
  { label: "7d", value: 7 },
  { label: "14d", value: 14 },
  { label: "30d", value: 30 },
  { label: "90d", value: 90 },
];

export function LogsDateFilter({ days, onChange }: Props) {
  return (
    <div className="flex items-center gap-1 bg-surface-1 border border-border-subtle rounded-lg p-0.5">
      {OPTIONS.map((opt) => (
        <button
          key={opt.value}
          onClick={() => onChange(opt.value)}
          className={`px-2.5 py-1 rounded-md text-[11px] font-medium transition-colors ${
            days === opt.value
              ? "bg-accent text-white"
              : "text-text-muted hover:text-text-secondary hover:bg-surface-2"
          }`}
        >
          {opt.label}
        </button>
      ))}
    </div>
  );
}
