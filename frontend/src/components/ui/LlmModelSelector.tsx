"use client";

import { useEffect, useState } from "react";
import { api, type LLMModel } from "@/lib/api";

export interface LlmPair {
  provider: string;
  model: string;
}

export const EMPTY_LLM: LlmPair = { provider: "", model: "" };

const LLM_PROVIDERS: { value: string; label: string }[] = [
  { value: "openai", label: "OpenAI" },
  { value: "anthropic", label: "Anthropic" },
  { value: "openrouter", label: "OpenRouter" },
];

const inputCls =
  "w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-1.5 text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-blue-500";

export function LlmModelSelector({
  label,
  description,
  pair,
  onChange,
  disabled = false,
}: {
  label: string;
  description?: string;
  pair: LlmPair;
  onChange: (pair: LlmPair) => void;
  disabled?: boolean;
}) {
  const [models, setModels] = useState<LLMModel[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!pair.provider) {
      setModels([]);
      return;
    }
    let cancelled = false;
    setLoading(true);
    api.models
      .list(pair.provider)
      .then((m) => {
        if (!cancelled) setModels(m);
      })
      .catch(() => {
        if (!cancelled) setModels([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [pair.provider]);

  return (
    <div className={`space-y-1.5 ${disabled ? "opacity-50 pointer-events-none" : ""}`}>
      <div>
        <span className="text-[10px] font-semibold text-zinc-400 uppercase tracking-wider">
          {label}
        </span>
        {description && (
          <span className="text-[10px] text-zinc-600 ml-1.5">{description}</span>
        )}
      </div>
      <select
        value={pair.provider}
        onChange={(e) => onChange({ provider: e.target.value, model: "" })}
        className={inputCls}
        disabled={disabled}
      >
        <option value="">System default (OpenAI)</option>
        {LLM_PROVIDERS.map((p) => (
          <option key={p.value} value={p.value}>
            {p.label}
          </option>
        ))}
      </select>
      {pair.provider && (
        loading ? (
          <div className={`${inputCls} flex items-center`}>
            <span className="text-zinc-500 text-[10px] animate-pulse">
              Loading models...
            </span>
          </div>
        ) : models.length > 0 ? (
          <select
            value={pair.model}
            onChange={(e) => onChange({ ...pair, model: e.target.value })}
            className={inputCls}
            disabled={disabled}
          >
            <option value="">Select model</option>
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        ) : (
          <input
            value={pair.model}
            onChange={(e) => onChange({ ...pair, model: e.target.value })}
            placeholder="Model name (e.g. gpt-4o)"
            className={inputCls}
            disabled={disabled}
          />
        )
      )}
    </div>
  );
}

export function formatProvider(provider: string | null): string {
  if (!provider) return "";
  const found = LLM_PROVIDERS.find((p) => p.value === provider);
  return found ? found.label : provider;
}

export function formatModelShort(model: string | null): string {
  if (!model) return "";
  const last = model.split("/").pop() || model;
  return last.length > 24 ? last.slice(0, 22) + "\u2026" : last;
}
