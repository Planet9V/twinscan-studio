import * as React from "react";
import { cn } from "@/lib/utils";

export const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, ...props }, ref) => (
    <input
      ref={ref}
      className={cn(
        "flex h-8 w-full rounded-md border border-white/15 bg-eigenia-obsidian px-2.5 py-1 text-xs text-white placeholder:text-eigenia-muted/60 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-eigenia-orange disabled:opacity-50",
        className
      )}
      {...props}
    />
  )
);
Input.displayName = "Input";
