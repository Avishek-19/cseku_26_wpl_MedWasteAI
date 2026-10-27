import Link from "next/link";

import { AuthShell } from "@/components/auth/auth-shell";
import { RegisterForm } from "@/components/auth/register-form";

export default function RegisterPage() {
  return (
    <AuthShell
      eyebrow="Get started"
      title="Create your account"
      description="Set up a workspace for your hospital, collector or Waste Processing Facility."
      footer={
        <>
          Already have an account?{" "}
          <Link href="/login" className="font-medium text-emerald hover:underline">
            Sign in
          </Link>
        </>
      }
    >
      <RegisterForm />
    </AuthShell>
  );
}
