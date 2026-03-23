"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type ConnectionHealthState } from "@/lib/api";
import { Tooltip } from "@/components/ui/Tooltip";
import { onEvent, type WorkflowEvent } from "@/lib/sse";
import { toast } from "@/stores/toast-store";

type HealthStatus = "healthy" | "degraded" | "down" | "unknown";

const STATUS_DOT_CLASSES: Record<HealthStatus, string> = {
  healthy: "bg-success",
  degraded: "bg-warning",
  down: "bg-error",
  unknown: "bg-surface-3",
};

function formatCheckTime(iso: string | null): string {
  if (!iso) return "never";
  const diff = Date.now() - new Date(iso).getTime();
  const secs = Math.floor(diff / 1000);
  if (secs < 60) return "just now";
  const mins = Math.floor(secs / 60);
  if (mins < 60) return `${mins}m ago`;
  return `${Math.floor(mins / 60)}h ago`;
}

interface ConnectionHealthProps {
  connectionId: string;
  onStatusChange?: (status: HealthStatus) => void;
}

export function ConnectionHealth({ connectionId, onStatusChange }: ConnectionHealthProps) {
  const [health, setHealth] = useState<ConnectionHealthState | null>(null);
  const [loading, setLoading] = useState(true);
  const [reconnecting, setReconnecting] = useState(false);
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  const fetchHealth = useCallback(() => {
    api.connections.health(connectionId)
      .then((h) => {
        if (mountedRef.current) {
          setHealth(h);
          setLoading(false);
          onStatusChange?.(h.status as HealthStatus);
        }
      })
      .catch(() => {
        if (mountedRef.current) setLoading(false);
      });
  }, [connectionId, onStatusChange]);

  useEffect(() => {
    fetchHealth();
  }, [fetchHealth]);

  useEffect(() => {
    const unsub = onEvent((event: WorkflowEvent) => {
      if (
        event.step === "connection_health" &&
        event.extra?.connection_id === connectionId
      ) {
        setHealth((prev) => {
          const updated: ConnectionHealthState = {
            status: event.status as HealthStatus,
            latency_ms: (event.extra?.latency_ms as number) ?? 0,
            last_check: new Date().toISOString(),
            consecutive_failures: prev?.consecutive_failures ?? 0,
            last_error: (event.extra?.last_error as string) ?? null,
          };
          onStatusChange?.(updated.status as HealthStatus);
          return updated;
        });
      }
    });
    return unsub;
  }, [connectionId, onStatusChange]);

  const handleReconnect = async (e: React.MouseEvent) => {
    e.stopPropagation();
    setReconnecting(true);
    try {
      const result = await api.connections.reconnect(connectionId);
      if (result.health) {
        setHealth(result.health);
        onStatusChange?.(result.health.status as HealthStatus);
      }
    } catch (err) {
      toast(err instanceof Error ? err.message : "Reconnect failed", "error");
    } finally {
      if (mountedRef.current) setReconnecting(false);
    }
  };

  if (loading) {
    return (
      <span className="inline-flex items-center" aria-label="Checking connection health">
        <span className="shrink-0 w-1.5 h-1.5 rounded-full bg-surface-3 animate-pulse" />
      </span>
    );
  }

  const status: HealthStatus = (health?.status as HealthStatus) ?? "unknown";
  const dotClass = STATUS_DOT_CLASSES[status];

  const tooltipLines = [
    `Status: ${status}`,
    health?.latency_ms ? `Latency: ${health.latency_ms}ms` : null,
    `Checked: ${formatCheckTime(health?.last_check ?? null)}`,
    health?.last_error ? `Error: ${health.last_error}` : null,
  ]
    .filter(Boolean)
    .join(" | ");

  return (
    <span className="inline-flex items-center gap-1">
      <Tooltip label={tooltipLines} position="bottom">
        <span
          className={`shrink-0 w-1.5 h-1.5 rounded-full inline-block ${dotClass} ${
            status === "degraded" ? "animate-pulse-dot" : ""
          }`}
          role="img"
          aria-label={`Connection health: ${status}`}
        />
      </Tooltip>
      {status === "down" && (
        <button
          type="button"
          onClick={handleReconnect}
          disabled={reconnecting}
          className="text-[8px] px-1 py-px rounded-full bg-error-muted text-error hover:bg-error/20 outline-none focus-visible:ring-2 focus-visible:ring-accent leading-none disabled:opacity-50"
        >
          {reconnecting ? "..." : "RECONNECT"}
        </button>
      )}
    </span>
  );
}
