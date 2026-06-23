"use client";

import { useState } from "react";
import { useAppStore } from "@/stores/app-store";
import { useAppPanel } from "@/hooks/useAppPanel";
import { Icon } from "@/components/ui/Icon";

export function HomeAsk() {
  const activeProject = useAppStore((s) => s.activeProject);
  const activeConnection = useAppStore((s) => s.activeConnection);
  const chatMode = useAppStore((s) => s.chatMode);
  const setPendingQuestion = useAppStore((s) => s.setPendingQuestion);
  const { setPanel } = useAppPanel();
  const [value, setValue] = useState("");

  const canAsk = !!activeProject && (!!activeConnection || chatMode === "knowledge_only");

  const submit = () => {
    const q = value.trim();
    if (!q || !canAsk) return;
    setPendingQuestion(q);
    setValue("");
    setPanel("chat");
  };

  return (
    <section className="rounded-lg border border-border-subtle bg-surface-1/50 p-4 space-y-2">
      <label htmlFor="home-ask" className="flex items-center gap-1.5 text-xs font-medium text-text-secondary">
        <Icon name="message-square" size={13} className="text-text-tertiary" />
        Ask your data
      </label>
      <div className="flex gap-2">
        <input
          id="home-ask"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              submit();
            }
          }}
          placeholder={canAsk ? "Ask anything about your data…" : "Add a connection to start asking"}
          disabled={!canAsk}
          maxLength={2000}
          className="flex-1 bg-surface-0 border border-border-subtle rounded-lg px-3 py-2 text-sm text-text-primary placeholder-text-muted focus:outline-none focus:ring-1 focus:ring-accent focus:border-accent transition-colors disabled:opacity-50"
        />
        <button
          type="button"
          onClick={submit}
          disabled={!canAsk || !value.trim()}
          className="shrink-0 px-3.5 py-2 rounded-lg bg-accent text-white text-sm font-medium hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent"
        >
          Ask
        </button>
      </div>
    </section>
  );
}
