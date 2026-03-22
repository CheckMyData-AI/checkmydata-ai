"use client";

import { useEffect, useLayoutEffect, useState, useCallback, type ReactNode } from "react";
import { createPortal } from "react-dom";

export type Placement = "top" | "bottom" | "right" | "bottom-right" | "top-left";

interface PopoverPortalProps {
  triggerRef: React.RefObject<HTMLElement | null>;
  placement: Placement;
  children: ReactNode;
  gap?: number;
  className?: string;
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
    case "bottom":
      top = trigger.bottom + gap;
      left = trigger.left + trigger.width / 2 - popup.width / 2;
      break;
    case "bottom-right":
      top = trigger.bottom + gap;
      left = trigger.right - popup.width;
      break;
    case "top":
      top = trigger.top - popup.height - gap;
      left = trigger.left + trigger.width / 2 - popup.width / 2;
      break;
    case "top-left":
      top = trigger.top - popup.height - gap;
      left = trigger.left;
      break;
    case "right":
      top = trigger.top + trigger.height / 2 - popup.height / 2;
      left = trigger.right + gap;
      break;
  }

  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const pad = 8;

  if (left < pad) left = pad;
  if (left + popup.width > vw - pad) left = vw - pad - popup.width;
  if (top < pad) top = pad;
  if (top + popup.height > vh - pad) top = vh - pad - popup.height;

  return { top, left };
}

export function PopoverPortal({
  triggerRef,
  placement,
  children,
  gap = 6,
  className = "",
}: PopoverPortalProps) {
  const [style, setStyle] = useState<React.CSSProperties>({
    position: "fixed",
    zIndex: 9999,
    visibility: "hidden",
    top: 0,
    left: 0,
  });
  const [popupRef, setPopupRef] = useState<HTMLDivElement | null>(null);

  const reposition = useCallback(() => {
    const trigger = triggerRef.current;
    if (!trigger || !popupRef) return;
    const tRect = trigger.getBoundingClientRect();
    const pRect = popupRef.getBoundingClientRect();
    const { top, left } = getCoords(tRect, pRect, placement, gap);
    setStyle({
      position: "fixed",
      zIndex: 9999,
      top,
      left,
      visibility: "visible",
    });
  }, [triggerRef, popupRef, placement, gap]);

  useLayoutEffect(() => {
    reposition();
  }, [reposition]);

  useEffect(() => {
    if (!popupRef) return;
    window.addEventListener("scroll", reposition, true);
    window.addEventListener("resize", reposition);
    return () => {
      window.removeEventListener("scroll", reposition, true);
      window.removeEventListener("resize", reposition);
    };
  }, [popupRef, reposition]);

  return createPortal(
    <div ref={setPopupRef} style={style} className={className}>
      {children}
    </div>,
    document.body,
  );
}
