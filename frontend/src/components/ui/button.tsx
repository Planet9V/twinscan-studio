"use client";

import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonStyles = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-eigenia-orange disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default: "bg-eigenia-orange text-white hover:bg-eigenia-orange/90",
        secondary: "bg-eigenia-surface text-eigenia-ink border border-white/10 hover:bg-white/10",
        outline: "border border-white/15 bg-transparent text-eigenia-ink hover:bg-white/5",
        ghost: "text-eigenia-muted hover:bg-white/5 hover:text-white",
        destructive: "bg-eigenia-fault/20 text-eigenia-fault border border-eigenia-fault/40 hover:bg-eigenia-fault/30",
        sky: "bg-eigenia-sky/15 text-eigenia-sky border border-eigenia-sky/35 hover:bg-eigenia-sky/25",
      },
      size: {
        default: "h-8 px-3 py-1.5",
        sm: "h-7 px-2.5 text-[11px]",
        lg: "h-9 px-4 text-sm",
        icon: "h-8 w-8",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonStyles> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return <Comp ref={ref} className={cn(buttonStyles({ variant, size }), className)} {...props} />;
  }
);
Button.displayName = "Button";
