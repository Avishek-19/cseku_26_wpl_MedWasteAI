export default function DashboardLoading() {
  return (
    <main className="flex min-h-[60vh] items-center justify-center" aria-busy="true" aria-live="polite">
      <div className="w-full max-w-2xl space-y-4 px-6">
        <div className="h-8 w-48 animate-pulse rounded-lg bg-mist" />
        <div className="h-24 animate-pulse rounded-2xl bg-mist" />
        <div className="h-48 animate-pulse rounded-2xl bg-mist" />
        <p className="text-center text-sm text-slate">Loading your workspace…</p>
      </div>
    </main>
  );
}
