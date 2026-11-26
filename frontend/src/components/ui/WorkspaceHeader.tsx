"use client";

import React from "react";
import { Command } from "lucide-react";
import { AnimatedMetric, type AnimatedMetricProps } from "@/components/ui/AnimatedMetric";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface WorkspaceHeaderProps {
  badge: string;
  title: string;
  subtitle?: string;
  statusTone?: "ok" | "warning" | "fault" | "idle";
  statusLabel?: string;
  metrics?: AnimatedMetricProps[];
  actions?: React.ReactNode;
  sticky?: boolean;
  className?: string;
}

const STATUS_DOT_CLASS: Record<NonNullable<WorkspaceHeaderProps["statusTone"]>, string> = {
  ok: "bg-emerald-400",
  warning: "bg-eigenia-amber",
  fault: "bg-eigenia-fault",
  idle: "bg-eigenia-muted",
};

const STATUS_BADGE_VARIANT: Record<
  NonNullable<WorkspaceHeaderProps["statusTone"]>,
  "sky" | "amber" | "fault" | "neutral"
> = {
  ok: "sky",
  warning: "amber",
  fault: "fault",
  idle: "neutral",
};

export function WorkspaceHeader({
  badge,
  title,
  subtitle,
  statusTone = "idle",
  statusLabel,
  metrics,
  actions,
  sticky = true,
  className,
}: WorkspaceHeaderProps): React.JSX.Element {
  const openPalette = () => {
    if (typeof window !== "undefined") {
      window.dispatchEvent(new CustomEvent("eigenia:open-command-palette"));
    }
  };

  return (
    <div
      className={cn(
        "rounded-lg border border-white/10 bg-eigenia-shell/90 px-4 py-3 shadow-sm backdrop-blur-md transition-colors duration-200 motion-reduce:transition-none",
        sticky && "sticky top-[54px] z-20",
        className
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-3">
        {/* Left: Badge, Title, Live Status & Subtitle */}
        <div className="min-w-0 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="default">{badge}</Badge>
            <h1 className="truncate font-mono text-sm font-bold tracking-wider text-white">
              {title}
            </h1>
            {statusLabel && (
              <Badge variant={STATUS_BADGE_VARIANT[statusTone]} className="gap-1.5">
                <span className="relative flex h-2 w-2">
                  {(statusTone === "ok" || statusTone === "warning" || statusTone === "fault") && (
                    <span
                      className={cn(
                        "absolute inline-flex h-full w-full animate-ping rounded-full opacity-70 motion-reduce:animate-none",
                        STATUS_DOT_CLASS[statusTone]
                      )}
                    />
                  )}
                  <span
                    className={cn(
                      "relative inline-flex h-2 w-2 rounded-full",
                      STATUS_DOT_CLASS[statusTone]
                    )}
                  />
                </span>
                {statusLabel}
              </Badge>
            )}
          </div>
          {subtitle && (
            <p className="truncate text-xs text-eigenia-muted">{subtitle}</p>
          )}
        </div>

        {/* Right: Primary Actions + ⌘K Shortcut Hint */}
        <div className="flex flex-wrap items-center gap-2">
          {actions}
          <Button
            type="button"
            size="sm"
            variant="outline"
            onClick={openPalette}
            title="Open Command Palette (⌘K / Ctrl+K)"
            className="h-7 gap-1 border-white/15 bg-eigenia-obsidian/75 px-2 font-mono text-[10px] text-eigenia-muted hover:border-eigenia-sky/50 hover:text-white"
          >
            <Command className="h-3 w-3 text-eigenia-orange" />
            <span>⌘K</span>
          </Button>
        </div>
      </div>

      {/* Optional Compact Animated Metric Strip */}
      {Array.isArray(metrics) && metrics.length > 0 && (
        <div className="mt-2.5 grid grid-cols-2 gap-2 border-t border-white/10 pt-2.5 sm:grid-cols-3 lg:grid-cols-6">
          {metrics.map((metric, idx) => (
            <AnimatedMetric key={`${metric.label}-${idx}`} {...metric} compact />
          ))}
        </div>
      )}
    </div>
  );
}
