import React from "react";
import { Button } from "@/components/ui/button";

interface RouteCrashBoundaryProps {
  children: React.ReactNode;
  routeLabel?: string;
}

interface RouteCrashBoundaryState {
  error: Error | null;
}

export class RouteCrashBoundary extends React.Component<
  RouteCrashBoundaryProps,
  RouteCrashBoundaryState
> {
  state: RouteCrashBoundaryState = {
    error: null,
  };

  static getDerivedStateFromError(error: Error): RouteCrashBoundaryState {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo) {
    console.error("[dashboard route crash]", {
      route: this.props.routeLabel ?? "unknown",
      error,
      componentStack: info.componentStack,
    });
  }

  private handleReload = () => {
    window.location.reload();
  };

  render() {
    const { error } = this.state;
    if (!error) {
      return this.props.children;
    }

    return (
      <div className="flex min-h-0 w-full flex-1 items-start justify-center px-4 py-8">
        <div className="w-full max-w-3xl rounded-[calc(var(--theme-radius)+0.55rem)] border border-destructive/30 bg-white/92 p-5 shadow-[0_24px_80px_-44px_rgba(190,75,73,0.35)]">
          <div className="font-expanded text-sm tracking-[0.08em] text-destructive">
            Dashboard route crashed
          </div>
          <p className="mt-2 text-sm leading-6 text-foreground">
            {this.props.routeLabel
              ? `The ${this.props.routeLabel} view hit a frontend runtime error.`
              : "This view hit a frontend runtime error."}
          </p>
          <pre className="mt-4 overflow-x-auto rounded-[calc(var(--theme-radius)-0.05rem)] border border-destructive/15 bg-destructive/5 px-3 py-3 font-mono text-xs leading-6 text-foreground">
            {error.stack || error.message}
          </pre>
          <div className="mt-4 flex justify-end">
            <Button type="button" size="sm" variant="outline" onClick={this.handleReload}>
              Reload page
            </Button>
          </div>
        </div>
      </div>
    );
  }
}
