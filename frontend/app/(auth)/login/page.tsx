import Link from "next/link";

import { AuthShell } from "@/components/auth/auth-shell";
import { LoginForm } from "@/components/auth/login-form";

export default function LoginPage() {
  return (
    <AuthShell
      eyebrow="Welcome back"
      title="Sign in to MedWaste AI"
      description="Access your hospital, collector or Waste Processing Facility workspace."
      footer={
        <>
          Don&apos;t have an account?{" "}
          <Link href="/register" className="font-medium text-emerald hover:underline">
            Register your organization
          </Link>
        </>
      }
    >
      <LoginForm />
    </AuthShell>
  );
}
