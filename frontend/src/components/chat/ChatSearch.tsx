"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import { api } from "@/lib/api";
import type { ChatSearchResult } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { toast } from "@/stores/toast-store";
import { Icon } from "@/components/ui/Icon";
import { mapDtoToMessages } from "@/components/chat/ChatSessionList";

const DEBOUNCE_MS = 300;

export function ChatSearch() {
  const activeProject = useAppStore((s) => s.activeProject);
  const connections = useAppStore((s) => s.connections);
  const chatSessions = useAppStore((s) => s.chatSessions);
  const setActiveSession = useAppStore((s) => s.setActiveSession);
  const setActiveConnection = useAppStore((s) => s.setActiveConnection);
  const setSessionMessages = useAppStore((s) => s.setSessionMessages);

  const [query, setQuery] = useState("");
  const [results, setResults] = useState<ChatSearchResult[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(0);

  const inputRef = useRef<HTMLInputElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current);
    };
  }, []);

  const mountedRef = useRef(true);

  useEffect(() => {
    return () => { mountedRef.current = false; };
  }, []);

  const doSearch = useCallback(
    async (term: string) => {
      if (!activeProject || term.trim().length < 2) {
        setResults([]);
        setLoading(false);
        return;
      }
      setLoading(true);
      try {
        const data = await api.chat.search(activeProject.id, term.trim());
        if (!mountedRef.current) return;
        setResults(data);
        setSelectedIdx(0);
      } catch (err) {
        if (!mountedRef.current) return;
        toast(
          err instanceof Error ? err.message : "Search failed",
          "error",
        );
        setResults([]);
      } finally {
        if (mountedRef.current) setLoading(false);
      }
    },
    [activeProject],
  );

  const handleInputChange = (value: string) => {
    setQuery(value);
    if (debounceRef.current) clearTimeout(debounceRef.current);
    if (value.trim().length < 2) {
      setResults([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    setOpen(true);
    debounceRef.current = setTimeout(() => doSearch(value), DEBOUNCE_MS);
  };

  const navigateToResult = async (result: ChatSearchResult) => {
    const session = chatSessions.find((s) => s.id === result.session_id);
    if (!session) {
      toast("Session not found in sidebar", "error");
      return;
    }

    setActiveSession(session);
    if (session.connection_id) {
      const conn = connections.find((c) => c.id === session.connection_id);
      if (conn) setActiveConnection(conn);
    }

    try {
      const msgs = await api.chat.getMessages(session.id);
      setSessionMessages(session.id, mapDtoToMessages(msgs));
    } catch (err) {
      toast(
        err instanceof Error ? err.message : "Failed to load messages",
        "error",
      );
    }

    setOpen(false);
    setQuery("");
    setResults([]);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Escape") {
      setOpen(false);
      inputRef.current?.blur();
      return;
    }
    if (!open || results.length === 0) return;
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setSelectedIdx((i) => Math.min(i + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setSelectedIdx((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      navigateToResult(results[selectedIdx]);
    }
  };

  useEffect(() => {
    const onClickOutside = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    document.addEventListener("mousedown", onClickOutside);
    return () => document.removeEventListener("mousedown", onClickOutside);
  }, []);

  useEffect(() => {
    const onGlobalKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        inputRef.current?.focus();
        setOpen(true);
      }
    };
    document.addEventListener("keydown", onGlobalKey);
    return () => document.removeEventListener("keydown", onGlobalKey);
  }, []);

  function highlightMatch(text: string, term: string) {
    if (!term.trim()) return text;
    const idx = text.toLowerCase().indexOf(term.toLowerCase());
    if (idx === -1) return text;
    return (
      <>
        {text.slice(0, idx)}
        <mark className="bg-accent/30 text-text-primary rounded-sm px-0.5">
          {text.slice(idx, idx + term.length)}
        </mark>
        {text.slice(idx + term.length)}
      </>
    );
  }

  function formatTime(iso: string) {
    if (!iso) return "";
    const d = new Date(iso);
    const now = Date.now();
    const diff = now - d.getTime();
    const mins = Math.floor(diff / 60_000);
    if (mins < 1) return "just now";
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    const days = Math.floor(hours / 24);
    return `${days}d ago`;
  }

  const showDropdown = open && (loading || results.length > 0 || (query.trim().length >= 2 && !loading));

  return (
    <div ref={containerRef} className="relative px-1 mb-1.5">
      <div className="relative">
        <Icon
          name="search"
          size={12}
          className="absolute left-2.5 top-1/2 -translate-y-1/2 text-text-muted pointer-events-none"
        />
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={(e) => handleInputChange(e.target.value)}
          onFocus={() => {
            if (query.trim().length >= 2) setOpen(true);
          }}
          onKeyDown={handleKeyDown}
          aria-label="Search chats"
          placeholder="Search chats..."
          className="w-full pl-7 pr-10 py-1.5 text-xs bg-surface-1 border border-border-subtle rounded-md text-text-primary placeholder:text-text-muted/60 outline-none focus:border-accent/50 focus:ring-1 focus:ring-accent/20 transition-colors"
        />
        <kbd className="absolute right-2 top-1/2 -translate-y-1/2 hidden sm:inline-flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] text-text-muted/50 bg-surface-2 border border-border-subtle rounded font-mono leading-none">
          {typeof navigator !== "undefined" && /mac/i.test(navigator.userAgent) ? "\u2318" : "Ctrl"}K
        </kbd>
      </div>

      {showDropdown && (
        <div className="absolute z-50 left-0 right-0 mt-1 mx-0 max-h-64 overflow-y-auto bg-surface-1 border border-border-subtle rounded-lg shadow-lg">
          {loading && results.length === 0 && (
            <div className="flex items-center justify-center py-4 gap-2">
              <div className="w-3 h-3 border-2 border-accent/40 border-t-accent rounded-full animate-spin" />
              <span className="text-xs text-text-muted">Searching...</span>
            </div>
          )}

          {!loading && results.length === 0 && query.trim().length >= 2 && (
            <div className="py-4 text-center text-xs text-text-muted">
              No results found
            </div>
          )}

          {!loading && results.length === 0 && query.trim().length > 0 && query.trim().length < 2 && (
            <div className="py-4 text-center text-xs text-text-muted">
              Type at least 2 characters to search
            </div>
          )}

          {results.map((r, i) => (
            <button
              key={`${r.message_id}-${i}`}
              onClick={() => navigateToResult(r)}
              onMouseEnter={() => setSelectedIdx(i)}
              className={`w-full text-left px-3 py-2 border-b border-border-subtle/50 last:border-b-0 transition-colors ${
                i === selectedIdx ? "bg-surface-2" : "hover:bg-surface-2/50"
              }`}
            >
              <div className="flex items-center justify-between gap-2 mb-0.5">
                <span className="text-[11px] font-medium text-text-primary truncate">
                  {r.session_title}
                </span>
                <span className="text-[10px] text-text-muted shrink-0">
                  {formatTime(r.created_at)}
                </span>
              </div>
              <p className="text-[11px] text-text-secondary leading-relaxed line-clamp-2">
                {highlightMatch(r.content_snippet, query.trim())}
              </p>
              {r.sql_query && (
                <div className="mt-1 flex items-center gap-1.5">
                  <Icon name="terminal" size={10} className="text-accent/60 shrink-0" />
                  <span className="text-[10px] text-accent/70 font-mono truncate">
                    {r.sql_query.length > 80 ? r.sql_query.slice(0, 80) + "..." : r.sql_query}
                  </span>
                </div>
              )}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
