import Link from "next/link";
import { Button } from "@/components/ui/button";
export default function NotFound() {
  return <main id="main-content" className="grid min-h-screen place-items-center bg-mist p-6"><div className="workspace-panel max-w-md p-9"><p className="eyebrow">Page not found</p><h1 className="mt-3 font-display text-2xl font-semibold">Let’s get you back on track.</h1><p className="mt-3 text-sm leading-6 text-slate">This page does not exist or has moved.</p><Button className="mt-6" asChild><Link href="/">Back to MedWaste AI</Link></Button></div></main>;
}
