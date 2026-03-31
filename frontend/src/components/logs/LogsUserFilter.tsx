"use client";

import type { LogUser } from "@/lib/api";

interface Props {
  users: LogUser[];
  selectedUserId: string | null;
  onSelect: (userId: string | null) => void;
}

export function LogsUserFilter({ users, selectedUserId, onSelect }: Props) {
  return (
    <div className="space-y-0.5">
      <button
        onClick={() => onSelect(null)}
        className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-xs transition-colors ${
          !selectedUserId
            ? "bg-accent/10 text-accent"
            : "text-text-secondary hover:bg-surface-2"
        }`}
      >
        <div className="w-6 h-6 rounded-full bg-surface-3 flex items-center justify-center shrink-0">
          <span className="text-[10px] font-medium text-text-tertiary">All</span>
        </div>
        <span className="truncate font-medium">All users</span>
        <span className="ml-auto text-[10px] text-text-muted tabular-nums">
          {users.reduce((s, u) => s + u.request_count, 0)}
        </span>
      </button>

      {users.map((u) => (
        <button
          key={u.user_id}
          onClick={() => onSelect(u.user_id)}
          className={`w-full flex items-center gap-2 px-2 py-1.5 rounded-md text-xs transition-colors ${
            selectedUserId === u.user_id
              ? "bg-accent/10 text-accent"
              : "text-text-secondary hover:bg-surface-2"
          }`}
        >
          {u.picture_url ? (
            /* eslint-disable-next-line @next/next/no-img-element */
            <img
              src={u.picture_url}
              alt=""
              referrerPolicy="no-referrer"
              className="w-6 h-6 rounded-full border border-border-default shrink-0 object-cover"
            />
          ) : (
            <div className="w-6 h-6 rounded-full bg-surface-3 border border-border-default flex items-center justify-center shrink-0">
              <span className="text-[10px] font-medium text-text-tertiary">
                {(u.display_name || u.email || "?").charAt(0).toUpperCase()}
              </span>
            </div>
          )}
          <span className="truncate">{u.display_name || u.email}</span>
          <span className="ml-auto text-[10px] text-text-muted tabular-nums shrink-0">
            {u.request_count}
          </span>
        </button>
      ))}
    </div>
  );
}
