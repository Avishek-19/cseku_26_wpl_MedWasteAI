import { AuthProvider } from "@/hooks/use-auth";
import "leaflet/dist/leaflet.css";
import type { Metadata } from "next";
import "./globals.css";
import "./premium.css";
import { MotionController } from "@/components/motion/motion-controller";

export const metadata: Metadata = {
  title: "MedWaste AI — Smarter Medical Waste Management",
  description:
    "MedWaste AI connects hospitals, waste collectors and Waste Processing Facilities on one record — from waste report to verified disposal.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="h-full antialiased">
      <body className="min-h-full flex flex-col bg-paper text-charcoal">
        <a href="#main-content" className="skip-link">Skip to content</a>
        <MotionController />
        <AuthProvider>{children}</AuthProvider>
      </body>
    </html>
  );
}