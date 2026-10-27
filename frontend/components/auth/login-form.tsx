"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { AlertCircle,ArrowRight,Eye,EyeOff } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/hooks/use-auth";
import { ApiError } from "@/lib/api";

const loginSchema = z.object({
  email: z.string().min(1, "Email is required").email("Enter a valid email address"),
  password: z.string().min(1, "Password is required"),
});

type LoginValues = z.infer<typeof loginSchema>;

export function LoginForm() {
  const { login } = useAuth();
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<LoginValues>({ resolver: zodResolver(loginSchema) });

  const onSubmit = async (values: LoginValues) => {
    setServerError(null);
    try {
      await login(values);
      const next = new URLSearchParams(window.location.search).get("next");
      router.push(next?.startsWith("/dashboard") && !next.includes("\\") ? next : "/dashboard");
    } catch (err) {
      setServerError(
        err instanceof ApiError ? err.message : "Something went wrong. Please try again."
      );
    }
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)} noValidate className="space-y-4">
      {serverError && (
        <div className="flex items-start gap-2 rounded-lg border border-signal-rust/20 bg-signal-rust-bg px-3.5 py-2.5 text-[13px] text-signal-rust">
          <AlertCircle size={15} className="mt-0.5 shrink-0" />
          {serverError}
        </div>
      )}

      <div>
        <Label htmlFor="email">Email</Label>
        <Input id="email" type="email" autoComplete="email" {...register("email")} />
        {errors.email && (
          <p className="mt-1 text-[12.5px] text-signal-rust">{errors.email.message}</p>
        )}
      </div>

      <div>
        <Label htmlFor="password">Password</Label>
        <div className="relative">
          <Input
            id="password"
            type={showPassword ? "text" : "password"}
            autoComplete="current-password"
            className="pr-11"
            {...register("password")}
          />
          <button
            type="button"
            onClick={() => setShowPassword((prev) => !prev)}
            className="absolute right-3 top-1/2 -translate-y-1/2 rounded p-0.5 text-slate-light hover:text-charcoal transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-emerald"
            aria-label={showPassword ? "Hide password" : "Show password"}
          >
            {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
          </button>
        </div>
        {errors.password && (
          <p className="mt-1 text-[12.5px] text-signal-rust">{errors.password.message}</p>
        )}
      </div>

      <Button type="submit" className="group mt-2 w-full" disabled={isSubmitting}>
        {isSubmitting ? "Signing in…" : "Sign in"}
        {!isSubmitting && (
          <ArrowRight size={16} className="transition-transform group-hover:translate-x-0.5" />
        )}
      </Button>
    </form>
  );
}