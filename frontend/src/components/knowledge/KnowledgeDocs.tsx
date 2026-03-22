"use client";

import { useEffect, useRef, useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { Spinner } from "@/components/ui/Spinner";
import { toast } from "@/stores/toast-store";
import { Icon } from "@/components/ui/Icon";

interface DocMeta {
  id: string;
  doc_type: string;
  source_path: string;
  commit_sha: string | null;
  updated_at: string | null;
}

const DOC_TYPE_ICONS: Record<string, string> = {
  model: "database",
  summary: "layout-dashboard",
  migration: "git-branch",
  sql: "terminal",
};

const VISIBLE_CAP = 5;

export function KnowledgeDocs() {
  const { activeProject } = useAppStore();
  const [docs, setDocs] = useState<DocMeta[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [showAll, setShowAll] = useState(false);
  const [viewingDoc, setViewingDoc] = useState<{
    id: string;
    content: string;
    source_path: string;
  } | null>(null);
  const [docLoadingId, setDocLoadingId] = useState<string | null>(null);
  const mountedRef = useRef(true);

  useEffect(() => {
    return () => { mountedRef.current = false; };
  }, []);

  useEffect(() => {
    if (!activeProject) {
      setListLoading(false);
      return;
    }
    let cancelled = false;
    setListLoading(true);
    api.repos
      .docs(activeProject.id)
      .then((d) => { if (!cancelled) setDocs(d); })
      .catch((err) => { if (!cancelled) toast(err instanceof Error ? err.message : "Failed to load docs", "error"); })
      .finally(() => { if (!cancelled) setListLoading(false); });
    return () => { cancelled = true; };
  }, [activeProject]);

  const handleView = async (doc: DocMeta) => {
    if (!activeProject) return;
    if (viewingDoc?.id === doc.id) {
      setViewingDoc(null);
      return;
    }
    setDocLoadingId(doc.id);
    try {
      const full = await api.repos.doc(activeProject.id, doc.id);
      if (!mountedRef.current) return;
      setViewingDoc({
        id: full.id,
        content: full.content,
        source_path: full.source_path,
      });
    } catch (err) {
      if (!mountedRef.current) return;
      toast(
        err instanceof Error ? err.message : "Failed to load doc",
        "error",
      );
    } finally {
      if (mountedRef.current) setDocLoadingId(null);
    }
  };

  if (!activeProject) return null;

  const visibleDocs = showAll ? docs : docs.slice(0, VISIBLE_CAP);
  const hasMore = docs.length > VISIBLE_CAP;

  return (
    <div className="px-1">
      {listLoading && <Spinner />}
      {!listLoading && docs.length === 0 && (
        <p className="text-[10px] text-text-muted px-3 py-1">
          No indexed documents yet. Index your repository to generate knowledge
          docs.
        </p>
      )}
      <div>
        {visibleDocs.map((d) => {
          const iconName =
            (DOC_TYPE_ICONS[d.doc_type] as import("@/components/ui/Icon").IconName) || "file-text";
          const isViewing = viewingDoc?.id === d.id;
          return (
            <div
              key={d.id}
              className={`relative flex items-center gap-2 pl-3 pr-1.5 py-1.5 rounded-md transition-colors cursor-pointer ${
                isViewing ? "bg-surface-1" : "hover:bg-surface-1"
              }`}
              onClick={() => handleView(d)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  handleView(d);
                }
              }}
            >
              {isViewing && (
                <div className="absolute left-0.5 top-1/4 bottom-1/4 w-0.5 bg-accent rounded-full" />
              )}
              {docLoadingId === d.id ? (
                <div className="w-3 h-3 shrink-0 border border-text-muted border-t-accent rounded-full animate-spin" />
              ) : (
                <Icon
                  name={iconName}
                  size={12}
                  className={`shrink-0 ${isViewing ? "text-accent" : "text-text-muted"}`}
                />
              )}
              <div className="flex-1 min-w-0 flex items-center gap-1.5">
                <span className="text-[8px] text-text-muted uppercase font-mono shrink-0 leading-none">
                  {d.doc_type}
                </span>
                <span className={`text-xs truncate ${isViewing ? "text-text-primary" : "text-text-secondary"}`}>
                  {d.source_path.split("/").pop()}
                </span>
              </div>
            </div>
          );
        })}
      </div>
      {hasMore && (
        <button
          onClick={() => setShowAll((v) => !v)}
          className="w-full text-[10px] text-text-muted hover:text-accent py-1 transition-colors"
        >
          {showAll ? "Show less" : `Show all ${docs.length}`} →
        </button>
      )}

      {viewingDoc && (
        <div className="mt-1.5 p-3 bg-surface-1 rounded-lg border border-border-subtle max-h-64 overflow-y-auto overflow-x-hidden sidebar-scroll">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] text-text-muted truncate flex-1 font-mono">
              {viewingDoc.source_path}
            </span>
            <button
              onClick={() => setViewingDoc(null)}
              className="p-0.5 rounded text-text-muted hover:text-text-primary transition-colors ml-2"
            >
              <Icon name="x" size={12} />
            </button>
          </div>
          <pre className="text-[10px] text-text-secondary whitespace-pre-wrap leading-relaxed">
            {viewingDoc.content}
          </pre>
        </div>
      )}
    </div>
  );
}
