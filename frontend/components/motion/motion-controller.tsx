"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";
import { useMotionPreference } from "./motion-preference";

/** Progressive enhancement: server-rendered content stays visible without JS. */
export function MotionController() {
  const pathname = usePathname();
  const preference = useMotionPreference();

  useEffect(() => {
    const root = document.documentElement;
    root.dataset.motion = preference === "enabled" ? "on" : "off";
    if (preference !== "enabled" || !("IntersectionObserver" in window)) return;

    const reveals = Array.from(document.querySelectorAll<HTMLElement>("[data-reveal]"));
    const art = Array.from(document.querySelectorAll<HTMLElement>("[data-motion-art]"));
    const observer = new IntersectionObserver(entries => {
      for (const entry of entries) {
        if (!entry.isIntersecting) continue;
        (entry.target as HTMLElement).dataset.revealState = "entered";
        observer.unobserve(entry.target);
      }
    }, { rootMargin: "0px 0px -24px 0px", threshold: 0.08 });
    for (const element of reveals) {
      // Only hide content that has not entered the viewport, avoiding an initial flash.
      if (element.getBoundingClientRect().top >= window.innerHeight) {
        element.dataset.revealState = "waiting";
        observer.observe(element);
      }
    }
    const artObserver = new IntersectionObserver(entries => {
      for (const entry of entries) (entry.target as HTMLElement).dataset.inView = String(entry.isIntersecting);
    });
    art.forEach(element => artObserver.observe(element));
    const onVisibility = () => { root.dataset.documentHidden = String(document.hidden); };
    const onFocus = (event: FocusEvent) => {
      if (!(event.target instanceof Element)) return;
      const element = event.target.closest<HTMLElement>('[data-reveal-state="waiting"]');
      if (element) { element.dataset.revealState = "entered"; observer.unobserve(element); }
    };
    onVisibility();
    document.addEventListener("visibilitychange", onVisibility);
    document.addEventListener("focusin", onFocus);
    return () => {
      observer.disconnect();
      artObserver.disconnect();
      reveals.forEach(element => { delete element.dataset.revealState; });
      document.removeEventListener("visibilitychange", onVisibility);
      document.removeEventListener("focusin", onFocus);
    };
  }, [pathname, preference]);

  return null;
}
