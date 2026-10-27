import { cn } from "@/lib/utils";
import type { LucideIcon } from "lucide-react";

const TONE_STYLES = {
  default: {
    value: "text-charcoal",
    iconBg: "rgba(132,96,172,0.12)",
    iconColor: "#4e2d7d",
  },
  emerald: {
    value: "text-[#553089]",
    iconBg: "rgba(132,96,172,0.12)",
    iconColor: "#5f3d8f",
  },
  amber: {
    value: "text-[#e67e22]",
    iconBg: "rgba(230,126,34,0.12)",
    iconColor: "#e67e22",
  },
  rust: {
    value: "text-[#d64545]",
    iconBg: "rgba(214,69,69,0.12)",
    iconColor: "#d64545",
  },
  muted: {
    value: "text-slate",
    iconBg: "rgba(132,96,172,0.1)",
    iconColor: "#6c40ab",
  },
} as const;

export function StatCard({
  label,
  value,
  tone = "default",
  hint,
  icon: Icon,
}: {
  label: string;
  value: string;
  tone?: keyof typeof TONE_STYLES;
  hint?: string;
  icon?: LucideIcon;
}) {
  const styles = TONE_STYLES[tone];

  return (
    <div
      className={cn(
        "workspace-stat group relative overflow-hidden rounded-2xl border border-mist-deep bg-paper p-5 shadow-sm transition-all duration-300",
        "hover:-translate-y-1 hover:shadow-lg hover:border-[#6c40ab]/40"
      )}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-slate-light">
            {label}
          </p>
          <p
            className={cn(
              "mt-2 font-display text-[1.6rem] font-semibold leading-none tracking-tight",
              styles.value
            )}
          >
            {value}
          </p>
          {hint && (
            <p className="mt-2 text-[11.5px] leading-snug text-slate-light">
              {hint}
            </p>
          )}
        </div>

        {Icon && (
          <div
            className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl transition-transform duration-300 group-hover:scale-110"
            style={{
              background: `radial-gradient(circle at 30% 30%, rgba(255,255,255,0.9), ${styles.iconBg})`,
              boxShadow:
                "0 4px 14px rgba(132,96,172,0.15), inset 0 1px 0 rgba(255,255,255,0.8)",
              color: styles.iconColor,
              border: "1px solid rgba(132,96,172,0.2)",
            }}
          >
            <Icon size={22} strokeWidth={1.75} />
          </div>
        )}
      </div>
    </div>
  );
}