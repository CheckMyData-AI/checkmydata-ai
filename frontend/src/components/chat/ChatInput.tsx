"use client";

import { type ReactNode, useState, useRef, useCallback } from "react";

interface ChatInputProps {
  onSend: (message: string) => void;
  disabled?: boolean;
  placeholder?: string;
  rightSlot?: ReactNode;
}

export function ChatInput({ onSend, disabled, placeholder, rightSlot }: ChatInputProps) {
  const [value, setValue] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);

  const handleSend = useCallback(() => {
    const trimmed = value.trim();
    if (!trimmed || disabled) return;
    onSend(trimmed);
    setValue("");
    inputRef.current?.focus();
  }, [value, disabled, onSend]);

  const MAX_LENGTH = 4000;
  const remaining = MAX_LENGTH - value.length;
  const nearLimit = remaining <= 200;

  return (
    <div className="sticky bottom-0 py-4 px-4 md:px-6 flex justify-center bg-surface-0" style={{ paddingBottom: "max(1rem, env(safe-area-inset-bottom))" }}>
      <div className="flex flex-col gap-1 max-w-2xl w-full">
        <div className="flex gap-2 items-end">
          <textarea
            ref={inputRef}
            value={value}
            onChange={(e) => { if (e.target.value.length <= MAX_LENGTH) setValue(e.target.value); }}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder={placeholder || "Ask about your database..."}
            disabled={disabled}
            rows={1}
            maxLength={MAX_LENGTH}
            aria-label="Message input"
            className="flex-1 resize-none max-h-40 overflow-y-auto bg-transparent border border-zinc-700/50 rounded-xl px-4 py-3 text-base md:text-sm text-zinc-100 placeholder-zinc-500 focus:outline-none focus:ring-1 focus:ring-zinc-500/40 focus:border-zinc-500/40 disabled:opacity-50 transition-colors"
          />
          <button
            onClick={handleSend}
            disabled={disabled || !value.trim()}
            aria-label="Send message"
            className="shrink-0 min-h-[44px] min-w-[44px] flex items-center justify-center rounded-xl border border-zinc-700/50 text-zinc-400 hover:text-zinc-100 hover:border-zinc-500/50 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          >
            <svg className="w-5 h-5 md:w-4 md:h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 12L3.269 3.126A59.768 59.768 0 0121.485 12 59.77 59.77 0 013.27 20.876L5.999 12zm0 0h7.5" />
            </svg>
          </button>
          {rightSlot}
        </div>
        {nearLimit && (
          <p className={`text-[10px] text-right pr-14 transition-colors ${remaining <= 50 ? "text-red-400" : "text-zinc-500"}`}>
            {remaining} characters remaining
          </p>
        )}
      </div>
    </div>
  );
}
