import * as React from "react";

import { cn } from "@/lib/utils";

const Textarea = React.forwardRef<
  HTMLTextAreaElement,
  React.TextareaHTMLAttributes<HTMLTextAreaElement>
>(({ className, ...props }, ref) => {
  return (
    <textarea
      ref={ref}
      className={cn(
        "flex min-h-24 w-full rounded-md border border-mist-deep bg-paper px-3.5 py-2.5 text-[14.5px] text-charcoal placeholder:text-slate-light transition-colors",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald focus-visible:border-emerald",
        "disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    />
  );
});
Textarea.displayName = "Textarea";

export { Textarea };
