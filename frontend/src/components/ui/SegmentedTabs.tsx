"use client";

import React from "react";
import { cn } from "@/lib/utils";

export interface SegmentedTabItem {
  id: string;
  label: string;
  icon?: React.ReactNode;
  count?: number | string;
  alertTone?: "ok" | "warning" | "fault" | null;
}

export interface SegmentedTabsProps {
  tabs: SegmentedTabItem[];
  value: string;
  onValueChange: (nextId: string) => void;
  rightSlot?: React.ReactNode;
  className?: string;
}

const ALERT_DOT_CLASS: Record<"ok" | "warning" | "fault", string> = {
  ok: "bg-emerald-400",
  warning: "bg-eigenia-amber",
  fault: "bg-eigenia-fault",
};

export function SegmentedTabs({
  tabs,
  value,
  onValueChange,
  rightSlot,
  className,
}: SegmentedTabsProps): React.JSX.Element {
  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-2 rounded-lg border border-white/10 bg-eigenia-obsidian/90 p-1.5",
        className
      )}
    >
      <div role="tablist" className="flex flex-wrap items-center gap-1">
        {tabs.map((tab) => {
          const isActive = tab.id === value;
          return (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={isActive}
              onClick={() => onValueChange(tab.id)}
              className={cn(
                "inline-flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-medium transition-all duration-200 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-eigenia-orange motion-reduce:transition-none",
                isActive
                  ? "border-eigenia-orange/50 bg-eigenia-orange/15 text-white shadow-[0_0_16px_rgba(224,90,16,0.18)]"
                  : "border-transparent text-eigenia-muted hover:border-white/10 hover:bg-white/5 hover:text-white"
              )}
            >
              {tab.icon && (
                <span className={cn("shrink-0", isActive ? "text-eigenia-orange" : "text-eigenia-muted")}>
                  {tab.icon}
                </span>
              )}
              <span>{tab.label}</span>
              {tab.count !== undefined && tab.count !== null && (
                <span
                  className={cn(
                    "rounded px-1.5 py-0.5 font-mono text-[10px] leading-none",
                    isActive
                      ? "bg-eigenia-orange/25 text-white"
                      : "bg-white/5 text-eigenia-muted"
                  )}
                >
                  {tab.count}
                </span>
              )}
              {tab.alertTone && (
                <span className="relative ml-0.5 flex h-2 w-2 shrink-0">
                  {(tab.alertTone === "warning" || tab.alertTone === "fault") && (
                    <span
                      className={cn(
                        "absolute inline-flex h-full w-full animate-ping rounded-full opacity-75 motion-reduce:animate-none",
                        ALERT_DOT_CLASS[tab.alertTone]
                      )}
                    />
                  )}
                  <span
                    className={cn(
                      "relative inline-flex h-2 w-2 rounded-full",
                      ALERT_DOT_CLASS[tab.alertTone]
                    )}
                  />
                </span>
              )}
            </button>
          );
        })}
      </div>

      {rightSlot && <div className="flex flex-wrap items-center gap-2">{rightSlot}</div>}
    </div>
  );
}
