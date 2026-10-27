"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { AlertCircle,CheckCircle2,ShieldCheck } from "lucide-react";
import { useEffect,useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api,ApiError } from "@/lib/api";
import type { HospitalProfile,HospitalProfileInput } from "@/types/hospital";

const schema = z.object({
  name: z.string().min(1, "Required").max(255),
  registration_number: z.string().min(1, "Required").max(100),
  contact_person: z.string().min(1, "Required").max(255),
  phone: z.string().min(1, "Required").max(30),
  address_line: z.string().min(1, "Required").max(255),
  city: z.string().min(1, "Required").max(120),
  region: z.string().min(1, "Required").max(120),
  postal_code: z.string().min(1, "Required").max(20),
  bed_count: z.string().optional(),
  latitude: z.string().optional(),
  longitude: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

export function HospitalProfileForm() {
  const [profile, setProfile] = useState<HospitalProfile | null>(null);
  const [loading, setLoading] = useState(true);
  const [serverError, setServerError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({ resolver: zodResolver(schema) });

  useEffect(() => {
    api
      .get<HospitalProfile | null>("/api/v1/hospitals/me")
      .then((data) => {
        setProfile(data);
        if (data) {
          reset({
            ...data,
            bed_count: data.bed_count != null ? String(data.bed_count) : "",
            latitude: data.latitude != null ? String(data.latitude) : "",
            longitude: data.longitude != null ? String(data.longitude) : "",
          } as unknown as FormValues);
        }
      })
      .finally(() => setLoading(false));
  }, [reset]);

  const onSubmit = async (values: FormValues) => {
    setServerError(null);
    setSaved(false);
    const payload: HospitalProfileInput = {
      name: values.name,
      registration_number: values.registration_number,
      contact_person: values.contact_person,
      phone: values.phone,
      address_line: values.address_line,
      city: values.city,
      region: values.region,
      postal_code: values.postal_code,
      bed_count: values.bed_count ? Number(values.bed_count) : null,
      latitude: values.latitude ? Number(values.latitude) : null,
      longitude: values.longitude ? Number(values.longitude) : null,
    };
    try {
      const result = profile
        ? await api.put<HospitalProfile>("/api/v1/hospitals/me", payload)
        : await api.post<HospitalProfile>("/api/v1/hospitals/me", payload);
      setProfile(result);
      setSaved(true);
    } catch (err) {
      setServerError(
        err instanceof ApiError ? err.message : "Something went wrong. Please try again."
      );
    }
  };

  if (loading) {
    return <p className="text-[14px] text-slate">Loading…</p>;
  }

  return (
    <div className="manifest-edge rounded-2xl border border-mist-deep bg-paper p-7">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="font-display text-lg font-semibold text-charcoal">
            Hospital profile
          </h2>
          <p className="mt-1 text-[13.5px] text-slate">
            This information is used to verify your organization and match
            pickups to the right location.
          </p>
        </div>
        {profile && (
          <Badge variant={profile.is_verified ? "emerald" : "amber"}>
            {profile.is_verified ? (
              <>
                <ShieldCheck size={12} /> Verified
              </>
            ) : (
              "Pending verification"
            )}
          </Badge>
        )}
      </div>

      <form onSubmit={handleSubmit(onSubmit)} noValidate className="mt-6 space-y-5">
        {serverError && (
          <div className="flex items-start gap-2 rounded-lg border border-signal-rust/20 bg-signal-rust-bg px-3.5 py-2.5 text-[13px] text-signal-rust">
            <AlertCircle size={15} className="mt-0.5 shrink-0" />
            {serverError}
          </div>
        )}
        {saved && (
          <div className="flex items-start gap-2 rounded-lg border border-emerald/20 bg-signal-emerald-bg px-3.5 py-2.5 text-[13px] text-emerald-dim">
            <CheckCircle2 size={15} className="mt-0.5 shrink-0" />
            Profile saved.
          </div>
        )}

        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2">
          <div>
            <Label htmlFor="name">Hospital name</Label>
            <Input id="name" {...register("name")} />
            {errors.name && (
              <p className="mt-1 text-[12.5px] text-signal-rust">{errors.name.message}</p>
            )}
          </div>
          <div>
            <Label htmlFor="registration_number">Registration number</Label>
            <Input id="registration_number" {...register("registration_number")} />
            {errors.registration_number && (
              <p className="mt-1 text-[12.5px] text-signal-rust">
                {errors.registration_number.message}
              </p>
            )}
          </div>
          <div>
            <Label htmlFor="contact_person">Contact person</Label>
            <Input id="contact_person" {...register("contact_person")} />
            {errors.contact_person && (
              <p className="mt-1 text-[12.5px] text-signal-rust">
                {errors.contact_person.message}
              </p>
            )}
          </div>
          <div>
            <Label htmlFor="phone">Phone</Label>
            <Input id="phone" {...register("phone")} />
            {errors.phone && (
              <p className="mt-1 text-[12.5px] text-signal-rust">{errors.phone.message}</p>
            )}
          </div>
          <div className="sm:col-span-2">
            <Label htmlFor="address_line">Address</Label>
            <Input id="address_line" {...register("address_line")} />
            {errors.address_line && (
              <p className="mt-1 text-[12.5px] text-signal-rust">
                {errors.address_line.message}
              </p>
            )}
          </div>
          <div>
            <Label htmlFor="city">City</Label>
            <Input id="city" {...register("city")} />
            {errors.city && (
              <p className="mt-1 text-[12.5px] text-signal-rust">{errors.city.message}</p>
            )}
          </div>
          <div>
            <Label htmlFor="region">Region</Label>
            <Input id="region" {...register("region")} />
            {errors.region && (
              <p className="mt-1 text-[12.5px] text-signal-rust">{errors.region.message}</p>
            )}
          </div>
          <div>
            <Label htmlFor="postal_code">Postal code</Label>
            <Input id="postal_code" {...register("postal_code")} />
            {errors.postal_code && (
              <p className="mt-1 text-[12.5px] text-signal-rust">
                {errors.postal_code.message}
              </p>
            )}
          </div>
          <div>
            <Label htmlFor="bed_count">Bed count (optional)</Label>
            <Input id="bed_count" type="number" min={0} {...register("bed_count")} />
          </div>
          <div>
            <Label htmlFor="latitude">Latitude (optional)</Label>
            <Input
              id="latitude"
              type="number"
              step="any"
              placeholder="e.g. 22.845600"
              {...register("latitude")}
            />
          </div>
          <div>
            <Label htmlFor="longitude">Longitude (optional)</Label>
            <Input
              id="longitude"
              type="number"
              step="any"
              placeholder="e.g. 89.540300"
              {...register("longitude")}
            />
          </div>
        </div>

        <Button type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Saving…" : profile ? "Save changes" : "Create profile"}
        </Button>
      </form>
    </div>
  );
}