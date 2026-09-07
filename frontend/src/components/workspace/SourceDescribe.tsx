"use client";

import { useState } from "react";
import { api, type Connection } from "@/lib/api";
import { toast } from "@/stores/toast-store";

/**
 * Say what a source is for, in your own words. `SCN-134`, decision D3: one free-text
 * field, nothing about it validated beyond its length.
 *
 * Two things this component is careful about, and both are honesty rather than polish:
 *
 * **It says where the text goes.** A field whose effect is invisible does not get
 * filled in. One line states that the agent receives this with every question on the
 * connection — which is also the only warning a user gets before writing something they
 * would not want a model to read.
 *
 * **A failed save keeps the text.** Losing a paragraph somebody just wrote, to a
 * network error, is the kind of small betrayal that stops people using a field.
 */

//: Matches the API's cap. Stated here so the counter is honest before the request,
//: rather than the server refusing a paragraph the user already finished.
const MAX = 2000;

export function SourceDescribe({
  connection,
  onDone,
}: {
  connection: Connection;
  /** `undefined` = cancelled and nothing changed; a value = the new description. */
  onDone: (purpose?: string | null) => void;
}) {
  const [text, setText] = useState(connection.purpose ?? "");
  const [saving, setSaving] = useState(false);
  const over = text.length - MAX;

  const save = async () => {
    if (over > 0) return;
    setSaving(true);
    try {
      const trimmed = text.trim();
      await api.connections.update(connection.id, { purpose: trimmed || null });
      toast("Description saved", "success");
      onDone(trimmed || null);
    } catch (e) {
      // Text preserved on purpose — the field stays open with what was typed.
      toast(e instanceof Error ? e.message : "Could not save the description", "error");
      setSaving(false);
    }
  };

  return (
    <div className="mt-2 space-y-1.5">
      <label className="block">
        <span className="sr-only">What is {connection.name} for?</span>
        <textarea
          autoFocus
          rows={3}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Production billing DB. Money is in minor units. Only rows with status='settled' count as revenue."
          className="w-full text-xs bg-surface-1 border border-border rounded-lg px-2 py-1.5 text-text-primary placeholder:text-text-muted outline-none focus-visible:ring-2 focus-visible:ring-accent"
        />
      </label>

      <p className="text-meta text-text-muted">
        Sent to the agent with every question on this connection, as background about the
        data — not as an instruction.
      </p>

      <div className="flex items-center gap-2">
        <button
          type="button"
          onClick={save}
          disabled={saving || over > 0}
          className="text-meta px-2 py-1 rounded border border-border text-text-secondary hover:bg-surface-1 disabled:opacity-50 transition-colors"
        >
          {saving ? "Saving…" : "Save"}
        </button>
        <button
          type="button"
          onClick={() => onDone()}
          className="text-meta px-2 py-1 rounded text-text-muted hover:text-text-secondary transition-colors"
        >
          Cancel
        </button>
        <span className={`text-meta ml-auto ${over > 0 ? "text-warning" : "text-text-muted"}`}>
          {over > 0 ? `${over} over the limit` : `${text.length} / ${MAX}`}
        </span>
      </div>
    </div>
  );
}
