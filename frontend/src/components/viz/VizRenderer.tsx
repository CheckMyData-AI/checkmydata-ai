"use client";

import dynamic from "next/dynamic";
import { DataTable } from "./DataTable";

const ChartRenderer = dynamic(() => import("./ChartRenderer").then((m) => m.ChartRenderer), {
  ssr: false,
  loading: () => <div className="h-64 bg-zinc-900 rounded-lg animate-pulse" />,
});

interface VizRendererProps {
  data: Record<string, unknown>;
}

export function VizRenderer({ data }: VizRendererProps) {
  const type = data.type as string;
  const payload = data.data as Record<string, unknown>;

  if (!payload) return null;

  switch (type) {
    case "chart":
      return <ChartRenderer config={payload} />;

    case "table":
      return <DataTable data={payload} />;

    case "text":
    case "number":
    case "key_value":
      return <TextViz data={payload} />;

    default:
      return <DataTable data={payload} />;
  }
}

function TextViz({ data }: { data: Record<string, unknown> }) {
  if (data.type === "number") {
    return (
      <div className="bg-zinc-900 rounded-lg p-4 text-center">
        <p className="text-3xl font-bold text-blue-400">{String(data.value)}</p>
        <p className="text-xs text-zinc-400 mt-1">{String(data.label || "")}</p>
      </div>
    );
  }

  if (data.type === "key_value") {
    const kv = data.data as Record<string, unknown>;
    return (
      <div className="bg-zinc-900 rounded-lg p-4 space-y-2">
        {Object.entries(kv).map(([k, v]) => (
          <div key={k} className="flex justify-between text-sm">
            <span className="text-zinc-400">{k}</span>
            <span className="text-zinc-100 font-mono">{String(v)}</span>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="bg-zinc-900 rounded-lg p-4">
      <p className="text-sm text-zinc-300">{String(data.content || "")}</p>
    </div>
  );
}
