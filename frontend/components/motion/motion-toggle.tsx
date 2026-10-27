"use client";

import { Pause, Play } from "lucide-react";
import { cn } from "@/lib/utils";
import { toggleMotion, useMotionPreference } from "./motion-preference";

export function MotionToggle({ compact = false, className }: { compact?: boolean; className?: string }) {
  const preference = useMotionPreference();
  const enabled = preference === "enabled";
  const label = preference === "reduced" ? "Animations reduced by device settings" : enabled ? "Pause interface animations" : "Enable interface animations";
  return (
    <button type="button" onClick={toggleMotion} aria-label={label} aria-pressed={!enabled}
      disabled={preference === "reduced"} title={label}
      className={cn("motion-toggle", compact && "motion-toggle-compact", className)}>
      {enabled ? <Pause size={13} aria-hidden="true" /> : <Play size={13} aria-hidden="true" />}
      {!compact && <span>{enabled ? "Motion on" : "Motion paused"}</span>}
    </button>
  );
}
