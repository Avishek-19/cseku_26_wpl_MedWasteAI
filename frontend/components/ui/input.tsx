import * as React from "react";

import { cn } from "@/lib/utils";

const Input = React.forwardRef<HTMLInputElement, React.InputHTMLAttributes<HTMLInputElement>>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        ref={ref}
        className={cn(
          "mw-input flex h-11 w-full rounded-md border border-mist-deep bg-paper px-3.5 text-[14.5px] text-charcoal placeholder:text-slate-light transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald focus-visible:border-emerald",
          "disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        {...props}
      />
    );
  }
);
Input.displayName = "Input";

export { Input };
