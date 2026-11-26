"use client";

import React, { useState } from "react";
import { ChevronDown, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

export interface InteractiveSurfaceProps {
  title?: string;
  subtitle?: string;
  badge?: React.ReactNode;
  accent?: "none" | "sky" | "orange" | "emerald" | "amber" | "fault";
  headerRight?: React.ReactNode;
  collapsible?: boolean;
  defaultCollapsed?: boolean;
  hoverable?: boolean;
  className?: string;
  contentClassName?: string;
  children: React.ReactNode;
}

const ACCENT_TOP_CLASS: Record<NonNullable<InteractiveSurfaceProps["accent"]>, string> = {
  none: "",
  sky: "border-t-2 border-t-eigenia-sky/75",
  orange: "border-t-2 border-t-eigenia-orange/85",
  emerald: "border-t-2 border-t-emerald-400/80",
  amber: "border-t-2 border-t-eigenia-amber/80",
  fault: "border-t-2 border-t-eigenia-fault/85",
};

export function InteractiveSurface({
  title,
  subtitle,
  badge,
  accent = "none",
  headerRight,
  collapsible = false,
  defaultCollapsed = false,
  hoverable = true,
  className,
  contentClassName,
  children,
}: InteractiveSurfaceProps): React.JSX.Element {
  const [collapsed, setCollapsed] = useState(defaultCollapsed);
  const hasHeader = Boolean(title || subtitle || badge || headerRight || collapsible);

  return (
    <div
      className={cn(
        "rounded-lg border border-white/10 bg-eigenia-surface text-eigenia-ink shadow-sm transition-all duration-200 motion-reduce:transition-none",
        hoverable &&
          "hover:-translate-y-0.5 hover:border-eigenia-sky/35 hover:shadow-[0_8px_28px_rgba(0,0,0,0.45)] motion-reduce:hover:translate-y-0",
        ACCENT_TOP_CLASS[accent],
        className
      )}
    >
      {hasHeader && (
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-white/10 px-4 py-3">
          <div className="flex min-w-0 items-center gap-2">
            {collapsible && (
              <button
                type="button"
                onClick={() => setCollapsed((v) => !v)}
                aria-expanded={!collapsed}
                aria-label={collapsed ? "Expand section" : "Collapse section"}
                className="rounded p-0.5 text-eigenia-muted transition-colors hover:bg-white/10 hover:text-white"
              >
                {collapsed ? (
                  <ChevronRight className="h-4 w-4" />
                ) : (
                  <ChevronDown className="h-4 w-4" />
                )}
              </button>
            )}
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                {title && (
                  <h3 className="truncate text-xs font-semibold uppercase tracking-wider text-white">
                    {title}
                  </h3>
                )}
                {badge}
              </div>
              {subtitle && (
                <p className="mt-0.5 truncate text-[11px] text-eigenia-muted">{subtitle}</p>
              )}
            </div>
          </div>
          {headerRight && <div className="flex items-center gap-2">{headerRight}</div>}
        </div>
      )}

      {!collapsed && <div className={cn("p-4", contentClassName)}>{children}</div>}
    </div>
  );
}
