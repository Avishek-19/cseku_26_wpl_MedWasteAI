"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { AlertCircle,CheckCircle2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api,ApiError } from "@/lib/api";

const schema = z.object({
  current_password: z.string().min(1, "Required"),
  new_password: z.string().min(8, "Use at least 8 characters").max(72),
});
type FormValues = z.infer<typeof schema>;

export function ChangePasswordForm() {
  const [serverError, setServerError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  const onSubmit = async (values: FormValues) => {
    setServerError(null);
    setSaved(false);
    try {
      await api.post("/api/v1/auth/me/change-password", values);
      setSaved(true);
      reset();
    } catch (err) {
      setServerError(
        err instanceof ApiError ? err.message : "Something went wrong. Please try again."
      );
    }
  };

  return (
    <div className="rounded-2xl border border-mist-deep bg-paper p-7">
      <h2 className="font-display text-lg font-semibold text-charcoal">Password</h2>
      <form onSubmit={handleSubmit(onSubmit)} noValidate className="mt-5 max-w-sm space-y-4">
        {serverError && (
          <div className="flex items-start gap-2 rounded-lg border border-signal-rust/20 bg-signal-rust-bg px-3.5 py-2.5 text-[13px] text-signal-rust">
            <AlertCircle size={15} className="mt-0.5 shrink-0" />
            {serverError}
          </div>
        )}
        {saved && (
          <div className="flex items-start gap-2 rounded-lg border border-emerald/20 bg-signal-emerald-bg px-3.5 py-2.5 text-[13px] text-emerald-dim">
            <CheckCircle2 size={15} className="mt-0.5 shrink-0" />
            Password updated.
          </div>
        )}
        <div>
          <Label htmlFor="current_password">Current password</Label>
          <Input
            id="current_password"
            type="password"
            autoComplete="current-password"
            {...register("current_password")}
          />
          {errors.current_password && (
            <p className="mt-1 text-[12.5px] text-signal-rust">
              {errors.current_password.message}
            </p>
          )}
        </div>
        <div>
          <Label htmlFor="new_password">New password</Label>
          <Input
            id="new_password"
            type="password"
            autoComplete="new-password"
            {...register("new_password")}
          />
          {errors.new_password && (
            <p className="mt-1 text-[12.5px] text-signal-rust">
              {errors.new_password.message}
            </p>
          )}
        </div>
        <Button type="submit" size="sm" disabled={isSubmitting}>
          {isSubmitting ? "Updating…" : "Update password"}
        </Button>
      </form>
    </div>
  );
}
