"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { confirmAction } from "@/components/ui/ConfirmModal";
import { toast } from "@/stores/toast-store";
import { Spinner } from "@/components/ui/Spinner";
import { Icon } from "@/components/ui/Icon";
import { ActionButton } from "@/components/ui/ActionButton";
import { usePermission } from "@/hooks/usePermission";
import { FormModal } from "@/components/ui/FormModal";

interface Rule {
  id: string;
  project_id: string | null;
  name: string;
  content: string;
  format: string;
  is_default: boolean;
}

const inputCls =
  "w-full bg-surface-1 border border-border-subtle rounded-lg px-3 py-2 text-xs text-text-primary placeholder-text-muted focus:outline-none focus:ring-1 focus:ring-accent focus:border-accent transition-colors";

function sortRules(rules: Rule[]): Rule[] {
  return [...rules].sort((a, b) => {
    if (a.is_default && !b.is_default) return -1;
    if (!a.is_default && b.is_default) return 1;
    return 0;
  });
}

interface RulesManagerProps {
  createRequested?: boolean;
  onCreateHandled?: () => void;
}

export function RulesManager({ createRequested, onCreateHandled }: RulesManagerProps) {
  const activeProject = useAppStore((s) => s.activeProject);
  const rulesVersion = useAppStore((s) => s.rulesVersion);
  const { canEdit } = usePermission();
  const [rules, setRules] = useState<Rule[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [viewingId, setViewingId] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [content, setContent] = useState("");
  const [originalName, setOriginalName] = useState("");
  const [originalContent, setOriginalContent] = useState("");
  const [listLoading, setListLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  const editingRule = editingId
    ? rules.find((r) => r.id === editingId)
    : null;

  const viewingRule = viewingId
    ? rules.find((r) => r.id === viewingId)
    : null;

  const isDirty = editingId !== null && (name !== originalName || content !== originalContent);

  useEffect(() => {
    if (createRequested && canEdit) {
      setEditingId(null);
      setName("");
      setContent("");
      setShowCreate(true);
      onCreateHandled?.();
    }
  }, [createRequested, onCreateHandled, canEdit]);

  useEffect(() => {
    let cancelled = false;
    setListLoading(true);
    api.rules
      .list(activeProject?.id)
      .then((data) => { if (!cancelled) setRules(sortRules(data)); })
      .catch((err) => { if (!cancelled) toast(err instanceof Error ? err.message : "Failed to load rules", "error"); })
      .finally(() => { if (!cancelled) setListLoading(false); });
    return () => { cancelled = true; };
  }, [activeProject?.id, rulesVersion]);

  const handleCreate = async () => {
    if (!name.trim() || !content.trim() || saving) return;
    setSaving(true);
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
      toast("Rule created", "success");
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "Failed to create rule",
        "error",
      );
    } finally {
      setSaving(false);
    }
  };

  const handleEdit = (rule: Rule) => {
    setViewingId(null);
    setEditingId(rule.id);
    setName(rule.name);
    setContent(rule.content);
    setOriginalName(rule.name);
    setOriginalContent(rule.content);
    setShowCreate(false);
  };

  const handleRowClick = (rule: Rule) => {
    if (canEdit) {
      handleEdit(rule);
    } else {
      setViewingId(rule.id);
    }
  };

  const handleUpdate = async () => {
    if (!editingId || saving) return;
    setSaving(true);
    try {
      const updated = await api.rules.update(editingId, {
        name: name.trim(),
        content: content.trim(),
      });
      setRules((prev) =>
        sortRules(prev.map((r) => (r.id === updated.id ? updated : r))),
      );
      setEditingId(null);
      setName("");
      setContent("");
      toast("Rule updated", "success");
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "Failed to update rule",
        "error",
      );
    } finally {
      setSaving(false);
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
      toast(
        err instanceof Error ? err.message : "Failed to delete rule",
        "error",
      );
    }
  };

  const isFormOpen = showCreate || editingId !== null || viewingId !== null;

  const cancel = () => {
    setEditingId(null);
    setViewingId(null);
    setShowCreate(false);
    setName("");
    setContent("");
    setOriginalName("");
    setOriginalContent("");
  };

  return (
    <div className="px-1">
      <FormModal
        open={isFormOpen}
        onClose={cancel}
        title={viewingId ? "View Rule" : editingId ? "Edit Rule" : "New Rule"}
        maxWidth="max-w-3xl"
      >
        {viewingRule ? (
          <div className="space-y-2.5">
            <p className="text-sm font-medium text-text-primary">{viewingRule.name}</p>
            <pre className="w-full bg-surface-2 border border-border-subtle rounded-lg px-3 py-2 text-xs text-text-secondary font-mono whitespace-pre-wrap min-h-[200px] overflow-y-auto max-h-[60vh]">
              {viewingRule.content}
            </pre>
          </div>
        ) : (
          <div className="space-y-2.5">
            {editingRule?.is_default && (
              <p className="text-[10px] text-warning/70 px-1 flex items-center gap-1">
                <Icon name="zap" size={10} />
                This is the default metrics guide. Edit it to match your project.
              </p>
            )}
            <input
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="Rule name"
              aria-label="Rule name"
              maxLength={255}
              className={inputCls}
            />
            <textarea
              value={content}
              onChange={(e) => setContent(e.target.value)}
              placeholder="Rule content (markdown)"
              aria-label="Rule content"
              rows={12}
              maxLength={50000}
              className={inputCls + " resize-y min-h-[200px] font-mono text-[13px]"}
            />
            <div className="flex gap-2 pt-1">
              <button
                onClick={editingId ? handleUpdate : handleCreate}
                disabled={saving || (editingId !== null && !isDirty)}
                className="flex-1 px-3 py-2 bg-accent text-white text-xs font-medium rounded-lg hover:bg-accent-hover disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
              >
                {saving ? "Saving..." : editingId ? "Save" : "Create"}
              </button>
              {editingId && (
                <button
                  onClick={cancel}
                  className="px-3 py-2 text-text-tertiary hover:text-text-primary text-xs transition-colors"
                >
                  Cancel
                </button>
              )}
            </div>
          </div>
        )}
      </FormModal>

      {listLoading && <Spinner />}
      <div>
        {rules.map((rule) => (
          <div
            key={rule.id}
            role="button"
            tabIndex={0}
            onClick={() => handleRowClick(rule)}
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); handleRowClick(rule); } }}
            className="group relative flex items-center gap-2 pl-3 pr-1.5 py-1.5 rounded-md hover:bg-surface-1 transition-colors cursor-pointer"
          >
            <Icon
              name="file-text"
              size={12}
              className="text-text-muted shrink-0"
            />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-text-secondary truncate">
                  {rule.name}
                </span>
                {rule.is_default && (
                  <span className="shrink-0 text-[10px] px-1 py-px rounded-full bg-warning-muted text-warning leading-none">
                    default
                  </span>
                )}
                {!rule.project_id && (
                  <span className="shrink-0 text-[10px] px-1 py-px rounded-full bg-surface-3/50 text-text-muted leading-none">
                    global
                  </span>
                )}
              </div>
            </div>
            <div className="shrink-0 flex items-center gap-0.5 opacity-0 group-hover:opacity-100 focus-within:opacity-100 transition-opacity duration-150">
              {canEdit && (
                <ActionButton
                  icon="pencil"
                  title="Edit rule"
                  onClick={(e) => { e.stopPropagation(); handleEdit(rule); }}
                  size="xs"
                />
              )}
              {canEdit && (
                <ActionButton
                  icon="trash"
                  title="Delete rule"
                  onClick={(e) => { e.stopPropagation(); handleDelete(rule); }}
                  variant="danger"
                  size="xs"
                />
              )}
            </div>
          </div>
        ))}
        {rules.length === 0 && (
          <p className="text-[10px] text-text-muted px-3 py-1">
            No custom rules yet
          </p>
        )}
      </div>
    </div>
  );
}
