"use client";

import { useId, useState, useRef, useEffect, useCallback } from "react";
import { createPortal } from "react-dom";

type Placement = "top" | "bottom" | "right";

interface TooltipProps {
  label: string;
  position?: Placement;
  children: React.ReactNode;
}

function getCoords(
  trigger: DOMRect,
  popup: DOMRect,
  placement: Placement,
  gap: number,
): { top: number; left: number } {
  let top = 0;
  let left = 0;
  switch (placement) {
    case "top":
      top = trigger.top - popup.height - gap;
      left = trigger.left + trigger.width / 2 - popup.width / 2;
      break;
    case "right":
      top = trigger.top + trigger.height / 2 - popup.height / 2;
      left = trigger.right + gap;
      break;
    case "bottom":
    default:
      top = trigger.bottom + gap;
      left = trigger.left + trigger.width / 2 - popup.width / 2;
      break;
  }
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const pad = 6;
  if (left < pad) left = pad;
  if (left + popup.width > vw - pad) left = vw - pad - popup.width;
  if (top < pad) top = pad;
  if (top + popup.height > vh - pad) top = vh - pad - popup.height;
  return { top, left };
}

export function Tooltip({ label, position = "bottom", children }: TooltipProps) {
  const id = useId();
  const [visible, setVisible] = useState(false);
  const triggerRef = useRef<HTMLSpanElement>(null);
  const tooltipRef = useRef<HTMLSpanElement>(null);
  const delayRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const [style, setStyle] = useState<React.CSSProperties>({
    position: "fixed",
    zIndex: 9999,
    top: 0,
    left: 0,
    visibility: "hidden",
  });

  const reposition = useCallback(() => {
    const trigger = triggerRef.current;
    const tip = tooltipRef.current;
    if (!trigger || !tip) return;
    const tRect = trigger.getBoundingClientRect();
    const pRect = tip.getBoundingClientRect();
    const coords = getCoords(tRect, pRect, position, 6);
    setStyle({
      position: "fixed",
      zIndex: 9999,
      top: coords.top,
      left: coords.left,
      visibility: "visible",
    });
  }, [position]);

  useEffect(() => {
    if (!visible) return;
    reposition();
  }, [visible, reposition]);

  useEffect(() => {
    return () => clearTimeout(delayRef.current);
  }, []);

  if (!label) return <>{children}</>;

  const show = () => {
    clearTimeout(delayRef.current);
    delayRef.current = setTimeout(() => setVisible(true), 200);
  };
  const hide = () => {
    clearTimeout(delayRef.current);
    setVisible(false);
  };

  return (
    <span
      ref={triggerRef}
      className="relative inline-flex"
      aria-describedby={visible ? id : undefined}
      onMouseEnter={show}
      onMouseLeave={hide}
      onFocus={show}
      onBlur={hide}
    >
      {children}
      {visible &&
        createPortal(
          <span
            ref={tooltipRef}
            id={id}
            role="tooltip"
            style={style}
            className="pointer-events-none whitespace-nowrap px-2 py-1 rounded-md text-[10px] font-medium leading-none bg-surface-3 text-text-primary border border-border-default animate-tooltip-in"
          >
            {label}
          </span>,
          document.body,
        )}
    </span>
  );
}
