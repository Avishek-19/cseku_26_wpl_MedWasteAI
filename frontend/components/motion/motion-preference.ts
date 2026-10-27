"use client";

import { useSyncExternalStore } from "react";

const KEY = "medwaste:motion";
const EVENT = "medwaste:motion-change";
const QUERY = "(prefers-reduced-motion: reduce)";
type Preference = "enabled" | "paused" | "reduced";
let sessionPreference: Preference | null = null;

function getSnapshot(): Preference {
  if (window.matchMedia(QUERY).matches) return "reduced";
  if (sessionPreference) return sessionPreference;
  try { return window.localStorage.getItem(KEY) === "paused" ? "paused" : "enabled"; }
  catch { return "enabled"; }
}

function subscribe(callback: () => void) {
  const media = window.matchMedia(QUERY);
  const onStorage = (event: StorageEvent) => { if (event.key === KEY || event.key === null) { sessionPreference = null; callback(); } };
  media.addEventListener("change", callback);
  window.addEventListener(EVENT, callback);
  window.addEventListener("storage", onStorage);
  return () => {
    media.removeEventListener("change", callback);
    window.removeEventListener(EVENT, callback);
    window.removeEventListener("storage", onStorage);
  };
}

export function useMotionPreference() {
  return useSyncExternalStore(subscribe, getSnapshot, (): Preference => "enabled");
}

export function toggleMotion() {
  const next = getSnapshot() === "enabled" ? "paused" : "enabled";
  sessionPreference = next;
  try { window.localStorage.setItem(KEY, next); } catch { /* Device preferences still apply when storage is unavailable. */ }
  window.dispatchEvent(new Event(EVENT));
}
