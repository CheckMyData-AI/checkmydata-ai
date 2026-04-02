"use client";

import { useEffect, useRef } from "react";
import { api } from "@/lib/api";
import { useAppStore } from "@/stores/app-store";
import { mapDtoToMessages } from "@/components/chat/ChatSessionList";
import { POLL_INTERVAL_MS, MAX_POLL_MS } from "@/lib/polling";

/**
 * Polls for new messages when the active session is in "processing" state
 * but we are not actively streaming (i.e. the user navigated away and came back).
 * Stops polling when new messages appear or the session goes idle.
 */
export function useSessionPolling() {
  const activeSession = useAppStore((s) => s.activeSession);
  const activeProject = useAppStore((s) => s.activeProject);
  const isThinking = useAppStore((s) => s.isThinking);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startedRef = useRef<number>(0);
  const initialMsgCountRef = useRef<number>(0);

  const sessionId = activeSession?.id;
  const sessionStatus = activeSession?.status;
  const projectId = activeProject?.id;

  useEffect(() => {
    const shouldPoll =
      sessionStatus === "processing" && !isThinking && projectId && sessionId;

    if (!shouldPoll) {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
      return;
    }

    const currentMessages = useAppStore.getState().messages;
    initialMsgCountRef.current = currentMessages.length;
    startedRef.current = Date.now();

    const poll = async () => {
      if (Date.now() - startedRef.current > MAX_POLL_MS) {
        if (timerRef.current) {
          clearInterval(timerRef.current);
          timerRef.current = null;
        }
        return;
      }

      try {
        const [sessions, msgs] = await Promise.all([
          api.chat.listSessions(projectId),
          api.chat.getMessages(sessionId),
        ]);

        const store = useAppStore.getState();
        store.setChatSessions(sessions);

        const updatedSession = sessions.find((s) => s.id === sessionId);
        if (updatedSession) {
          store.setActiveSession(updatedSession);
        }

        const mapped = mapDtoToMessages(msgs);
        store.setSessionMessages(sessionId, mapped);

        const hasNewMessages = mapped.length > initialMsgCountRef.current;
        const sessionIdle = updatedSession?.status !== "processing";

        if (hasNewMessages || sessionIdle) {
          if (timerRef.current) {
            clearInterval(timerRef.current);
            timerRef.current = null;
          }
        }
      } catch {
        /* network errors are fine, will retry next tick */
      }
    };

    poll();
    timerRef.current = setInterval(poll, POLL_INTERVAL_MS);

    return () => {
      if (timerRef.current) {
        clearInterval(timerRef.current);
        timerRef.current = null;
      }
    };
  }, [sessionId, sessionStatus, isThinking, projectId]);
}
