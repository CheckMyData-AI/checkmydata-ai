"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { Spinner } from "@/components/ui/Spinner";
import { toast } from "@/stores/toast-store";

interface DocMeta {
  id: string;
  doc_type: string;
  source_path: string;
  commit_sha: string | null;
  updated_at: string | null;
}

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
    if (!activeProject) { setListLoading(false); return; }
    setListLoading(true);
    api.repos.docs(activeProject.id).then(setDocs).catch(() => {}).finally(() => setListLoading(false));
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
      toast(err instanceof Error ? err.message : "Failed to load doc", "error");
    }
  };

  if (!activeProject) return null;

  return (
    <div className="space-y-2">
      {listLoading && <Spinner />}
      {!listLoading && docs.length === 0 && (
        <p className="text-[10px] text-zinc-600 px-3">
          No indexed documents yet. Index your repository to generate knowledge docs.
        </p>
      )}
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {docs.map((d) => (
          <button
            key={d.id}
            onClick={() => handleView(d)}
            className={`w-full text-left px-3 py-1.5 rounded-md text-xs transition-colors truncate ${
              viewingDoc?.id === d.id
                ? "bg-zinc-800 text-zinc-100"
                : "text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-300"
            }`}
          >
            <span className="text-[9px] text-zinc-500 uppercase mr-1">
              {d.doc_type}
            </span>
            {d.source_path.split("/").pop()}
          </button>
        ))}
      </div>

      {viewingDoc && (
        <div className="mt-2 p-3 bg-zinc-900 rounded-lg max-h-64 overflow-y-auto">
          <div className="flex items-center justify-between mb-2">
            <span className="text-[10px] text-zinc-500 truncate flex-1">
              {viewingDoc.source_path}
            </span>
            <button
              onClick={() => setViewingDoc(null)}
              className="text-xs text-zinc-500 hover:text-zinc-300 ml-2"
            >
              ×
            </button>
          </div>
          <pre className="text-[10px] text-zinc-300 whitespace-pre-wrap leading-relaxed">
            {viewingDoc.content}
          </pre>
        </div>
      )}
    </div>
  );
}
