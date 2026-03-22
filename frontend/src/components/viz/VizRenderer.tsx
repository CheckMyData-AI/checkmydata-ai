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

function VizRenderer({ data }: VizRendererProps) {
  const type = data.type as string;
  const payload = data.data as Record<string, unknown>;

  if (!payload) {
    return (
      <div className="bg-zinc-900 rounded-lg p-4 text-center">
        <p className="text-xs text-zinc-500">Visualization data unavailable</p>
      </div>
    );
  }

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

export { VizRenderer };
export default VizRenderer;

function TextViz({ data }: { data: Record<string, unknown> }) {
  if (data.type === "number") {
    return (
      <div className="bg-zinc-900 rounded-lg p-4 text-center overflow-hidden">
        <p className="text-3xl font-bold text-blue-400 break-all">{String(data.value)}</p>
        <p className="text-xs text-zinc-400 mt-1">{String(data.label || "")}</p>
      </div>
    );
  }

  if (data.type === "key_value") {
    const kv = data.data as Record<string, unknown>;
    return (
      <div className="bg-zinc-900 rounded-lg p-4 space-y-2 overflow-hidden">
        {Object.entries(kv).map(([k, v]) => (
          <div key={k} className="flex justify-between text-sm gap-2 min-w-0">
            <span className="text-zinc-400 shrink-0">{k}</span>
            <span className="text-zinc-100 font-mono truncate min-w-0 text-right">{String(v)}</span>
          </div>
        ))}
      </div>
    );
  }

  return (
    <div className="bg-zinc-900 rounded-lg p-4 overflow-hidden">
      <p className="text-sm text-zinc-300 break-words">{String(data.content || "")}</p>
    </div>
  );
}
