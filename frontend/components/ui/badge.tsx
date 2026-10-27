import { cva,type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-[11px] font-medium uppercase tracking-[0.12em]",
  {
    variants: {
      variant: {
        default: "border-mist-deep bg-mist text-charcoal",
        emerald: "border-emerald/20 bg-signal-emerald-bg text-emerald-dim",
        amber: "border-signal-amber/20 bg-signal-amber-bg text-signal-amber",
        rust: "border-signal-rust/20 bg-signal-rust-bg text-signal-rust",
        dark: "border-white/10 bg-white/5 text-mist",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge,badgeVariants };
