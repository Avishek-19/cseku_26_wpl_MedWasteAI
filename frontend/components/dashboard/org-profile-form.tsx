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
import type { WasteCategory } from "@/types/waste";

const PROCESSING_SERVICES = [
  ["AUTOCLAVE", "Autoclaving"],
  ["INCINERATION", "Incineration"],
  ["CHEMICAL_TREATMENT", "Chemical treatment"],
  ["MICROWAVE_TREATMENT", "Microwave treatment"],
  ["SHARPS_DESTRUCTION", "Sharps destruction"],
  ["PHARMACEUTICAL_TREATMENT", "Pharmaceutical treatment"],
  ["RECYCLING", "Recycling"],
  ["MATERIAL_RECOVERY", "Material recovery"],
  ["FINAL_DISPOSAL", "Final disposal"],
  ["SPECIALIZED_TREATMENT", "Specialized treatment"],
] as const;

const schema = z.object({
  name: z.string().min(1, "Required").max(255),
  registration_number: z.string().min(1, "Required").max(100),
  contact_person: z.string().min(1, "Required").max(255),
  phone: z.string().min(1, "Required").max(30),
  address_line: z.string().min(1, "Required").max(255),
  city: z.string().min(1, "Required").max(120),
  region: z.string().min(1, "Required").max(120),
  postal_code: z.string().min(1, "Required").max(20),
  facility_type: z.string().min(1).max(80),
  availability_status: z.enum(["available", "limited", "unavailable"]),
  capacity_kg: z.string().min(1, "Required").refine((v) => Number(v) > 0, "Must be greater than 0"),
  latitude: z.string().optional(),
  longitude: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

type Profile = {
  id: string;
  user_id: string;
  name: string;
  registration_number: string;
  contact_person: string;
  phone: string;
  address_line: string;
  city: string;
  region: string;
  postal_code: string;
  capacity_kg: string;
  current_utilization_kg: string;
  is_verified: boolean;
  facility_type: string;
  processing_services: string[];
  other_services: string[];
  availability_status: "available" | "limited" | "unavailable";
  latitude?: number | null;
  longitude?: number | null;
  created_at: string;
  updated_at: string;
};

export function OrgProfileForm() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [categories, setCategories] = useState<WasteCategory[]>([]);
  const [accepted, setAccepted] = useState<Set<string>>(new Set());
  const [services, setServices] = useState<Set<string>>(new Set());
  const [otherServices, setOtherServices] = useState<string[]>([]);
  const [otherInput, setOtherInput] = useState("");
  const [loading, setLoading] = useState(true);
  const [serverError, setServerError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isSubmitting },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      facility_type: "Waste Processing Facility",
      availability_status: "available",
      latitude: "",
      longitude: "",
    },
  });

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      api.get<Profile | null>("/api/v1/facilities/me"),
      api.get<WasteCategory[]>("/api/v1/waste/categories").catch(() => []),
      api.get<WasteCategory[]>("/api/v1/facilities/me/accepted-categories").catch(() => []),
    ]).then(([profileData, allCategories, acceptedCategories]) => {
      if (cancelled) return;
      setProfile(profileData);
      setCategories(allCategories);
      setAccepted(new Set(acceptedCategories.map((c) => c.id)));
      if (profileData) {
        reset({
          name: profileData.name,
          registration_number: profileData.registration_number,
          contact_person: profileData.contact_person,
          phone: profileData.phone,
          address_line: profileData.address_line,
          city: profileData.city,
          region: profileData.region,
          postal_code: profileData.postal_code,
          facility_type: profileData.facility_type || "Waste Processing Facility",
          availability_status: profileData.availability_status,
          capacity_kg: profileData.capacity_kg,
          latitude: profileData.latitude != null ? String(profileData.latitude) : "",
          longitude: profileData.longitude != null ? String(profileData.longitude) : "",
        });
        setServices(new Set(profileData.processing_services || []));
        setOtherServices(profileData.other_services || []);
      }
    }).catch((err) => {
      if (!cancelled) setServerError(err instanceof ApiError ? err.message : "Could not load facility profile.");
    }).finally(() => {
      if (!cancelled) setLoading(false);
    });
    return () => { cancelled = true; };
  }, [reset]);

  const onSubmit = async (values: FormValues) => {
    setServerError(null);
    setSaved(false);
    try {
      const payload = {
        ...values,
        capacity_kg: values.capacity_kg,
        latitude: values.latitude?.trim() ? Number(values.latitude) : null,
        longitude: values.longitude?.trim() ? Number(values.longitude) : null,
        processing_services: Array.from(services),
        other_services: otherServices,
        accepted_category_ids: Array.from(accepted),
      };
      const result = profile
        ? await api.put<Profile>("/api/v1/facilities/me", payload)
        : await api.post<Profile>("/api/v1/facilities/me", payload);
      setProfile(result);
      setServices(new Set(result.processing_services || []));
      setOtherServices(result.other_services || []);
      setSaved(true);
    } catch (err) {
      setServerError(err instanceof ApiError ? err.message : "Could not save facility profile.");
    }
  };

  const toggle = (set: Set<string>, value: string, setter: (next: Set<string>) => void) => {
    const next = new Set(set);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    setter(next);
  };

  const addOtherService = () => {
    const value = otherInput.trim();
    if (!value || value.length > 120 || otherServices.includes(value)) return;
    setOtherServices((prev) => [...prev, value].slice(0, 20));
    setOtherInput("");
  };

  if (loading) return <p className="text-[14px] text-slate">Loading facility profile…</p>;

  return (
    <div className="manifest-edge rounded-2xl border border-mist-deep bg-paper p-7">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-display text-lg font-semibold text-charcoal">Waste Processing Facility profile</h2>
          <p className="mt-1 text-[13.5px] text-slate">
            Tell the platform exactly which waste types and processing services this facility can handle.
            These database values drive deterministic facility matching after collection.
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

      <form onSubmit={handleSubmit(onSubmit)} noValidate className="mt-6 space-y-7">
        {serverError && (
          <div className="flex items-start gap-2 rounded-lg border border-signal-rust/20 bg-signal-rust-bg px-3.5 py-2.5 text-[13px] text-signal-rust">
            <AlertCircle size={15} className="mt-0.5 shrink-0" />
            {serverError}
          </div>
        )}
        {saved && (
          <div className="flex items-start gap-2 rounded-lg border border-emerald/20 bg-signal-emerald-bg px-3.5 py-2.5 text-[13px] text-emerald-dim">
            <CheckCircle2 size={15} className="mt-0.5 shrink-0" />
            Facility profile and capabilities saved.
          </div>
        )}

        <section>
          <h3 className="text-[13px] font-semibold uppercase tracking-[.08em] text-slate-light">
            Basic information
          </h3>
          <div className="mt-4 grid grid-cols-1 gap-5 sm:grid-cols-2">
            {(
              [
                ["name", "Facility name"],
                ["registration_number", "Registration number"],
                ["contact_person", "Contact person"],
                ["phone", "Phone"],
                ["address_line", "Address"],
                ["city", "City"],
                ["region", "Region"],
                ["postal_code", "Postal code"],
              ] as const
            ).map(([id, label]) => (
              <div key={id} className={id === "address_line" ? "sm:col-span-2" : ""}>
                <Label htmlFor={id}>{label}</Label>
                <Input id={id} {...register(id)} />
                {errors[id] && (
                  <p className="mt-1 text-[12.5px] text-signal-rust">{errors[id]?.message}</p>
                )}
              </div>
            ))}

            {/* Coordinates for route optimization */}
            <div>
              <Label htmlFor="latitude">Latitude</Label>
              <Input
                id="latitude"
                type="number"
                step="any"
                placeholder="22.8456"
                {...register("latitude")}
              />
              {errors.latitude && (
                <p className="mt-1 text-[12.5px] text-signal-rust">{errors.latitude.message}</p>
              )}
            </div>
            <div>
              <Label htmlFor="longitude">Longitude</Label>
              <Input
                id="longitude"
                type="number"
                step="any"
                placeholder="89.5403"
                {...register("longitude")}
              />
              {errors.longitude && (
                <p className="mt-1 text-[12.5px] text-signal-rust">{errors.longitude.message}</p>
              )}
            </div>

            <div>
              <Label htmlFor="facility_type">Facility type</Label>
              <Input id="facility_type" {...register("facility_type")} />
              {errors.facility_type && (
                <p className="mt-1 text-[12.5px] text-signal-rust">{errors.facility_type.message}</p>
              )}
            </div>
            <div>
              <Label htmlFor="availability_status">Availability</Label>
              <select
                id="availability_status"
                {...register("availability_status")}
                className="h-10 w-full rounded-lg border border-mist-deep bg-paper px-3 text-[13px] text-charcoal"
              >
                <option value="available">Available</option>
                <option value="limited">Limited</option>
                <option value="unavailable">Unavailable</option>
              </select>
            </div>
            <div>
              <Label htmlFor="capacity_kg">Daily processing capacity (kg)</Label>
              <Input id="capacity_kg" type="number" min="0" step="0.01" {...register("capacity_kg")} />
              {errors.capacity_kg && (
                <p className="mt-1 text-[12.5px] text-signal-rust">{errors.capacity_kg.message}</p>
              )}
            </div>
          </div>
        </section>

        <section className="border-t border-mist-deep pt-6">
          <h3 className="text-[13px] font-semibold uppercase tracking-[.08em] text-slate-light">
            Accepted waste types
          </h3>
          <p className="mt-1 text-[12.5px] text-slate-light">
            Select only waste categories this facility is authorized and equipped to receive.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            {categories.map((category) => {
              const checked = accepted.has(category.id);
              return (
                <button
                  key={category.id}
                  type="button"
                  onClick={() => toggle(accepted, category.id, setAccepted)}
                  className={`rounded-full border px-3.5 py-1.5 text-[13px] ${
                    checked
                      ? "border-emerald/30 bg-signal-emerald-bg text-emerald-dim"
                      : "border-mist-deep bg-paper text-slate hover:bg-mist"
                  }`}
                >
                  {checked ? "✓ " : "○ "}
                  {category.name}
                </button>
              );
            })}
          </div>
          {categories.length === 0 && (
            <p className="mt-3 text-[12.5px] text-signal-amber">
              No active waste categories are available yet.
            </p>
          )}
        </section>

        <section className="border-t border-mist-deep pt-6">
          <h3 className="text-[13px] font-semibold uppercase tracking-[.08em] text-slate-light">
            Processing services
          </h3>
          <p className="mt-1 text-[12.5px] text-slate-light">
            Recycling is configured here as a capability of this same facility.
          </p>
          <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
            {PROCESSING_SERVICES.map(([code, label]) => {
              const checked = services.has(code);
              return (
                <button
                  key={code}
                  type="button"
                  onClick={() => toggle(services, code, setServices)}
                  className={`rounded-xl border px-3 py-2.5 text-left text-[13px] ${
                    checked
                      ? "border-emerald/30 bg-signal-emerald-bg text-emerald-dim"
                      : "border-mist-deep bg-paper text-slate hover:bg-mist"
                  }`}
                >
                  {checked ? "✓ " : "○ "}
                  {label}
                </button>
              );
            })}
          </div>
          <div className="mt-4">
            <Label htmlFor="other_service">Other authorized processing service</Label>
            <div className="mt-2 flex gap-2">
              <Input
                id="other_service"
                value={otherInput}
                onChange={(e) => setOtherInput(e.target.value)}
                placeholder="e.g. Specialized solvent recovery"
                maxLength={120}
              />
              <Button type="button" variant="outline" onClick={addOtherService}>
                Add
              </Button>
            </div>
            {otherServices.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {otherServices.map((service) => (
                  <button
                    key={service}
                    type="button"
                    onClick={() => setOtherServices((prev) => prev.filter((x) => x !== service))}
                    className="rounded-full bg-mist px-3 py-1 text-[12px] text-slate"
                  >
                    {service} ×
                  </button>
                ))}
              </div>
            )}
          </div>
        </section>

        <div className="flex justify-end border-t border-mist-deep pt-5">
          <Button type="submit" disabled={isSubmitting}>
            {isSubmitting ? "Saving…" : profile ? "Save facility profile" : "Create facility profile"}
          </Button>
        </div>
      </form>
    </div>
  );
}