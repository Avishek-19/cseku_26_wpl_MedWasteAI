"use client";
import { useDeferredEffect } from "@/hooks/use-deferred-effect";

import { ACTIVE_ORG_CHANGE_EVENT,activeOrganizationId } from "@/lib/api";
import { useEffect,useRef,useState } from "react";

export type TrackingSocketState = "live" | "reconnecting" | "offline";

export type TrackingSocketEvent = {
  type?: string;
  event?: string;
  vehicle_id?: string;
  route_id?: string;
  location?: {
    latitude: number;
    longitude: number;
    speed_kmh: number | null;
    heading_degrees: number | null;
    timestamp: string;
    source?: "simulator" | "gps_device" | "mobile_app" | "manual";
    provenance_verified?: boolean;
    anomaly_type?: string | null;
    demo?: boolean;
  };
  route_progress?: {
    route_id: string;
    status: string;
    destination_state?: string;
    destination_arrived_at?: string | null;
    destination_received_at?: string | null;
    completed_stops: number;
    total_stops: number;
    current_stop_id: string | null;
    next_stop_id: string | null;
    stops: { id: string; status: string }[];
  } | null;
  [key: string]: unknown;
};

const SOCKET_URL = process.env.NEXT_PUBLIC_WS_URL?.replace(/\/$/, "");

export function useTrackingWebSocket({
  vehicleIds = [],
  routeIds = [],
  enabled = true,
  onEvent,
}: {
  vehicleIds?: string[];
  routeIds?: string[];
  enabled?: boolean;
  onEvent?: (event: TrackingSocketEvent) => void;
}) {
  const [state, setState] = useState<TrackingSocketState>("offline");
  const [organizationVersion, setOrganizationVersion] = useState(0);
  useEffect(() => { const cb = () => setOrganizationVersion(v => v + 1); window.addEventListener(ACTIVE_ORG_CHANGE_EVENT, cb); return () => window.removeEventListener(ACTIVE_ORG_CHANGE_EVENT, cb); }, []);
  const callbackRef = useRef(onEvent);
  const retryRef = useRef(0);
  const connectedAtRef = useRef<number | null>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => { callbackRef.current = onEvent; }, [onEvent]);

  const vehiclesKey = [...new Set(vehicleIds)].sort().join(",");
  const routesKey = [...new Set(routeIds)].sort().join(",");

  useDeferredEffect(() => {
    if (!enabled || (!vehiclesKey && !routesKey)) {
      setState("offline");
      return;
    }

    let closed = false;
    let socket: WebSocket | null = null;
    retryRef.current = 0;

    const connect = () => {
      if (closed) return;
      setState(retryRef.current === 0 ? "reconnecting" : "reconnecting");

      // During local development the API runs on the *same hostname* as the
      // website on port 8000. Never hardcode "localhost" for a phone.
      // In HTTPS deployments provide a WebSocket-upgrade reverse proxy and
      // use same-origin WSS or specify NEXT_PUBLIC_WS_URL.
      const base = new URL(SOCKET_URL || (process.env.NODE_ENV === "development"
        ? `${window.location.protocol}//${window.location.hostname}:8000`
        : window.location.origin));
      const protocol = base.protocol === "https:" ? "wss:" : "ws:";
      const org = activeOrganizationId();
      socket = new WebSocket(`${protocol}//${base.host}/api/v1/tracking/ws${org ? `?organization_id=${encodeURIComponent(org)}` : ""}`);

      socket.onopen = () => {
        connectedAtRef.current = Date.now();
        setState("live");
        vehiclesKey.split(",").filter(Boolean).forEach((vehicleId) => {
          socket?.send(JSON.stringify({ type: "subscribe", vehicle_id: vehicleId }));
        });
        routesKey.split(",").filter(Boolean).forEach((routeId) => {
          socket?.send(JSON.stringify({ type: "subscribe", route_id: routeId }));
        });
      };

      socket.onmessage = (message) => {
        try {
          const event = JSON.parse(message.data) as TrackingSocketEvent;
          if (event.type === "ping") {
            socket?.send(JSON.stringify({ type: "pong" }));
            return;
          }
          callbackRef.current?.(event);
        } catch {
          callbackRef.current?.({ type: "error", message: "Received an invalid tracking event." });
        }
      };

      socket.onerror = () => setState("reconnecting");
      socket.onclose = () => {
        if (closed) return;
        setState("reconnecting");
        if (connectedAtRef.current && Date.now() - connectedAtRef.current > 10000) retryRef.current = 0;
        const delay = Math.min(1000 * 2 ** retryRef.current, 15000);
        retryRef.current += 1;
        timerRef.current = setTimeout(connect, delay);
      };
    };

    connect();

    return () => {
      closed = true;
      if (timerRef.current) clearTimeout(timerRef.current);
      timerRef.current = null;
      socket?.close();
    };
  }, [enabled, routesKey, vehiclesKey, organizationVersion]);

  return state;
}
