/** GPS delivery is live transport, not proof of device authenticity. */
export type GPSLike = {
  source?: string | null;
  provenance_verified?: boolean | null;
  anomaly_type?: string | null;
  timestamp?: string | null;
  demo?: boolean | null;
};
export type GPSTrust = "no-signal" | "stale" | "simulator" | "anomalous" | "verified" | "unverified";
export function gpsTrust(location: GPSLike | null, nowMs: number, staleSeconds: number): GPSTrust {
  if (!location) return "no-signal";
  const instant = Date.parse(location.timestamp ?? "");
  if (!Number.isFinite(instant) || instant > nowMs + 30000 || nowMs - instant > staleSeconds * 1000) return "stale";
  if (location.source === "simulator" || location.demo) return "simulator";
  if (location.anomaly_type) return "anomalous";
  return location.provenance_verified === true ? "verified" : "unverified";
}
export const gpsTrustLabel: Record<GPSTrust, string> = {
  "no-signal": "NO GPS", "stale": "GPS STALE", "simulator": "SIMULATOR",
  "anomalous": "GPS ANOMALY", "verified": "VERIFIED GPS", "unverified": "UNVERIFIED GPS",
};
