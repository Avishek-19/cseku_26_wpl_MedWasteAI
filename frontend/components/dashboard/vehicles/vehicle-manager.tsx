"use client";

import { AlertCircle,Building2,Plus,ShieldCheck,Truck } from "lucide-react";
import { useEffect,useState } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { api,ApiError } from "@/lib/api";
import type { Vehicle,VehicleStatus } from "@/types/waste";
import { VEHICLE_STATUS_LABELS } from "@/types/waste";

const STATUS_TONE: Record<VehicleStatus, "emerald" | "default" | "amber"> = {
  available: "emerald",
  reserved: "amber",
  on_route: "default",
  maintenance: "amber",
};

interface Company { id: string; name: string; org_type: string; status: string }
interface CompanyMember { user_id: string; member_role: string; user_name: string; user_email: string; user_active: boolean }

export function VehicleManager() {
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [companies, setCompanies] = useState<Company[]>([]);
  const [companyId, setCompanyId] = useState("");
  const [membersByCompany, setMembersByCompany] = useState<Record<string, CompanyMember[]>>({});
  const [driverId, setDriverId] = useState("");
  const [assigningVehicleId, setAssigningVehicleId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [showForm, setShowForm] = useState(false);
  const [code, setCode] = useState("");
  const [capacity, setCapacity] = useState("");
  const [location, setLocation] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = () => {
    setLoading(true);
    api
      .get<Vehicle[]>("/api/v1/vehicles/mine")
      .then(setVehicles)
      .catch((err) => setError(err instanceof ApiError ? err.message : "Unable to load fleet."))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    load();
    api.get<Company[]>("/api/v1/organizations/mine")
      .then((items) => {
        const eligible = items.filter((x) => x.org_type === "COLLECTION_COMPANY");
        setCompanies(eligible);
        if (eligible.length === 1) setCompanyId(eligible[0].id);
        void Promise.all(eligible.map(async (company) => {
          try {
            const members = await api.get<CompanyMember[]>(`/api/v1/organizations/${company.id}/members`);
            setMembersByCompany((current) => ({...current, [company.id]: members}));
          } catch { setError("Could not load company drivers. Refresh before assigning a vehicle."); }
        }));
      }).catch(() => setCompanies([]));
  }, []);

  const eligibleDrivers = (company: string | null) => (membersByCompany[company ?? ""] ?? []).filter(
    (member) => member.user_active && ["owner", "manager", "driver"].includes(member.member_role)
  );
  const assignDriver = async (vehicleId: string, selectedDriver: string) => {
    if (!selectedDriver) return;
    setError(null);
    setAssigningVehicleId(vehicleId);
    try {
      await api.patch(`/api/v1/vehicles/${vehicleId}`, { assigned_collector_id: selectedDriver });
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Driver assignment failed.");
    } finally { setAssigningVehicleId(null); }
  };

  const createVehicle = async () => {
    setError(null);
    if (!code.trim() || !capacity || Number(capacity) <= 0 || !companyId || !driverId) {
      setError("Choose a company, an assigned driver, a valid vehicle code and capacity.");
      return;
    }
    setBusy(true);
    try {
      await api.post("/api/v1/vehicles", {
        vehicle_code: code,
        capacity_kg: capacity,
        organization_id: companyId,
        assigned_collector_id: driverId,
        location: location || undefined,
      });
      setCode("");
      setCapacity("");
      setLocation("");
      setShowForm(false);
      setDriverId("");
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Couldn't register this vehicle.");
    } finally {
      setBusy(false);
    }
  };

  const deactivateVehicle = async (vehicleId: string) => {
    setError(null);
    try {
      await api.patch(`/api/v1/vehicles/${vehicleId}`, { is_active: false });
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not deactivate this vehicle.");
    }
  };

  return (
    <div className="mx-auto max-w-5xl">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="font-display text-2xl font-semibold text-charcoal">Vehicles</h1>
          <p className="mt-1.5 text-[14px] text-slate">
            Organization-owned fleet, protected reservations and verified dispatch lifecycle.
          </p>
        </div>
        <Button size="sm" onClick={() => setShowForm((v) => !v)}>
          <Plus size={15} /> Add vehicle
        </Button>
      </div>

      <div className="mt-6 grid gap-3 sm:grid-cols-3">
        <div className="rounded-2xl border border-mist-deep bg-paper p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-light">Active fleet</p>
          <p className="mt-2 text-3xl font-semibold text-charcoal">{vehicles.filter(v => v.is_active).length}</p>
        </div>
        <div className="rounded-2xl border border-mist-deep bg-paper p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-light">On a job</p>
          <p className="mt-2 text-3xl font-semibold text-charcoal">{vehicles.filter(v => v.status === "reserved" || v.status === "on_route").length}</p>
        </div>
        <div className="rounded-2xl border border-mist-deep bg-paper p-4">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-light">Dispatch-ready</p>
          <p className="mt-2 text-3xl font-semibold text-charcoal">{vehicles.filter(v => v.is_active && v.status === "available").length}</p>
        </div>
      </div>
      {error && !showForm && <p role="alert" className="mt-4 rounded-xl border border-signal-rust/20 bg-signal-rust-bg px-4 py-3 text-sm text-signal-rust">{error}</p>}

      {showForm && (
        <div className="manifest-edge mt-6 rounded-2xl border border-mist-deep bg-paper p-6">
          {error && (
            <div className="mb-4 flex items-start gap-2 rounded-lg border border-signal-rust/20 bg-signal-rust-bg px-3.5 py-2.5 text-[13px] text-signal-rust">
              <AlertCircle size={15} className="mt-0.5 shrink-0" />
              {error}
            </div>
          )}
          <div className="mb-4 flex items-center gap-2 text-sm text-slate"><Building2 size={16}/> Register under a collection company — the driver cannot manually change dispatch status.</div>
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div className="sm:col-span-2">
              <Label htmlFor="fleet_company">Collection company</Label>
              <Select id="fleet_company" value={companyId} onChange={(e) => {setCompanyId(e.target.value); setDriverId("");}}>
                <option value="">Choose a company</option>
                {companies.map(c => <option key={c.id} value={c.id}>{c.name} ({c.status})</option>)}
              </Select>
              {companies.length === 0 && <p className="mt-1 text-xs text-slate">Create or join a collection company in the <a className="font-semibold underline" href="/dashboard/company">Company workspace</a> before adding a vehicle.</p>}
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="fleet_driver">Assigned driver (required before dispatch)</Label>
              <Select id="fleet_driver" value={driverId} onChange={(e) => setDriverId(e.target.value)}>
                <option value="">Choose an active company driver</option>
                {eligibleDrivers(companyId).map((member) => <option key={member.user_id} value={member.user_id}>
                  {member.user_name} ({member.member_role}) — {member.user_email}
                </option>)}
              </Select>
              {!eligibleDrivers(companyId).length && companyId && <p className="mt-1 text-xs text-slate">No eligible member found. Add an owner, manager or driver in Company workspace first.</p>}
            </div>
            <div>
              <Label htmlFor="vehicle_code">Vehicle code</Label>
              <Input
                id="vehicle_code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                placeholder="VAN-01"
              />
            </div>
            <div>
              <Label htmlFor="capacity">Capacity (kg)</Label>
              <Input
                id="capacity"
                type="number"
                min="0"
                value={capacity}
                onChange={(e) => setCapacity(e.target.value)}
                placeholder="200"
              />
            </div>
            <div>
              <Label htmlFor="location">Location (optional)</Label>
              <Input
                id="location"
                value={location}
                onChange={(e) => setLocation(e.target.value)}
                placeholder="Central Depot"
              />
            </div>
          </div>
          <Button size="sm" className="mt-4" onClick={createVehicle} disabled={busy}>
            {busy ? "Adding…" : "Add vehicle"}
          </Button>
        </div>
      )}

      <div className="mt-6 space-y-3">
        {loading ? (
          <p className="text-[14px] text-slate">Loading…</p>
        ) : vehicles.length === 0 ? (
          <div className="flex flex-col items-center gap-3 rounded-2xl border border-mist-deep bg-paper p-14 text-center">
            <Truck size={28} className="text-slate-light" strokeWidth={1.5} />
            <p className="text-[14px] text-slate">No vehicles registered yet.</p>
          </div>
        ) : (
          vehicles.map((vehicle) => (
            <div
              key={vehicle.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-mist-deep bg-paper px-5 py-4"
            >
              <div>
                <div className="flex items-center gap-2.5">
                  <span className="font-data text-[14px] text-charcoal">
                    {vehicle.vehicle_code}
                  </span>
                  <Badge variant={vehicle.is_active ? STATUS_TONE[vehicle.status] : "amber"}>
                    {VEHICLE_STATUS_LABELS[vehicle.status]}
                  </Badge>
                </div>
                <p className="mt-1 text-[12.5px] text-slate-light">
                  {vehicle.capacity_kg} kg capacity
                  {vehicle.location ? ` · ${vehicle.location}` : ""}
                  {!vehicle.is_active ? " · Inactive" : ""}
                </p>
                <p className="mt-1 text-xs text-slate">Assigned driver: {
                  eligibleDrivers(vehicle.organization_id).find((member) => member.user_id === vehicle.assigned_collector_id)?.user_name
                  ?? vehicle.assigned_collector_id.slice(0,8)
                }</p>
                {vehicle.is_active && vehicle.status === "available" && vehicle.organization_id && (
                  <label className="mt-2 block text-xs text-slate">Change driver (only before booking)
                    <Select aria-label={`Assigned driver for ${vehicle.vehicle_code}`} value={vehicle.assigned_collector_id}
                      onChange={(e) => {void assignDriver(vehicle.id, e.target.value);}}
                      disabled={assigningVehicleId === vehicle.id} className="mt-1 max-w-xs">
                      {!eligibleDrivers(vehicle.organization_id).some((member) => member.user_id === vehicle.assigned_collector_id) &&
                        <option value={vehicle.assigned_collector_id}>Current driver (inactive/unavailable)</option>}
                      {eligibleDrivers(vehicle.organization_id).map((member) => <option key={member.user_id} value={member.user_id}>{member.user_name} — {member.member_role}</option>)}
                    </Select>
                  </label>
                )}
              </div>
              <div className="flex items-center gap-3">
                {vehicle.status === "available" && vehicle.is_active ? (
                  <button type="button" onClick={() => deactivateVehicle(vehicle.id)} className="rounded-lg border border-mist-deep px-3 py-2 text-xs font-medium text-slate hover:bg-mist" aria-label={`Deactivate ${vehicle.vehicle_code}`}>
                    Deactivate
                  </button>
                ) : (
                  <span className="inline-flex items-center gap-1 text-xs text-slate-light"><ShieldCheck size={14}/> Managed by dispatch</span>
                )}
              </div>
            </div>
          ))
        )}
      </div>
    </div>
  );
}
