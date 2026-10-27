"use client";
import { Button } from "@/components/ui/button";
export default function ErrorPage({ reset }: { error: Error & { digest?: string }; reset: () => void }) {
  return <main id="main-content" className="grid min-h-[75vh] place-items-center bg-mist p-6"><div className="workspace-panel max-w-md p-9"><p className="eyebrow">Something needs attention</p><h1 className="mt-3 font-display text-2xl font-semibold">This page could not be loaded.</h1><p className="mt-3 text-sm leading-6 text-slate">Please retry. If the issue continues, contact your platform administrator.</p><Button className="mt-6" onClick={reset}>Try again</Button></div></main>;
}
