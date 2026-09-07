"use client";

import { useCallback, useEffect, useState } from "react";
import { api, type Connection, type SyncSchedule } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { useAppPanel } from "@/hooks/useAppPanel";
import { usePermission } from "@/hooks/usePermission";
import { toast } from "@/stores/toast-store";
import { Icon } from "@/components/ui/Icon";
import { selectBaseCls } from "@/components/ui/Input";
import { ConnectionSelector } from "@/components/connections/ConnectionSelector";
import { SyncStatusIndicator } from "@/components/connections/SyncStatusIndicator";
import { SourceDescribe } from "./SourceDescribe";

/**
 * One screen where every source of a project is visible and manageable. `SCR-01`,
 * `SCN-129`, `SCN-131`, `SCN-132`, `SCN-147`.
 *
 * What it replaces: a `max-w-xl` panel that re-rendered the sidebar's compact list, so
 * the product had two views of the same list and no management surface.
 *
 * The screen answers one question — *what is connected to this project, and what does
 * it still need?* Everything here earns its place against that question, and the
 * ordering of the groups is the answer to "what do I do first".
 */

const CAPABILITY_LABEL: Record<string, string> = {
  queryable: "the agent can query this",
  collected: "collected on a schedule",
  unknown: "capability unknown",
};

function CapabilityChip({ value }: { value: string | undefined }) {
  const kind = value ?? "unknown";
  const tone =
    kind === "queryable"
      ? "text-text-secondary border-border"
      : kind === "collected"
        ? "text-text-secondary border-border"
        : "text-warning border-warning/40";
  return (
    <span className={`text-kicker px-1.5 py-0.5 rounded border ${tone}`}>
      {CAPABILITY_LABEL[kind] ?? CAPABILITY_LABEL.unknown}
    </span>
  );
}

function SourceCard({
  connection,
  canEdit,
  onDescribed,
}: {
  connection: Connection;
  canEdit: boolean;
  onDescribed: (purpose: string | null) => void;
}) {
  const [describing, setDescribing] = useState(false);
  const firstLine = (connection.purpose ?? "").trim().split("\n")[0];

  return (
    <div className="rounded-card border border-border bg-panel p-3">
      <div className="flex items-start gap-2.5">
        <Icon name="database" size={14} className="text-text-tertiary mt-0.5 shrink-0" />
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-sm text-text-primary truncate">{connection.name}</span>
            {connection.db_type && (
              <span className="text-kicker text-text-muted font-mono">{connection.db_type}</span>
            )}
            <CapabilityChip value={connection.capability} />
            {connection.is_read_only && (
              <span className="text-kicker px-1.5 py-0.5 rounded border border-border text-text-secondary">
                read-only
              </span>
            )}
          </div>

          {/* The description, or its absence stated plainly. "No purpose set" is not a
              placeholder — it tells the user the agent is currently inferring, which is
              where the wrong answers come from (SCN-134). */}
          {firstLine ? (
            <p className="text-meta text-text-secondary mt-1 truncate">{firstLine}</p>
          ) : (
            <p className="text-meta text-text-muted mt-1">
              No purpose set — the agent will infer one
            </p>
          )}

          {canEdit && !describing && (
            <button
              type="button"
              onClick={() => setDescribing(true)}
              className="mt-1.5 text-meta text-text-tertiary hover:text-text-secondary transition-colors outline-none focus-visible:ring-2 focus-visible:ring-accent rounded"
            >
              {firstLine ? "Edit description" : "Describe"}
            </button>
          )}

          {describing && (
            <SourceDescribe
              connection={connection}
              onDone={(purpose) => {
                setDescribing(false);
                if (purpose !== undefined) onDescribed(purpose);
              }}
            />
          )}
        </div>
      </div>
    </div>
  );
}

function SyncHourControl({ projectId }: { projectId: string }) {
  const [schedule, setSchedule] = useState<SyncSchedule | null>(null);
  const [error, setError] = useState(false);
  const [saving, setSaving] = useState(false);
  const { canEdit } = usePermission();

  const load = useCallback(() => {
    setError(false);
    api.projects
      .syncSchedule(projectId)
      .then(setSchedule)
      .catch(() => setError(true));
  }, [projectId]);

  useEffect(load, [load]);

  if (error) {
    // Not "enabled" and not "disabled" — unknown. Rendering it as editable would
    // promise a nightly run nobody has checked can happen.
    return (
      <p className="text-meta text-text-muted flex items-center gap-1.5">
        <Icon name="alert-triangle" size={11} />
        Could not check the sync schedule.
        <button type="button" onClick={load} className="underline hover:text-text-secondary">
          Retry
        </button>
      </p>
    );
  }
  if (!schedule) return null;

  const save = async (hour: number) => {
    setSaving(true);
    try {
      setSchedule(await api.projects.setSyncSchedule(projectId, { hour }));
      toast("Sync hour updated", "success");
    } catch (e) {
      toast(e instanceof Error ? e.message : "Could not update the sync hour", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="flex items-center gap-2 flex-wrap">
      <span className="text-meta text-text-muted">Nightly sync at</span>
      {/* Width comes from the wrapper, geometry from `selectBaseCls`. The pack bans a
          select styled any other way — twelve files once had twelve slightly different
          ones — and "slightly different" is exactly what a few extra utility classes
          here would be. */}
      <div className="w-28 shrink-0">
        <select
          aria-label="Nightly sync hour"
          disabled={!schedule.may_run || !canEdit || saving}
          value={schedule.hour}
          onChange={(e) => save(Number(e.target.value))}
          className={selectBaseCls}
        >
          {Array.from({ length: 24 }, (_, h) => (
            <option key={h} value={h}>
              {String(h).padStart(2, "0")}:00
            </option>
          ))}
        </select>
      </div>
      <span className="text-meta text-text-muted">{schedule.timezone}</span>
      {!schedule.may_run && (
        // SCN-147: the absence of automation is stated where the automation would have
        // been, not on a billing page the user has no reason to open.
        <span className="text-meta text-text-muted">
          — scheduled syncs need a subscription; indexing by hand still works
        </span>
      )}
    </div>
  );
}

export function DataWorkspace() {
  const activeProject = useAppStore((s) => s.activeProject);
  const connections = useAppStore((s) => s.connections);
  const setConnections = useAppStore((s) => s.setConnections);
  const { canEdit } = usePermission();
  const { setPanel } = useAppPanel();
  const [docCount, setDocCount] = useState<number | null>(null);

  const projectId = activeProject?.id;

  useEffect(() => {
    if (!projectId) return;
    let cancelled = false;
    api.repos
      .docs(projectId)
      .then((d) => {
        if (!cancelled) setDocCount(d.length);
      })
      .catch(() => {
        if (!cancelled) setDocCount(null);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const onDescribed = useCallback(
    (id: string, purpose: string | null) => {
      setConnections(connections.map((c) => (c.id === id ? { ...c, purpose } : c)));
    },
    [connections, setConnections],
  );

  if (!activeProject) {
    return (
      <div className="flex-1 flex items-center justify-center p-8">
        <p className="text-sm text-text-tertiary">Select a project first</p>
      </div>
    );
  }

  const hasSources = connections.length > 0;
  const hasRepo = Boolean(activeProject.repo_url);

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="max-w-4xl mx-auto p-6 space-y-5">
        <div className="animate-slide-in-left" style={{ animationFillMode: "both" }}>
          <h2 className="text-sm font-semibold text-text-primary">Data</h2>
          <p className="text-xs text-text-tertiary mt-0.5">
            Everything {activeProject.name} is connected to, and what it still needs
          </p>
        </div>

        {/* ---- Databases & sources ---- */}
        <section
          className="animate-slide-in-left rounded-card border border-border bg-panel p-4 space-y-3"
          style={{ animationDelay: "60ms", animationFillMode: "both" }}
        >
          <div className="flex items-center justify-between gap-2">
            <h3 className="text-xs font-medium text-text-secondary uppercase tracking-wider">
              Databases &amp; sources ({connections.length})
            </h3>
          </div>

          {!hasSources && (
            // SCN-131: the ordering is STATED, not discovered. A repository connected
            // first is never picked up by the nightly wave, because a project with no
            // active connection is not eligible — and nothing used to say so.
            <p className="text-meta text-text-muted">
              Start here. A data source comes first: until the project has one, a
              connected repository is only ever indexed by hand.
            </p>
          )}

          <div className="space-y-2">
            {connections.map((c) => (
              <SourceCard
                key={c.id}
                connection={c}
                canEdit={canEdit}
                onDescribed={(p) => onDescribed(c.id, p)}
              />
            ))}
          </div>

          <div className="border-t border-border-subtle pt-3">
            <ConnectionSelector />
            <SyncStatusIndicator />
          </div>

          <p className="text-meta text-text-muted">
            Credentials are encrypted at rest and never shown again after saving.
          </p>
        </section>

        {/* ---- Repositories ---- */}
        <section
          className="animate-slide-in-left rounded-card border border-border bg-panel p-4 space-y-2"
          style={{ animationDelay: "120ms", animationFillMode: "both" }}
        >
          <h3 className="text-xs font-medium text-text-secondary uppercase tracking-wider">
            Repository
          </h3>
          {hasRepo ? (
            <>
              <p className="text-sm text-text-primary font-mono truncate">
                {activeProject.repo_url}
              </p>
              <p className="text-meta text-text-muted">
                Branch {activeProject.repo_branch || "main"}
                {!hasSources && " · indexed manually only — no data source connected yet"}
              </p>
            </>
          ) : (
            <p className="text-meta text-text-muted">
              No repository connected. Code questions are unavailable without one.
            </p>
          )}
          <SyncHourControl projectId={activeProject.id} />
        </section>

        {/* ---- Documentation ---- */}
        <section
          className="animate-slide-in-left rounded-card border border-border bg-panel p-4 space-y-2"
          style={{ animationDelay: "180ms", animationFillMode: "both" }}
        >
          <h3 className="text-xs font-medium text-text-secondary uppercase tracking-wider">
            Documentation
          </h3>
          <p className="text-meta text-text-muted">
            {docCount === null
              ? "Could not read the document count."
              : docCount === 0
                ? "No documents generated yet — they come from indexing the repository."
                : `${docCount} document${docCount === 1 ? "" : "s"} generated from the repository.`}
          </p>
          <button
            type="button"
            onClick={() => setPanel("knowledge")}
            className="text-meta text-text-tertiary hover:text-text-secondary transition-colors underline outline-none focus-visible:ring-2 focus-visible:ring-accent rounded"
          >
            Open Knowledge
          </button>
        </section>
      </div>
    </div>
  );
}
