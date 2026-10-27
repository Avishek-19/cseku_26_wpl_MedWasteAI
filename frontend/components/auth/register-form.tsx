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
import { Select } from "@/components/ui/select";
import { useAuth } from "@/hooks/use-auth";
import { ApiError } from "@/lib/api";
import { ROLE_LABELS } from "@/types/auth";

const registerSchema = z.object({
  full_name: z.string().min(1, "Name is required").max(255),
  email: z.string().min(1, "Email is required").email("Enter a valid email address"),
  password: z
    .string()
    .min(10, "Use at least 10 characters")
    .regex(/[A-Z]/, "Include an uppercase letter")
    .regex(/[a-z]/, "Include a lowercase letter")
    .regex(/[0-9]/, "Include a number")
    .max(72, "Keep it under 72 characters"),
  role: z.enum(["hospital", "collector", "facility"]),
});

type RegisterValues = z.infer<typeof registerSchema>;

export function RegisterForm() {
  const { register: registerUser } = useAuth();
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<RegisterValues>({
    resolver: zodResolver(registerSchema),
    defaultValues: { role: "hospital" },
  });

  const onSubmit = async (values: RegisterValues) => {
    setServerError(null);
    try {
      await registerUser(values);
      router.push("/dashboard");
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
        <Label htmlFor="full_name">Full name</Label>
        <Input id="full_name" autoComplete="name" {...register("full_name")} />
        {errors.full_name && (
          <p className="mt-1 text-[12.5px] text-signal-rust">{errors.full_name.message}</p>
        )}
      </div>

      <div>
        <Label htmlFor="email">Work email</Label>
        <Input id="email" type="email" autoComplete="email" {...register("email")} />
        {errors.email && (
          <p className="mt-1 text-[12.5px] text-signal-rust">{errors.email.message}</p>
        )}
      </div>

      <div>
        <Label htmlFor="role">Organization type</Label>
        <Select id="role" {...register("role")}>
          {Object.entries(ROLE_LABELS).filter(([value]) => value !== "admin").map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </Select>
        <p className="mt-1.5 text-[12px] text-slate-light">
          Waste Processing Facility and collector accounts are verified by an
          administrator before they can receive matched waste.
        </p>
      </div>

      <div>
        <Label htmlFor="password">Password</Label>
        <div className="relative">
          <Input
            id="password"
            type={showPassword ? "text" : "password"}
            autoComplete="new-password"
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
        {isSubmitting ? "Creating account…" : "Create account"}
        {!isSubmitting && (
          <ArrowRight size={16} className="transition-transform group-hover:translate-x-0.5" />
        )}
      </Button>
    </form>
  );
}