"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { gpsTrust,gpsTrustLabel } from "@/lib/gps-trust";
import type { LatLngExpression,LayerGroup,Map as LeafletMap,Marker,Polyline } from "leaflet";
import { LocateFixed,Map as MapIcon,Maximize2,ZoomIn,ZoomOut } from "lucide-react";
import { useEffect,useMemo,useRef,useState } from "react";

export type TrackingMapStop = {
  id: string;
  pickup_id: string;
  sequence: number;
  latitude: string | number;
  longitude: string | number;
  status: string;
  label?: string | null;
  priority?: string | null;
  pickup_status?: string | null;
};

export type TrackingMapRoute = {
  id: string;
  version: number;
  status: string;
  destination_state?: string;
  geometry: { type?: string; coordinates?: number[][] } | null;
  origin_latitude?: string | number | null;
  origin_longitude?: string | number | null;
  destination_latitude?: string | number | null;
  destination_longitude?: string | number | null;
  stops: TrackingMapStop[];
};

export type TrackingMapLocation = {
  latitude: number;
  longitude: number;
  speed_kmh: number | null;
  heading_degrees: number | null;
  timestamp: string;
  source?: "simulator" | "gps_device" | "mobile_app" | "manual";
  provenance_verified?: boolean;
  anomaly_type?: string | null;
  demo?: boolean;
  stale?: boolean;
};

type GeoPoint = [number, number];

export function LiveTrackingMap({
  route,
  location,
  staleThresholdSeconds = 30,
}: {
  route: TrackingMapRoute | null;
  location: TrackingMapLocation | null;
  staleThresholdSeconds?: number;
}) {
  const mapHostRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<LeafletMap | null>(null);
  const vehicleMarkerRef = useRef<Marker | null>(null);
  const completedLineRef = useRef<Polyline | null>(null);
  const activeLineRef = useRef<Polyline | null>(null);
  const remainingLineRef = useRef<Polyline | null>(null);
  const routeLayerRef = useRef<LayerGroup | null>(null);

  const targetRef = useRef<TrackingMapLocation | null>(null);
  const renderedRef = useRef<GeoPoint | null>(null);
  const targetHeadingRef = useRef<number>(0);
  const renderedHeadingRef = useRef<number>(0);
  const frameRef = useRef<number | null>(null);
  const leafletRef = useRef<typeof import("leaflet") | null>(null);
  const iconHeadingRef = useRef<number | null>(null);
  const iconTrustRef = useRef<string | null>(null);
  const routeProgressRef = useRef(0);
  const [leafletReady, setLeafletReady] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);
  const [mapLoading, setMapLoading] = useState(true);
  const [clock, setClock] = useState(() => Date.now());
  const [reducedMotion, setReducedMotion] = useState(false);

  const points = useMemo<GeoPoint[]>(() => {
    const geometry = route?.geometry?.coordinates;
    if (geometry && geometry.length >= 2) {
      const parsed = geometry
        .filter((p) => p.length >= 2 && Number.isFinite(Number(p[0])) && Number.isFinite(Number(p[1])))
        .map((p) => [Number(p[1]), Number(p[0])] as GeoPoint);
      if (parsed.length >= 2) return parsed;
    }
    if (!route) return [];
    const fallback: GeoPoint[] = [];
    if (route.origin_latitude != null && route.origin_longitude != null) {
      fallback.push([Number(route.origin_latitude), Number(route.origin_longitude)]);
    }
    [...route.stops]
      .sort((a, b) => a.sequence - b.sequence)
      .forEach((s) => {
        fallback.push([Number(s.latitude), Number(s.longitude)]);
      });
    if (route.destination_latitude != null && route.destination_longitude != null) {
      fallback.push([Number(route.destination_latitude), Number(route.destination_longitude)]);
    }
    return fallback.filter(([lat, lng]) => Number.isFinite(lat) && Number.isFinite(lng));
  }, [route]);

  useEffect(() => {
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    const media = window.matchMedia("(prefers-reduced-motion: reduce)");
    const update = () => setReducedMotion(media.matches);
    update();
    media.addEventListener("change", update);
    return () => {
      window.clearInterval(timer);
      media.removeEventListener("change", update);
    };
  }, []);

  const trust = gpsTrust(location, clock, staleThresholdSeconds);
  const stale = useMemo(() => {
    if (!location) return true;
    const age = (clock - new Date(location.timestamp).getTime()) / 1000;
    return !Number.isFinite(age) || age > staleThresholdSeconds;
  }, [clock, location, staleThresholdSeconds]);

  useEffect(() => {
    let disposed = false;
    void import("leaflet").then((L) => {
      if (disposed || !mapHostRef.current || mapRef.current) return;
      leafletRef.current = L;
      const map = L.map(mapHostRef.current, {
        zoomControl: false,
        attributionControl: true,
        preferCanvas: true,
      });

      // Carto Voyager — free, no API key, cleaner than default OSM
      

     L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
                maxZoom: 19,
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
             }).addTo(map); 

             
      map.setView([0, 0], 2);
      mapRef.current = map;
      routeLayerRef.current = L.layerGroup().addTo(map);
      setLeafletReady(true);
      setMapLoading(false);
      window.setTimeout(() => map.invalidateSize(), 50);
    }).catch(() => {
      setMapError("Map library could not be loaded. Check the frontend dependencies and try again.");
      setMapLoading(false);
    });

    return () => {
      disposed = true;
      if (frameRef.current != null) cancelAnimationFrame(frameRef.current);
      mapRef.current?.remove();
      mapRef.current = null;
      vehicleMarkerRef.current = null;
      routeLayerRef.current = null;
      leafletRef.current = null;
    };
  }, []);

  useEffect(() => {
    if (!leafletReady || !mapRef.current || !routeLayerRef.current || !route) return;
    let cancelled = false;
    void import("leaflet").then((L) => {
      if (cancelled || !mapRef.current || !routeLayerRef.current) return;
      routeLayerRef.current.clearLayers();
      completedLineRef.current = null;
      activeLineRef.current = null;
      remainingLineRef.current = null;
      if (points.length < 2) return;

      L.polyline(points as LatLngExpression[], {
        color: "#8a978f",
        weight: 3,
        opacity: 0.45,
        dashArray: "7 9",
      }).addTo(routeLayerRef.current);

      route.stops.forEach((stop) => {
        const state = stop.status.toLowerCase();
        const isCurrent = ["en_route", "arrived"].includes(state);
        const isDone = ["collected", "completed"].includes(state);
        const marker = L.circleMarker([Number(stop.latitude), Number(stop.longitude)], {
          radius: isCurrent ? 9 : 7,
          weight: 2,
          color: isDone ? "#221435" : isCurrent ? "#56318b" : "#625d69",
          fillOpacity: 1,
          fillColor: isDone ? "#7549b4" : isCurrent ? "#faf9fb" : "#f0eff1",
        });
        const label = stop.label ? escapeHtml(stop.label) : `Pickup ${String(stop.sequence).padStart(2, "0")}`;
        marker.bindTooltip(
          `${String(stop.sequence).padStart(2, "0")} · ${label} · ${formatStopStatus(stop.status)}`,
          { direction: "top", offset: [0, -6] },
        );
        marker.addTo(routeLayerRef.current!);
      });

      if (route.destination_latitude != null && route.destination_longitude != null) {
        const destination = L.marker(
          [Number(route.destination_latitude), Number(route.destination_longitude)],
          {
            icon: L.divIcon({
              className: "mw-facility-marker",
              html: `<div class="mw-facility-marker__pin"><span>✚</span></div>`,
              iconSize: [34, 42],
              iconAnchor: [17, 40],
            }),
          },
        );
        destination.bindTooltip("Treatment Facility · Final destination", {
          direction: "top",
          offset: [0, -34],
        });
        destination.addTo(routeLayerRef.current!);
      }

      if (!location && points.length >= 2) {
        mapRef.current.fitBounds(points, { padding: [36, 36], maxZoom: 15 });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [leafletReady, points, route, location]);

  useEffect(() => {
    if (!leafletReady || !mapRef.current || !routeLayerRef.current || points.length < 2) return;
    const projected = location
      ? projectOnPolyline(points, [location.latitude, location.longitude])
      : null;
    routeProgressRef.current = projected?.distanceFraction ?? 0;

    const completed = projected
      ? points.slice(0, projected.segmentIndex + 1).concat([projected.point])
      : [points[0]];
    const active = projected
      ? [projected.point, points[Math.min(projected.segmentIndex + 1, points.length - 1)]]
      : [points[0], points[1]];
    const remaining = projected
      ? [projected.point, ...points.slice(projected.segmentIndex + 1)]
      : points;

    void import("leaflet").then((L) => {
      if (!mapRef.current) return;
      if (!completedLineRef.current) {
        completedLineRef.current = L.polyline(completed as LatLngExpression[], {
          color: "#221435",
          weight: 6,
          opacity: 0.9,
        }).addTo(mapRef.current);
        activeLineRef.current = L.polyline(active as LatLngExpression[], {
          color: "#7549b4",
          weight: 7,
          opacity: 1,
        }).addTo(mapRef.current);
        remainingLineRef.current = L.polyline(remaining as LatLngExpression[], {
          color: "#8a978f",
          weight: 3,
          opacity: 0.7,
          dashArray: "7 9",
        }).addTo(mapRef.current);
      } else {
        completedLineRef.current.setLatLngs(completed as LatLngExpression[]);
        activeLineRef.current?.setLatLngs(active as LatLngExpression[]);
        remainingLineRef.current?.setLatLngs(remaining as LatLngExpression[]);
      }
    });
  }, [leafletReady, points, location]);

  useEffect(() => {
    if (!leafletReady || !mapRef.current || !location) return;
    targetRef.current = location;
    targetHeadingRef.current = location.heading_degrees ?? targetHeadingRef.current;

    function animateFrame() {
    const marker = vehicleMarkerRef.current;
    const target = targetRef.current;
    if (!marker || !target) {
      frameRef.current = null;
      return;
    }
    if (stale) {
      frameRef.current = null;
      return;
    }
    const current = renderedRef.current ?? [target.latitude, target.longitude];
    const alpha = 1 - Math.exp(-8 * Math.min(0.05, 1 / 60));
    const next: GeoPoint = [
      current[0] + (target.latitude - current[0]) * alpha,
      current[1] + (target.longitude - current[1]) * alpha,
    ];
    renderedRef.current = next;
    const heading = smoothHeading(renderedHeadingRef.current, targetHeadingRef.current, 0.16);
    renderedHeadingRef.current = heading;
    const remaining = Math.max(Math.abs(next[0] - target.latitude), Math.abs(next[1] - target.longitude));
    const angular = Math.abs(((heading - targetHeadingRef.current + 540) % 360) - 180);
    marker.setLatLng(remaining < 0.000002 ? [target.latitude, target.longitude] : next);
    if (leafletRef.current && angular > 0.8 && Math.abs(heading - (iconHeadingRef.current ?? 0)) >= 3) {
      marker.setIcon(vehicleIcon(leafletRef.current, heading, trust));
      iconHeadingRef.current = heading;
      iconTrustRef.current = trust;
    }
    frameRef.current = remaining < 0.000002 && angular < 1 ? null : requestAnimationFrame(animateFrame);
  }
    void import("leaflet").then((L) => {
      if (!mapRef.current) return;
      if (!vehicleMarkerRef.current) {
        vehicleMarkerRef.current = L.marker([location.latitude, location.longitude], {
          icon: vehicleIcon(L, location.heading_degrees ?? 0, trust),
          zIndexOffset: 1000,
        }).addTo(mapRef.current);
        renderedRef.current = [location.latitude, location.longitude];
        renderedHeadingRef.current = location.heading_degrees ?? 0;
        iconHeadingRef.current = location.heading_degrees ?? 0;
        iconTrustRef.current = trust;
      } else if (iconTrustRef.current !== trust || Math.abs(targetHeadingRef.current - (iconHeadingRef.current ?? 0)) > 3) {
        vehicleMarkerRef.current.setIcon(vehicleIcon(L, targetHeadingRef.current, trust));
        iconHeadingRef.current = targetHeadingRef.current;
        iconTrustRef.current = trust;
      }
      if (frameRef.current == null && !reducedMotion && !stale) {
        frameRef.current = requestAnimationFrame(animateFrame);
      }
      if (reducedMotion && vehicleMarkerRef.current) {
        vehicleMarkerRef.current.setLatLng([location.latitude, location.longitude]);
      }
    });
  }, [leafletReady, location, reducedMotion, stale, trust]);

  useEffect(() => {
    if (!vehicleMarkerRef.current) return;
    void import("leaflet").then((L) => {
      vehicleMarkerRef.current?.setIcon(vehicleIcon(L, targetHeadingRef.current, trust));
      iconTrustRef.current = trust;
    });
  }, [stale, trust]);



  const zoom = (delta: number) =>
    mapRef.current?.setZoom((mapRef.current.getZoom() ?? 12) + delta);

  const center = () =>
    location &&
    mapRef.current?.flyTo(
      [location.latitude, location.longitude],
      Math.max(mapRef.current.getZoom(), 15),
      { duration: reducedMotion ? 0 : 0.6 },
    );

  const fit = () => {
    if (!points.length || !mapRef.current) return;
    mapRef.current.fitBounds(points, { padding: [36, 36], maxZoom: 15 });
  };

  const fullscreen = () => {
    const element = mapHostRef.current?.parentElement;
    if (!element) return;
    if (document.fullscreenElement) void document.exitFullscreen();
    else void element.requestFullscreen();
  };

  return (
    <div
      className="relative h-[420px] overflow-hidden rounded-2xl border border-mist-deep bg-mist sm:h-[520px]"
      aria-label="Live vehicle route map"
    >
      <div ref={mapHostRef} className="absolute inset-0 z-0" />
      <div className="pointer-events-none absolute inset-x-0 top-0 z-[500] flex items-start justify-between p-3 sm:p-4">
        <div className="pointer-events-auto rounded-xl border border-white/70 bg-paper/95 px-3 py-2.5 shadow-sm backdrop-blur sm:px-3.5 sm:py-3">
          <div className="flex items-center gap-2">
            <MapIcon size={15} className="text-forest" />
            <span className="font-display text-[13px] font-semibold text-charcoal">
              LIVE ROUTE
            </span>
            <Badge variant={trust === "verified" ? "emerald" : "amber"}>
              {gpsTrustLabel[trust]}
            </Badge>
          </div>
          <p className="mt-1 font-data text-[10px] text-slate">
            {route
              ? `Route v${route.version} · ${(route.destination_state ?? route.status).toUpperCase()}`
              : "Select a route to begin"}
          </p>
        </div>
        <div className="pointer-events-auto flex flex-col gap-1.5 rounded-xl border border-white/70 bg-paper/95 p-1.5 shadow-sm backdrop-blur">
          <MapControl label="Zoom in" onClick={() => zoom(1)}>
            <ZoomIn size={16} />
          </MapControl>
          <MapControl label="Zoom out" onClick={() => zoom(-1)}>
            <ZoomOut size={16} />
          </MapControl>
          <MapControl label="Center vehicle" onClick={center} disabled={!location}>
            <LocateFixed size={16} />
          </MapControl>
          <MapControl label="Fit route" onClick={fit} disabled={!points.length}>
            <MapIcon size={16} />
          </MapControl>
          <MapControl label="Fullscreen" onClick={fullscreen}>
            <Maximize2 size={16} />
          </MapControl>
        </div>
      </div>
      <div className="pointer-events-none absolute bottom-3 left-3 z-[500] rounded-xl border border-white/70 bg-paper/95 px-3 py-2 shadow-sm backdrop-blur sm:bottom-4 sm:left-4">
        <div className="flex items-center gap-3 text-[9px] uppercase tracking-[0.1em] text-slate sm:gap-4 sm:text-[10px]">
          <Legend line="solid-dark" label="Completed" />
          <Legend line="solid-green" label="Active" />
          <Legend line="dash" label="Remaining" />
          <span className="text-forest">✚ Facility</span>
        </div>
      </div>
      {mapLoading && (
        <div className="absolute inset-0 z-[600] grid place-items-center bg-paper/90" role="status">
          <div className="text-center">
            <div className="mx-auto h-7 w-7 animate-spin rounded-full border-2 border-mist-deep border-t-forest" />
            <p className="mt-3 text-sm text-slate">Loading map…</p>
          </div>
        </div>
      )}
      {mapError && (
        <div
          className="absolute inset-0 z-[600] grid place-items-center bg-paper/95 p-6 text-center text-sm text-signal-rust"
          role="alert"
        >
          {mapError}
        </div>
      )}
      {!mapLoading && !route && (
        <div className="pointer-events-none absolute inset-0 z-[400] grid place-items-center">
          <div className="rounded-xl border border-mist-deep bg-paper/95 px-5 py-4 text-center shadow-sm">
            <p className="font-display text-sm font-semibold text-charcoal">No route selected</p>
            <p className="mt-1 text-xs text-slate">
              Choose a persisted route to visualize its stops and geometry.
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function MapControl({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <Button
      type="button"
      size="icon"
      variant="outline"
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      className="h-9 w-9 bg-paper"
    >
      {children}
    </Button>
  );
}

function Legend({ line, label }: { line: string; label: string }) {
  const cls =
    line === "solid-dark"
      ? "bg-forest"
      : line === "solid-green"
        ? "bg-emerald"
        : "border-t border-dashed border-slate";
  return (
    <span className="flex items-center gap-1.5">
      <i className={`block h-0.5 w-5 ${cls}`} />
      {label}
    </span>
  );
}

function vehicleIcon(
  L: typeof import("leaflet"),
  heading: number,
  trust: string,
) {
  const stale = trust === "stale" || trust === "no-signal";
  const badge = ({verified:"SIGNED",unverified:"UNVERIFIED",simulator:"SIM",anomalous:"ANOMALY",stale:"STALE","no-signal":"NO GPS"} as Record<string,string>)[trust] ?? "NO GPS";
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 56 32">
    <g transform="rotate(${heading} 28 16)">
      <rect x="5" y="9" width="34" height="14" rx="3" fill="#6b3a73"/>
      <path d="M39 12h7l5 5v6H39z" fill="#5a3528"/>
      <rect x="42" y="14" width="6" height="5" rx="1" fill="#faf4ec"/>
      <circle cx="15" cy="25" r="4" fill="#241914"/><circle cx="43" cy="25" r="4" fill="#241914"/>
      <path d="M9 9V6h22v3" fill="none" stroke="#faf4ec" stroke-width="2"/>
    </g>
  </svg>`;
  return L.divIcon({
    className: `mw-truck-marker ${stale ? "mw-truck-marker--stale" : ""}`,
    html: `<div class="mw-truck-marker__wrap"><span class="mw-truck-marker__pulse"></span>${svg}<span class="mw-truck-marker__badge">${badge}</span></div>`,
    iconSize: [92, 64],
    iconAnchor: [46, 32],
  });
}

function projectOnPolyline(points: GeoPoint[], target: GeoPoint) {
  let best = {
    distance2: Number.POSITIVE_INFINITY,
    segmentIndex: 0,
    point: points[0] as GeoPoint,
    distanceAlong: 0,
  };
  let totalLength = 0;
  for (let i = 0; i < points.length - 1; i++) {
    const a = points[i];
    const b = points[i + 1];
    const dx = b[0] - a[0];
    const dy = b[1] - a[1];
    const len2 = dx * dx + dy * dy;
    const len = Math.sqrt(len2);
    if (len2 === 0) continue;
    const t = Math.max(0, Math.min(1, ((target[0] - a[0]) * dx + (target[1] - a[1]) * dy) / len2));
    const p: GeoPoint = [a[0] + dx * t, a[1] + dy * t];
    const d2 = (target[0] - p[0]) ** 2 + (target[1] - p[1]) ** 2;
    if (d2 < best.distance2) {
      best = { distance2: d2, segmentIndex: i, point: p, distanceAlong: totalLength + len * t };
    }
    totalLength += len;
  }
  return { ...best, distanceFraction: totalLength > 0 ? best.distanceAlong / totalLength : 0 };
}

function smoothHeading(from: number, to: number, alpha: number) {
  const delta = ((to - from + 540) % 360) - 180;
  return (from + delta * alpha + 360) % 360;
}

function formatStopStatus(status: string) {
  return status.replaceAll("_", " ").toUpperCase();
}

function escapeHtml(value: string) {
  const replacements: Record<string, string> = {
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  };
  return value.replace(/[&<>"']/g, (character) => replacements[character] ?? character);
}