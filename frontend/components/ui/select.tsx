import { ChevronDown } from "lucide-react";
import * as React from "react";

import { cn } from "@/lib/utils";

const Select = React.forwardRef<HTMLSelectElement, React.SelectHTMLAttributes<HTMLSelectElement>>(
  ({ className, children, ...props }, ref) => (
    <div className="relative">
      <select
        ref={ref}
        className={cn(
          "mw-input flex h-11 w-full appearance-none rounded-md border border-mist-deep bg-paper px-3.5 pr-9 text-[14.5px] text-charcoal transition-colors",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald focus-visible:border-emerald",
          "disabled:cursor-not-allowed disabled:opacity-50",
          className
        )}
        {...props}
      >
        {children}
      </select>
      <ChevronDown
        size={15}
        className="pointer-events-none absolute right-3.5 top-1/2 -translate-y-1/2 text-slate-light"
      />
    </div>
  )
);
Select.displayName = "Select";

export { Select };
