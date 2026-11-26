import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeStyles = cva(
  "inline-flex items-center gap-1 rounded px-2 py-0.5 font-mono text-[10px] font-medium uppercase tracking-wide border",
  {
    variants: {
      variant: {
        default: "border-eigenia-orange/40 bg-eigenia-orange/15 text-eigenia-orange",
        sky: "border-eigenia-sky/35 bg-eigenia-sky/10 text-eigenia-sky",
        amber: "border-eigenia-amber/40 bg-eigenia-amber/15 text-eigenia-amber",
        fault: "border-eigenia-fault/40 bg-eigenia-fault/15 text-eigenia-fault",
        neutral: "border-white/15 bg-white/5 text-eigenia-muted",
      },
    },
    defaultVariants: {
      variant: "neutral",
    },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeStyles> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeStyles({ variant }), className)} {...props} />;
}
