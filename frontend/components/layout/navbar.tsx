"use client";

import { Menu, X } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { BrandMark } from "@/components/layout/brand-mark";
import { MotionToggle } from "@/components/motion/motion-toggle";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const NAV_LINKS = [
  { href: "#solution", label: "Platform" },
  { href: "#lifecycle", label: "Lifecycle" },
  { href: "#network", label: "Network" },
  { href: "#trust", label: "Trust" },
];

export function Navbar() {
  const [scrolled, setScrolled] = useState(false);
  const [open, setOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 12);
    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);
  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setOpen(false); menuButton.current?.focus(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return <header className={cn("premium-nav fixed inset-x-0 top-0 z-50 border-b transition-all duration-300", scrolled || open ? "premium-nav-scrolled border-[#e7dfec] bg-[#fdfbfe]/95 backdrop-blur-xl" : "border-transparent bg-transparent")}>
    <nav aria-label="Main navigation" className="mx-auto flex h-14 max-w-7xl items-center justify-between gap-4 px-6 lg:px-8">
      <Link href="/" aria-label="MedWaste AI home" className="flex items-center gap-2.5"><BrandMark /><span className="font-display text-[16px] font-semibold tracking-tight text-charcoal">MedWaste <span className="text-[#86639e]">AI</span></span></Link>
      <div className="hidden items-center gap-7 md:flex">{NAV_LINKS.map(link => <a key={link.href} href={link.href} className="nav-link text-[12px] font-medium text-slate transition-colors hover:text-charcoal">{link.label}</a>)}</div>
      <div className="flex items-center gap-2">
        <MotionToggle compact />
        <div className="hidden items-center gap-2 md:flex"><Button variant="ghost" size="sm" asChild><Link href="/login">Sign in</Link></Button><Button size="sm" asChild><Link href="/register">Get started</Link></Button></div>
        <button ref={menuButton} type="button" className="grid size-9 place-items-center rounded-lg text-charcoal hover:bg-white/70 md:hidden" onClick={() => setOpen(value => !value)} aria-label={open ? "Close menu" : "Open menu"} aria-expanded={open} aria-controls="public-mobile-menu">{open ? <X size={20} /> : <Menu size={20} />}</button>
      </div>
    </nav>
    {open && <div id="public-mobile-menu" className="mobile-menu-enter border-t border-mist-deep bg-[#fdfbfe] px-6 py-5 md:hidden"><div className="flex flex-col gap-1">{NAV_LINKS.map(link => <a key={link.href} href={link.href} onClick={() => setOpen(false)} className="rounded-lg px-2 py-3 text-sm font-medium text-charcoal hover:bg-mist">{link.label}</a>)}<div className="mt-4 grid grid-cols-2 gap-3"><Button variant="outline" size="sm" asChild><Link href="/login" onClick={() => setOpen(false)}>Sign in</Link></Button><Button size="sm" asChild><Link href="/register" onClick={() => setOpen(false)}>Get started</Link></Button></div></div></div>}
  </header>;
}
