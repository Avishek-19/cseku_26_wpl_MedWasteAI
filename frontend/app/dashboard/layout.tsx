"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { DashboardSidebar } from "@/components/dashboard/sidebar";
import { DashboardTopbar } from "@/components/dashboard/topbar";
import { BrandMark } from "@/components/layout/brand-mark";
import { MotionToggle } from "@/components/motion/motion-toggle";
import { useAuth } from "@/hooks/use-auth";
import { useDeferredEffect } from "@/hooks/use-deferred-effect";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const drawer = useRef<HTMLDivElement>(null);

  useEffect(() => { if (!loading && !user) router.replace("/login"); }, [loading, user, router]);
  useDeferredEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const previousFocus = document.activeElement as HTMLElement | null;
    drawer.current?.querySelector<HTMLButtonElement>('[aria-label="Close navigation"]')?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setOpen(false); return; }
      if (event.key !== "Tab") return;
      const focusable = Array.from(drawer.current?.querySelectorAll<HTMLElement>('a[href], button:not([disabled])') ?? []);
      const first = focusable[0]; const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
    };
    const media = window.matchMedia("(min-width: 1024px)");
    const onWideScreen = (event: MediaQueryListEvent) => { if (event.matches) setOpen(false); };
    window.addEventListener("keydown", onKey);
    media.addEventListener("change", onWideScreen);
    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      window.removeEventListener("keydown", onKey);
      media.removeEventListener("change", onWideScreen);
      document.body.style.overflow = previousOverflow;
      if (previousFocus?.isConnected) previousFocus.focus();
    };
  }, [open]);

  if (loading || !user) return <main id="main-content" className="grid min-h-screen place-items-center bg-[#f8f5fb]"><div className="workspace-loading" role="status"><BrandMark className="size-12" /><p className="text-sm font-medium text-[#705682]">Opening your workspace…</p><span className="workspace-loading-line" aria-hidden="true" /></div></main>;

  return <div className="workspace-shell flex min-h-screen bg-[#f6f5f7] text-[#291e38]">
    <DashboardSidebar />
    <div className="flex min-w-0 flex-1 flex-col" inert={open}>
      <DashboardTopbar onMenuClick={() => setOpen(true)} />
      <main id="main-content" className="workspace-content min-w-0 flex-1 px-4 py-6 md:px-7 md:py-8 xl:px-10"><div className="mx-auto max-w-[1480px]"><div key={pathname} className="page-enter">{children}</div></div></main>
      <footer className="flex flex-wrap items-center justify-center gap-x-5 gap-y-3 border-t border-[#e4e1e9] px-5 py-4 text-center text-[11px] text-[#827b8d]"><span>MedWaste AI · Secure records. Accountable care.</span><MotionToggle /></footer>
    </div>
    {open && <div ref={drawer} role="dialog" aria-modal="true" aria-label="Workspace navigation menu" className="fixed inset-0 z-50 flex lg:hidden"><button type="button" aria-label="Close navigation" onClick={() => setOpen(false)} className="overlay-enter absolute inset-0 bg-[#110a1a]/70" /><div className="drawer-enter relative h-full shadow-2xl"><DashboardSidebar mobile onNavigate={() => setOpen(false)} /></div></div>}
  </div>;
}
