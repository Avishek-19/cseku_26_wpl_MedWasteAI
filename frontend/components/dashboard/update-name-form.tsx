"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { AlertCircle,CheckCircle2 } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/hooks/use-auth";
import { api,ApiError } from "@/lib/api";
import type { User } from "@/types/auth";

const schema = z.object({
  full_name: z.string().min(1, "Required").max(255),
});
type FormValues = z.infer<typeof schema>;

export function UpdateNameForm() {
  const { user, refresh } = useAuth();
  const [serverError, setServerError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { full_name: user?.full_name ?? "" },
  });

  const onSubmit = async (values: FormValues) => {
    setServerError(null);
    setSaved(false);
    try {
      await api.patch<User>("/api/v1/auth/me", values);
      await refresh();
      setSaved(true);
    } catch (err) {
      setServerError(
        err instanceof ApiError ? err.message : "Something went wrong. Please try again."
      );
    }
  };

  return (
    <div className="rounded-2xl border border-mist-deep bg-paper p-7">
      <h2 className="font-display text-lg font-semibold text-charcoal">Display name</h2>
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
            Saved.
          </div>
        )}
        <div>
          <Label htmlFor="full_name">Full name</Label>
          <Input id="full_name" {...register("full_name")} />
          {errors.full_name && (
            <p className="mt-1 text-[12.5px] text-signal-rust">{errors.full_name.message}</p>
          )}
        </div>
        <Button type="submit" size="sm" disabled={isSubmitting}>
          {isSubmitting ? "Saving…" : "Save"}
        </Button>
      </form>
    </div>
  );
}
