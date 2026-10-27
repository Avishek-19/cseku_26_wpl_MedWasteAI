"use client";

import { useEffect,type DependencyList,type EffectCallback } from "react";

/** Start asynchronous workspace initialization after the committed render.
 * Cancels queued work and runs subscription cleanup on unmount / dependency change.
 * Keeping callback identity controlled by the caller avoids render loops.
 */
export function useDeferredEffect(effect: EffectCallback, dependencies: DependencyList) {
  useEffect(() => {
    let cancelled = false;
    let cleanup: ReturnType<EffectCallback>;
    queueMicrotask(() => { if (!cancelled) cleanup = effect(); });
    return () => { cancelled = true; if (typeof cleanup === "function") cleanup(); };
    // Call sites declare the same dependency contract as React.useEffect.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, dependencies);
}
