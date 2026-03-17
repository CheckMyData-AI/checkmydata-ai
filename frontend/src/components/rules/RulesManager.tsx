"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { confirmAction } from "@/components/ui/ConfirmModal";
import { toast } from "@/stores/toast-store";
import { Spinner } from "@/components/ui/Spinner";

interface Rule {
  id: string;
  project_id: string | null;
  name: string;
  content: string;
  format: string;
  is_default: boolean;
}

const inputCls =
  "w-full bg-zinc-900 border border-zinc-700 rounded px-3 py-1.5 text-xs text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-blue-500";

function sortRules(rules: Rule[]): Rule[] {
  return [...rules].sort((a, b) => {
    if (a.is_default && !b.is_default) return -1;
    if (!a.is_default && b.is_default) return 1;
    return 0;
  });
}

export function RulesManager() {
  const { activeProject } = useAppStore();
  const [rules, setRules] = useState<Rule[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [listLoading, setListLoading] = useState(true);

  const editingRule = editingId ? rules.find((r) => r.id === editingId) : null;

  useEffect(() => {
    setListLoading(true);
    api.rules
      .list(activeProject?.id)
      .then((data) => setRules(sortRules(data)))
      .catch(() => {})
      .finally(() => setListLoading(false));
  }, [activeProject?.id]);

  const handleCreate = async () => {
    if (!name.trim() || !content.trim()) return;
    try {
      const rule = await api.rules.create({
        project_id: activeProject?.id,
        name: name.trim(),
        content: content.trim(),
      });
      setRules((prev) => sortRules([rule, ...prev]));
      setName("");
      setContent("");
      setShowCreate(false);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to create rule", "error");
    }
  };

  const handleEdit = (rule: Rule) => {
    setEditingId(rule.id);
    setName(rule.name);
    setContent(rule.content);
    setShowCreate(false);
  };

  const handleUpdate = async () => {
    if (!editingId) return;
    try {
      const updated = await api.rules.update(editingId, {
        name: name.trim(),
        content: content.trim(),
      });
      setRules((prev) => sortRules(prev.map((r) => (r.id === updated.id ? updated : r))));
      setEditingId(null);
      setName("");
      setContent("");
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to update rule", "error");
    }
  };

  const handleDelete = async (rule: Rule) => {
    const message = rule.is_default
      ? "Delete the default metrics rule? Once deleted, it won't be re-created automatically."
      : "Delete this rule?";
    if (!(await confirmAction(message))) return;
    try {
      await api.rules.delete(rule.id);
      setRules((prev) => prev.filter((r) => r.id !== rule.id));
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to delete rule", "error");
    }
  };

  const isFormOpen = showCreate || editingId !== null;

  return (
    <div className="space-y-2">
      <div className="flex justify-end">
        <button
          onClick={() => {
            if (showCreate) {
              setShowCreate(false);
            } else {
              setEditingId(null);
              setName("");
              setContent("");
              setShowCreate(true);
            }
          }}
          className="text-xs text-blue-400 hover:text-blue-300"
        >
          {showCreate ? "Cancel" : "+ New"}
        </button>
      </div>

      {isFormOpen && (
        <div className="space-y-2 p-2 bg-zinc-800/50 rounded-lg">
          {editingRule?.is_default && (
            <p className="text-[10px] text-amber-400/70 px-1">
              This is the default metrics guide. Edit it to match your project.
            </p>
          )}
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Rule name"
            className={inputCls}
          />
          <textarea
            value={content}
            onChange={(e) => setContent(e.target.value)}
            placeholder="Rule content (markdown)"
            rows={4}
            className={inputCls + " resize-y min-h-[60px]"}
          />
          <div className="flex gap-2">
            <button
              onClick={editingId ? handleUpdate : handleCreate}
              className="flex-1 px-3 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-500"
            >
              {editingId ? "Save" : "Create"}
            </button>
            {editingId && (
              <button
                onClick={() => {
                  setEditingId(null);
                  setName("");
                  setContent("");
                }}
                className="px-3 py-1.5 text-zinc-400 hover:text-zinc-200 text-xs"
              >
                Cancel
              </button>
            )}
          </div>
        </div>
      )}

      {listLoading && <Spinner />}
      <div className="space-y-1 max-h-48 overflow-y-auto">
        {rules.map((rule) => (
          <div key={rule.id} className="flex items-center gap-1 group">
            <div className="flex-1 px-3 py-1.5 text-xs text-zinc-400 truncate">
              <span className="text-zinc-300">{rule.name}</span>
              {rule.is_default && (
                <span className="ml-1 text-[9px] px-1 py-0.5 rounded bg-amber-900/40 text-amber-400/80">
                  default
                </span>
              )}
              {!rule.project_id && (
                <span className="ml-1 text-[9px] px-1 py-0.5 rounded bg-zinc-700 text-zinc-500">
                  global
                </span>
              )}
            </div>
            <button
              onClick={() => handleEdit(rule)}
              className="text-[10px] text-zinc-600 hover:text-blue-400 px-1 opacity-0 group-hover:opacity-100 transition-opacity"
            >
              ✎
            </button>
            <button
              onClick={() => handleDelete(rule)}
              className="text-xs text-zinc-600 hover:text-red-400 px-1 opacity-0 group-hover:opacity-100 transition-opacity"
            >
              ×
            </button>
          </div>
        ))}
        {rules.length === 0 && (
          <p className="text-[10px] text-zinc-600 px-3">No custom rules yet</p>
        )}
      </div>
    </div>
  );
}
