"use client";

import React, { useEffect, useState } from "react";
import { X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export interface SlideOverDrawerProps {
  open: boolean;
  onClose: () => void;
  title: string;
  subtitle?: string;
  badge?: string;
  badgeVariant?: "default" | "sky" | "amber" | "fault" | "neutral";
  widthClassName?: string;
  footer?: React.ReactNode;
  children: React.ReactNode;
}

export function SlideOverDrawer({
  open,
  onClose,
  title,
  subtitle,
  badge,
  badgeVariant = "sky",
  widthClassName = "max-w-lg",
  footer,
  children,
}: SlideOverDrawerProps): React.JSX.Element | null {
  const [entered, setEntered] = useState(false);

  useEffect(() => {
    if (!open) {
      setEntered(false);
      return;
    }
    const raf = window.requestAnimationFrame(() => setEntered(true));
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      window.cancelAnimationFrame(raf);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={title}
      className="fixed inset-0 z-50 flex justify-end"
    >
      {/* Backdrop */}
      <div
        onClick={onClose}
        aria-hidden="true"
        className={cn(
          "fixed inset-0 bg-black/55 backdrop-blur-sm transition-opacity duration-200 motion-reduce:transition-none",
          entered ? "opacity-100" : "opacity-0"
        )}
      />

      {/* Right-Side Gliding Sheet */}
      <aside
        className={cn(
          "relative z-10 flex h-full w-full flex-col border-l border-white/15 bg-eigenia-shell shadow-2xl transition-transform duration-200 ease-out motion-reduce:transition-none",
          widthClassName,
          entered ? "translate-x-0" : "translate-x-full"
        )}
      >
        {/* Sticky Header */}
        <div className="flex items-start justify-between gap-3 border-b border-white/10 bg-eigenia-obsidian/90 px-4 py-3.5">
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              {badge && <Badge variant={badgeVariant}>{badge}</Badge>}
              <h2 className="truncate font-mono text-sm font-bold tracking-wide text-white">
                {title}
              </h2>
            </div>
            {subtitle && (
              <p className="truncate text-xs text-eigenia-muted">{subtitle}</p>
            )}
          </div>
          <Button
            type="button"
            size="icon"
            variant="ghost"
            onClick={onClose}
            aria-label="Close drawer"
            className="h-7 w-7 shrink-0"
          >
            <X className="h-4 w-4" />
          </Button>
        </div>

        {/* Scrollable Body */}
        <div className="flex-1 overflow-y-auto p-4">{children}</div>

        {/* Optional Sticky Footer */}
        {footer && (
          <div className="border-t border-white/10 bg-eigenia-obsidian/90 px-4 py-3">
            {footer}
          </div>
        )}
      </aside>
    </div>
  );
}
