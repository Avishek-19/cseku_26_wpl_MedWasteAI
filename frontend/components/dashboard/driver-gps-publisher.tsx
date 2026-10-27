"use client";

import { api } from "@/lib/api";
import { useCallback,useEffect,useRef,useState } from "react";

type OwnRoute = {
  vehicle: { id: string; vehicle_code: string };
  route: { id: string; tracking_session_id?: string | null } | null;
};
type Overview = { vehicles: OwnRoute[] };

/** Consent-based foreground browser GPS. Never claims Android background service. */
export function DriverGpsPublisher() {
  const [routes, setRoutes] = useState<OwnRoute[]>([]);
  const [selected, setSelected] = useState("");
  const [sharing, setSharing] = useState(false);
  const [state, setState] = useState("GPS off");
  const [lastAt, setLastAt] = useState<string | null>(null);
  const [error, setError] = useState("");
  const watchRef = useRef<number | null>(null);
  const previousSent = useRef(0);
  const submitting = useRef(false);

  const stop = useCallback(() => {
    if (watchRef.current !== null && typeof navigator !== "undefined") {
      navigator.geolocation.clearWatch(watchRef.current);
      watchRef.current = null;
    }
    setSharing(false);
    setState("GPS stopped / OFFLINE");
  }, []);

  useEffect(() => {
    let disposed = false;
    api.get<Overview>("/api/v1/tracking/role-overview")
      .then((value) => { if (!disposed) setRoutes(value.vehicles.filter((v) => Boolean(v.route?.tracking_session_id))); })
      .catch((reason) => { if (!disposed) setError(reason instanceof Error ? reason.message : "Could not load assigned route"); });
    return () => { disposed = true; };
  }, []);
  useEffect(() => () => stop(), [stop]);

  function start() {
    setError("");
    if (!window.isSecureContext || !navigator.geolocation) {
      setError("Device GPS requires HTTPS (localhost is allowed for local development).");
      return;
    }
    const session = routes.find((v) => v.vehicle.id === selected)?.route?.tracking_session_id;
    if (!session) { setError("Start your assigned route before sharing GPS."); return; }
    if (watchRef.current !== null) return;
    previousSent.current = 0;
    const watchId = navigator.geolocation.watchPosition(
      async (position) => {
        // Avoid piling up overlapping requests or spamming the service.
        if (submitting.current || Date.now() - previousSent.current < 4000) return;
        previousSent.current = Date.now();
        submitting.current = true;
        try {
          const receipt = await api.post<{ provenance_verified: boolean }>(`/api/v1/tracking/sessions/${encodeURIComponent(session)}/locations`, {
            latitude: position.coords.latitude,
            longitude: position.coords.longitude,
            timestamp: new Date(position.timestamp).toISOString(),
            accuracy_m: position.coords.accuracy,
            speed_kmh: position.coords.speed === null ? null : Math.max(0, position.coords.speed * 3.6),
            heading_degrees: position.coords.heading,
            altitude_m: position.coords.altitude,
            source: "mobile_app",
          });
          setLastAt(new Date().toLocaleTimeString("en-BD", { timeZone: "Asia/Dhaka" }));
          setState(receipt.provenance_verified
            ? "Verified GPS telemetry received; route progress may advance after checks."
            : "Browser GPS uploaded for live map only — NOT verified arrival. For hospital handover use an Admin-approved no-GPS exception plus hospital QR.");
        } catch (reason) {
          setState("OFFLINE / upload failed");
          setError(reason instanceof Error ? reason.message : "GPS upload failed");
        } finally {
          submitting.current = false;
        }
      },
      (err) => {
        setState("GPS permission denied / unavailable");
        setError(err.message);
        stop();
      },
      { enableHighAccuracy: true, maximumAge: 0, timeout: 20000 },
    );
    watchRef.current = watchId;
    setSharing(true);
    setState("Waiting for device GPS...");
  }

  return (
    <section aria-label="Driver device GPS" className="rounded-xl border border-slate-200 bg-white p-4 text-slate-900 space-y-3">
      <h2 className="font-semibold">Driver device GPS (consent required)</h2>
      <p className="text-sm text-slate-600">Shares your phone&apos;s GPS only while this page is open and active. It stops when you leave or close the browser. No background GPS is claimed. Signed device telemetry is required to certify an arrival.</p>
      <label className="block text-sm">Assigned active route
        <select aria-label="Select tracked vehicle" value={selected} onChange={(e) => setSelected(e.target.value)} disabled={sharing} className="mt-1 w-full rounded border p-2">
          <option value="">Choose a started route</option>
          {routes.map((item) => <option key={item.vehicle.id} value={item.vehicle.id}>{item.vehicle.vehicle_code}</option>)}
        </select>
      </label>
      {sharing ? <button type="button" onClick={stop} className="rounded bg-rose-700 px-4 py-2 text-white">Stop sharing GPS</button>
        : <button type="button" disabled={!selected} onClick={start} className="rounded bg-indigo-700 px-4 py-2 text-white disabled:opacity-50">Allow &amp; start GPS sharing</button>}
      <p className="text-sm text-amber-800">Browser geolocation does not carry a registered device signature. It updates the map only and cannot automatically mark arrival. If no registered signed GPS device/gateway is available, request supervisor review on the <a className="underline font-semibold" href="/dashboard/handover">hospital handover page</a>. Never put a GPS signing secret into browser code.</p>
      <p className="text-sm" role="status">{state} {lastAt ? `(last uploaded ${lastAt}, Dhaka time)` : ""}</p>
      {error && <p className="text-sm text-rose-700" role="alert">{error}</p>}
    </section>
  );
}
