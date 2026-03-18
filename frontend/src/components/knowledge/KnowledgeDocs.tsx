"use client";

import { useEffect, useState } from "react";
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

export function KnowledgeDocs() {
  const { activeProject } = useAppStore();
  const [docs, setDocs] = useState<DocMeta[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [viewingDoc, setViewingDoc] = useState<{
    id: string;
    content: string;
    source_path: string;
  } | null>(null);

  useEffect(() => {
    if (!activeProject) {
      setListLoading(false);
      return;
    }
    setListLoading(true);
    api.repos
      .docs(activeProject.id)
      .then(setDocs)
      .catch(() => {})
      .finally(() => setListLoading(false));
  }, [activeProject?.id]);

  const handleView = async (doc: DocMeta) => {
    if (!activeProject) return;
    if (viewingDoc?.id === doc.id) {
      setViewingDoc(null);
      return;
    }
    try {
      const full = await api.repos.doc(activeProject.id, doc.id);
      setViewingDoc({
        id: full.id,
        content: full.content,
        source_path: full.source_path,
      });
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "Failed to load doc",
        "error",
      );
    }
  };

  if (!activeProject) return null;

  return (
    <div className="space-y-1.5 px-1">
      {listLoading && <Spinner />}
      {!listLoading && docs.length === 0 && (
        <p className="text-[10px] text-text-muted px-3 py-1">
          No indexed documents yet. Index your repository to generate knowledge
          docs.
        </p>
      )}
      <div className="space-y-0.5 max-h-48 overflow-y-auto sidebar-scroll">
        {docs.map((d) => {
          const iconName =
            (DOC_TYPE_ICONS[d.doc_type] as import("@/components/ui/Icon").IconName) || "file-text";
          return (
            <button
              key={d.id}
              onClick={() => handleView(d)}
              className={`w-full flex items-center gap-2 text-left px-2.5 py-2 rounded-lg text-xs transition-colors ${
                viewingDoc?.id === d.id
                  ? "bg-surface-2 text-text-primary"
                  : "text-text-secondary hover:bg-surface-2/50 hover:text-text-primary"
              }`}
            >
              <Icon
                name={iconName}
                size={12}
                className={
                  viewingDoc?.id === d.id
                    ? "text-accent"
                    : "text-text-muted"
                }
              />
              <span className="flex-1 min-w-0 overflow-hidden">
                <span className="text-[9px] text-text-muted uppercase font-mono mr-1">
                  {d.doc_type}
                </span>
                <span className="block truncate">
                  {d.source_path.split("/").pop()}
                </span>
              </span>
            </button>
          );
        })}
      </div>

      {viewingDoc && (
        <div className="mt-2 p-3 bg-surface-1 rounded-lg border border-border-subtle max-h-64 overflow-y-auto sidebar-scroll">
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
