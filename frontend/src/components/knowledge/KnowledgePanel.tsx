"use client";

import { KnowledgeHub, type KnowledgeTab } from "./KnowledgeHub";
import { RulesManager } from "@/components/rules/RulesManager";
import { useAppStore } from "@/stores/app-store";

interface KnowledgePanelProps {
  initialTab?: KnowledgeTab;
}

/**
 * What the agent knows about this project, as a screen rather than a sidebar section.
 *
 * `knowledge` and `insights` were both already in `APP_PANELS` — reachable URLs with
 * no case in the panel switch, so both rendered the chat. This is the destination they
 * were declared for.
 *
 * Rules sit here rather than in their own place because they are project knowledge:
 * they are injected into the same prompts as the documents above them, and a user
 * asking "what does the agent know" is asking about both. Keeping them apart is what
 * put them in two unrelated sidebar sections in the first place.
 */
export function KnowledgePanel({ initialTab = "docs" }: KnowledgePanelProps) {
  const activeProject = useAppStore((s) => s.activeProject);

  if (!activeProject) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <p className="text-sm text-text-tertiary">Select a project first</p>
      </div>
    );
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-3xl mx-auto p-6 space-y-4">
        <div className="animate-slide-in-left" style={{ animationFillMode: "both" }}>
          <h2 className="text-sm font-semibold text-text-primary">Knowledge</h2>
          <p className="text-xs text-text-tertiary mt-0.5">
            What the agent knows about {activeProject.name}, and the rules it is told to follow
          </p>
        </div>

        <section
          className="animate-slide-in-left rounded-card border border-border bg-panel p-4"
          style={{ animationDelay: "60ms", animationFillMode: "both" }}
        >
          <KnowledgeHub initialTab={initialTab} />
        </section>

        <section
          className="animate-slide-in-left rounded-card border border-border bg-panel p-4"
          style={{ animationDelay: "120ms", animationFillMode: "both" }}
        >
          <h3 className="text-xs font-medium text-text-secondary uppercase tracking-wider mb-2 px-1">
            Custom rules
          </h3>
          <RulesManager />
        </section>
      </div>
    </div>
  );
}
