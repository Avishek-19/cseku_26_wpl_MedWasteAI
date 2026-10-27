"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { AlertCircle,ArrowRight,Paperclip,X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { api,ApiError } from "@/lib/api";
import type { WasteRecord,WasteRecordInput } from "@/types/waste";

const schema = z.object({
  quantity: z
    .string()
    .min(1, "Required")
    .refine((v) => Number(v) > 0, "Must be greater than 0"),
  unit: z.enum(["kg", "lb", "l", "pcs"]),
  description: z.string().max(2000).optional(),
  generated_at: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

export function WasteReportForm() {
  const router = useRouter();
  const [serverError, setServerError] = useState<string | null>(null);
  const [pendingFiles, setPendingFiles] = useState<File[]>([]);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { unit: "kg" },
  });

  const onSubmit = async (values: FormValues) => {
    setServerError(null);
    const payload: WasteRecordInput = {
      quantity: values.quantity,
      unit: values.unit,
      description: values.description || undefined,
      generated_at: values.generated_at
        ? new Date(values.generated_at).toISOString()
        : undefined,
    };

    try {
      const record = await api.post<WasteRecord>("/api/v1/waste", payload);

      let failed = 0;
      for (const file of pendingFiles) {
        try {
          await api.upload(`/api/v1/waste/${record.id}/attachments`, file);
        } catch {
          failed += 1;
          // Record is already created; a failed attachment upload shouldn't
          // block navigation — the detail page lets them retry the upload.
        }
      }

      router.push(`/dashboard/waste/${record.id}${failed ? `?upload_failed=${failed}` : ""}`);
    } catch (err) {
      setServerError(
        err instanceof ApiError ? err.message : "Something went wrong. Please try again."
      );
    }
  };

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="font-display text-2xl font-semibold text-charcoal">Report waste</h1>
      <p className="mt-1.5 text-[14px] text-slate">
        Log a new batch. Category will be set after classification.
      </p>

      <form
        onSubmit={handleSubmit(onSubmit)}
        noValidate
        className="manifest-edge mt-7 space-y-5 rounded-2xl border border-mist-deep bg-paper p-7"
      >
        {serverError && (
          <div className="flex items-start gap-2 rounded-lg border border-signal-rust/20 bg-signal-rust-bg px-3.5 py-2.5 text-[13px] text-signal-rust">
            <AlertCircle size={15} className="mt-0.5 shrink-0" />
            {serverError}
          </div>
        )}

        <div className="grid grid-cols-2 gap-5">
          <div>
            <Label htmlFor="quantity">Quantity</Label>
            <Input id="quantity" type="number" step="0.01" min="0" {...register("quantity")} />
            {errors.quantity && (
              <p className="mt-1 text-[12.5px] text-signal-rust">{errors.quantity.message}</p>
            )}
          </div>
          <div>
            <Label htmlFor="unit">Unit</Label>
            <Select id="unit" {...register("unit")}>
              <option value="kg">Kilograms (kg)</option>
              <option value="lb">Pounds (lb)</option>
              <option value="l">Liters (L)</option>
              <option value="pcs">Pieces</option>
            </Select>
          </div>
        </div>

        <div>
          <Label htmlFor="generated_at">Date/time generated (optional)</Label>
          <Input id="generated_at" type="datetime-local" {...register("generated_at")} />
          <p className="mt-1.5 text-[12px] text-slate-light">Defaults to now if left blank.</p>
        </div>

        <div>
          <Label htmlFor="description">Description (optional)</Label>
          <Textarea
            id="description"
            placeholder="e.g. Sharps bin from Ward 4, replaced during morning rounds"
            {...register("description")}
          />
        </div>

        <div>
          <Label>Photos or documents (optional)</Label>
          <label className="flex cursor-pointer items-center gap-2 rounded-md border border-dashed border-mist-deep px-3.5 py-3 text-[13px] text-slate transition-colors hover:bg-mist">
            <Paperclip size={15} />
            Attach a file
            <input
              type="file"
              accept="image/jpeg,image/png,image/webp,application/pdf"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file && file.size > 10 * 1024 * 1024) setServerError("Files must be 10 MB or smaller.");
                else if (file) setPendingFiles((prev) => [...prev, file]);
                e.target.value = "";
              }}
            />
          </label>
          {pendingFiles.length > 0 && (
            <ul className="mt-2 space-y-1.5">
              {pendingFiles.map((file, i) => (
                <li
                  key={`${file.name}-${i}`}
                  className="flex items-center justify-between rounded-md bg-mist px-3 py-1.5 text-[12.5px] text-charcoal"
                >
                  {file.name}
                  <button
                    type="button"
                    onClick={() => setPendingFiles((prev) => prev.filter((_, idx) => idx !== i))}
                    className="text-slate-light hover:text-signal-rust"
                    aria-label={`Remove ${file.name}`}
                  >
                    <X size={13} />
                  </button>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-1.5 text-[12px] text-slate-light">
            JPEG, PNG, WebP, or PDF — up to 10 MB each.
          </p>
        </div>

        <Button type="submit" className="group w-full" disabled={isSubmitting}>
          {isSubmitting ? "Reporting…" : "Report waste"}
          {!isSubmitting && (
            <ArrowRight size={16} className="transition-transform group-hover:translate-x-0.5" />
          )}
        </Button>
      </form>
    </div>
  );
}