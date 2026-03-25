"use client";

import { useEffect, useState } from "react";
import { api, type LLMModel } from "@/lib/api";
import { toast } from "@/stores/toast-store";

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
  "w-full bg-surface-1 border border-border-subtle rounded-lg px-3 py-1.5 text-xs text-text-primary placeholder-text-muted focus:outline-none focus:ring-1 focus:ring-accent transition-colors";

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
  const [loadError, setLoadError] = useState(false);

  useEffect(() => {
    if (!pair.provider) {
      setModels([]);
      setLoadError(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setLoadError(false);
    api.models
      .list(pair.provider)
      .then((m) => {
        if (!cancelled) setModels(m);
      })
      .catch(() => {
        if (!cancelled) {
          setModels([]);
          setLoadError(true);
          toast("Could not load models — type model name manually", "error");
        }
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
        <span className="text-[10px] font-semibold text-text-secondary uppercase tracking-wider">
          {label}
        </span>
        {description && (
          <span className="text-[10px] text-text-muted ml-1.5">{description}</span>
        )}
      </div>
      <select
        value={pair.provider}
        onChange={(e) => onChange({ provider: e.target.value, model: "" })}
        className={inputCls}
        disabled={disabled}
        aria-label={`${label} provider`}
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
            <span className="text-text-muted text-[10px] animate-pulse">
              Loading models...
            </span>
          </div>
        ) : models.length > 0 ? (
          <select
            value={pair.model}
            onChange={(e) => onChange({ ...pair, model: e.target.value })}
            className={inputCls}
            disabled={disabled}
            aria-label={`${label} model`}
          >
            <option value="">Select model</option>
            {models.map((m) => (
              <option key={m.id} value={m.id}>
                {m.name}
              </option>
            ))}
          </select>
        ) : (
          <div>
            <input
              value={pair.model}
              onChange={(e) => onChange({ ...pair, model: e.target.value })}
              placeholder="Model name (e.g. gpt-4o)"
              className={`${inputCls} ${loadError ? "border-warning" : ""}`}
              disabled={disabled}
              aria-label={`${label} model name`}
            />
            {loadError && (
              <p className="text-[10px] text-warning mt-0.5 px-1">Could not load models — type model name manually</p>
            )}
          </div>
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
