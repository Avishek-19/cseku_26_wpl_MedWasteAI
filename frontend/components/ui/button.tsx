import { Slot } from "@radix-ui/react-slot";
import { cva,type VariantProps } from "class-variance-authority";
import * as React from "react";

import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "mw-button inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium tracking-tight transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald focus-visible:ring-offset-2 focus-visible:ring-offset-paper disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default:
          "mw-button-primary bg-forest text-paper hover:bg-charcoal shadow-[0_1px_0_0_rgba(255,255,255,0.08)_inset]",
        emerald: "bg-emerald text-paper hover:bg-emerald-dim",
        outline:
          "mw-button-outline border border-mist-deep bg-transparent text-charcoal hover:bg-mist",
        ghost: "text-charcoal hover:bg-mist",
        inverse: "bg-paper text-charcoal hover:bg-mist",
        link: "text-emerald underline-offset-4 hover:underline p-0 h-auto",
      },
      size: {
        default: "h-11 px-5",
        sm: "h-9 px-4 text-[13px]",
        lg: "h-12 px-7 text-[15px]",
        icon: "h-10 w-10",
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
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button,buttonVariants };
