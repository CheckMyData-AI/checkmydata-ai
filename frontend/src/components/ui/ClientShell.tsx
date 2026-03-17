"use client";

import { ErrorBoundary } from "./ErrorBoundary";
import { ToastContainer } from "./ToastContainer";
import { ConfirmModal } from "./ConfirmModal";

export function ClientShell({ children }: { children: React.ReactNode }) {
  return (
    <ErrorBoundary>
      {children}
      <ToastContainer />
      <ConfirmModal />
    </ErrorBoundary>
  );
}
