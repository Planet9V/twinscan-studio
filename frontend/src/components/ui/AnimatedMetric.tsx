"use client";

import React, { useEffect, useRef, useState } from "react";
import { cn } from "@/lib/utils";

export interface AnimatedMetricProps {
  label: string;
  value: number | string | null | undefined;
  unit?: string;
  decimals?: number;
  tone?: "default" | "sky" | "orange" | "emerald" | "amber" | "fault";
  pulse?: boolean;
  progressPct?: number | null;
  hint?: string;
  compact?: boolean;
  className?: string;
}

const TONE_VALUE_CLASS: Record<NonNullable<AnimatedMetricProps["tone"]>, string> = {
  default: "text-white",
  sky: "text-eigenia-sky",
  orange: "text-eigenia-orange",
  emerald: "text-emerald-400",
  amber: "text-eigenia-amber",
  fault: "text-eigenia-fault",
};

const TONE_DOT_CLASS: Record<NonNullable<AnimatedMetricProps["tone"]>, string> = {
  default: "bg-eigenia-muted",
  sky: "bg-eigenia-sky",
  orange: "bg-eigenia-orange",
  emerald: "bg-emerald-400",
  amber: "bg-eigenia-amber",
  fault: "bg-eigenia-fault",
};

const TONE_BAR_CLASS: Record<NonNullable<AnimatedMetricProps["tone"]>, string> = {
  default: "bg-white/60",
  sky: "bg-eigenia-sky",
  orange: "bg-eigenia-orange",
  emerald: "bg-emerald-400",
  amber: "bg-eigenia-amber",
  fault: "bg-eigenia-fault",
};

export function AnimatedMetric({
  label,
  value,
  unit,
  decimals = 1,
  tone = "default",
  pulse = false,
  progressPct = null,
  hint,
  compact = false,
  className,
}: AnimatedMetricProps): React.JSX.Element {
  const isNumeric = typeof value === "number" && Number.isFinite(value);
  const targetNum = isNumeric ? value : null;

  const [displayNum, setDisplayNum] = useState<number | null>(targetNum);
  const prevNumRef = useRef<number | null>(targetNum);

  useEffect(() => {
    if (targetNum === null) {
      prevNumRef.current = null;
      setDisplayNum(null);
      return;
    }

    const startVal = prevNumRef.current;
    prevNumRef.current = targetNum;

    const prefersReduced =
      typeof window !== "undefined" &&
      window.matchMedia &&
      window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    if (startVal === null || prefersReduced || Math.abs(targetNum - startVal) < 1e-6) {
      setDisplayNum(targetNum);
      return;
    }

    const durationMs = 380;
    const startTime = performance.now();
    let rafId = 0;

    const step = (now: number) => {
      const elapsed = now - startTime;
      const t = Math.min(1, elapsed / durationMs);
      // Cubic ease-out
      const eased = 1 - Math.pow(1 - t, 3);
      setDisplayNum(startVal + (targetNum - startVal) * eased);
      if (t < 1) {
        rafId = window.requestAnimationFrame(step);
      } else {
        setDisplayNum(targetNum);
      }
    };

    rafId = window.requestAnimationFrame(step);
    return () => window.cancelAnimationFrame(rafId);
  }, [targetNum]);

  const formattedValue =
    targetNum !== null && displayNum !== null
      ? displayNum.toFixed(decimals)
      : value !== null && value !== undefined && String(value).trim() !== ""
      ? String(value)
      : "—";

  const clampedPct =
    progressPct !== null && Number.isFinite(progressPct)
      ? Math.max(0, Math.min(100, progressPct))
      : null;

  return (
    <div
      title={hint}
      className={cn(
        "group rounded-md border border-white/10 bg-eigenia-obsidian/90 transition-all duration-200 hover:border-eigenia-sky/40 hover:bg-eigenia-surface/90 hover:shadow-[0_0_16px_rgba(56,189,248,0.12)] motion-reduce:transition-none",
        compact ? "px-2.5 py-1.5" : "px-3 py-2.5",
        className
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="truncate font-mono text-[10px] uppercase tracking-wider text-eigenia-muted">
          {label}
        </span>
        {pulse && (
          <span className="relative flex h-2 w-2 shrink-0">
            <span
              className={cn(
                "absolute inline-flex h-full w-full animate-ping rounded-full opacity-70 motion-reduce:animate-none",
                TONE_DOT_CLASS[tone]
              )}
            />
            <span className={cn("relative inline-flex h-2 w-2 rounded-full", TONE_DOT_CLASS[tone])} />
          </span>
        )}
      </div>

      <div className="mt-0.5 flex items-baseline gap-1 font-mono">
        <span
          className={cn(
            "font-bold tracking-tight transition-transform duration-200 group-hover:scale-[1.02] motion-reduce:transition-none motion-reduce:group-hover:scale-100",
            compact ? "text-xs" : "text-lg",
            TONE_VALUE_CLASS[tone]
          )}
        >
          {formattedValue}
        </span>
        {unit && formattedValue !== "—" && (
          <span className={cn("text-eigenia-muted", compact ? "text-[10px]" : "text-xs")}>
            {unit}
          </span>
        )}
      </div>

      {hint && !compact && (
        <div className="mt-0.5 truncate font-mono text-[10px] text-eigenia-muted">{hint}</div>
      )}

      {clampedPct !== null && (
        <div className="mt-1.5 h-1 w-full overflow-hidden rounded-full bg-white/10">
          <div
            style={{ width: `${clampedPct}%` }}
            className={cn(
              "h-full rounded-full transition-all duration-300 motion-reduce:transition-none",
              TONE_BAR_CLASS[tone]
            )}
          />
        </div>
      )}
    </div>
  );
}
