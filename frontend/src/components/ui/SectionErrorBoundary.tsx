"use client";

import React from "react";
import { Icon } from "./Icon";

interface Props {
  children: React.ReactNode;
  sectionName?: string;
}

interface State {
  hasError: boolean;
  error: Error | null;
}

export class SectionErrorBoundary extends React.Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, errorInfo: React.ErrorInfo) {
    const section = this.props.sectionName || "unknown";
    console.error(`[SectionErrorBoundary:${section}]`, error, errorInfo.componentStack);
  }

  private handleRetry = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      const name = this.props.sectionName || "This section";
      return (
        <div className="flex flex-col items-center justify-center p-6 gap-3 min-h-[120px]">
          <div className="w-10 h-10 rounded-full bg-error/10 flex items-center justify-center">
            <Icon name="x" size={18} className="text-error" />
          </div>
          <p className="text-sm text-text-secondary text-center">
            {name} encountered an error.
          </p>
          {this.state.error?.message && (
            <p className="text-xs text-text-muted text-center max-w-xs truncate">
              {this.state.error.message}
            </p>
          )}
          <button
            onClick={this.handleRetry}
            className="px-4 py-1.5 text-xs bg-surface-2 hover:bg-surface-3 text-text-secondary rounded-lg transition-colors border border-border-subtle"
          >
            Retry
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
