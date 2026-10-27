"use client";

import { useEffect } from "react";

export default function DashboardError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => { console.error(error); }, [error]);
  return (
    <main className="flex min-h-[60vh] items-center justify-center px-6">
      <section className="w-full max-w-lg rounded-2xl border border-mist-deep bg-paper p-8 text-center shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-[0.18em] text-forest">Something went wrong</p>
        <h1 className="mt-3 text-2xl font-semibold text-charcoal">We couldn’t load this workspace.</h1>
        <p className="mt-3 text-sm leading-6 text-slate">Your data is safe. Try again, and if the issue continues, check the API connection.</p>
        <button onClick={() => reset()} className="mt-6 rounded-xl bg-forest px-5 py-2.5 text-sm font-semibold text-white transition hover:opacity-90 focus:outline-none focus:ring-2 focus:ring-forest focus:ring-offset-2">
          Try again
        </button>
      </section>
    </main>
  );
}
