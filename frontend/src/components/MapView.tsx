"use client";

import { MapContainer, TileLayer, Marker, Polyline, Tooltip } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { useWorldStore } from "../store/useWorldStore";
import { PRIORITY_META, STATUS_META } from "../lib/palette";
import type { LatLng, Order, Vehicle } from "../lib/types";
import { fmtTime } from "../lib/geo";

const CENTER: [number, number] = [12.9716, 77.5946];

// CARTO's basemap CDN now requires an API key and watermarks anonymous tiles,
// so we default to Esri's keyless dark-gray basemap. To use your own provider
// (e.g. a keyed CARTO or MapTiler URL) set NEXT_PUBLIC_MAP_TILE_URL in
// frontend/.env.local — no code change needed.
const TILE_URL =
  process.env.NEXT_PUBLIC_MAP_TILE_URL ??
  "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}";
const TILE_ATTRIBUTION =
  process.env.NEXT_PUBLIC_MAP_TILE_ATTRIBUTION ?? "&copy; Esri";

function depotIcon() {
  return L.divIcon({
    className: "",
    html: `<div style="width:18px;height:18px;background:#f8fafc;border:2px solid #0f172a;transform:rotate(45deg);box-shadow:0 0 8px rgba(248,250,252,.6)"></div>`,
    iconSize: [18, 18],
    iconAnchor: [9, 9],
  });
}

function vehicleIcon(v: Vehicle) {
  const broken = v.status === "BROKEN";
  const ring = broken ? "#ef4444" : v.color;
  const glyph = broken ? "&#9888;" : v.name.replace(/\D/g, "") || "•";
  return L.divIcon({
    className: "",
    html: `<div style="display:flex;align-items:center;justify-content:center;width:26px;height:26px;border-radius:50%;background:${ring};color:#0b1120;font:700 11px var(--font-geist-mono,monospace);border:2px solid #e2e8f0;box-shadow:0 0 10px ${ring}aa">${glyph}</div>`,
    iconSize: [26, 26],
    iconAnchor: [13, 13],
  });
}

function orderIcon(o: Order) {
  const s = STATUS_META[o.status];
  const p = PRIORITY_META[o.priority];
  const dim = o.status === "COMPLETED" || o.status === "CANCELLED" || o.status === "DROPPED";
  return L.divIcon({
    className: "",
    html: `<div style="width:16px;height:16px;border-radius:50%;background:${s.color};border:2px solid ${p.color};opacity:${dim ? 0.45 : 1};box-shadow:0 0 6px ${s.color}88"></div>`,
    iconSize: [16, 16],
    iconAnchor: [8, 8],
  });
}

const toLL = (p: LatLng): [number, number] => [p.lat, p.lng];

export default function MapView() {
  const depot = useWorldStore((s) => s.depot);
  const vehicles = useWorldStore((s) => s.vehicles);
  const orders = useWorldStore((s) => s.orders);
  const plan = useWorldStore((s) => s.plan);
  const select = useWorldStore((s) => s.select);
  const byId: Record<string, Order> = {};
  for (const o of orders) byId[o.id] = o;

  return (
    <MapContainer
      center={CENTER}
      zoom={12}
      className="h-full w-full"
      zoomControl={true}
    >
      <TileLayer url={TILE_URL} attribution={TILE_ATTRIBUTION} />

      {vehicles.map((v) => {
        const stops = (plan[v.id] || [])
          .map((st) => byId[st.orderId])
          .filter((o) => o && o.status !== "COMPLETED" && o.status !== "CANCELLED" && o.status !== "DROPPED");
        if (!stops.length) return null;
        const path: [number, number][] = [toLL(v.location), ...stops.map((o) => toLL(o.location))];
        return (
          <Polyline
            key={`route-${v.id}`}
            positions={path}
            pathOptions={{ color: v.color, weight: 3, opacity: 0.85, dashArray: v.status === "BROKEN" ? "6 8" : undefined }}
          />
        );
      })}

      <Marker position={toLL(depot.location)} icon={depotIcon()}>
        <Tooltip direction="top">{depot.name}</Tooltip>
      </Marker>

      {orders.map((o) => (
        <Marker
          key={o.id}
          position={toLL(o.location)}
          icon={orderIcon(o)}
          eventHandlers={{ click: () => select(o.id) }}
        >
          <Tooltip direction="top">
            <span style={{ fontWeight: 600 }}>{o.label}</span> · {o.address}
            <br />
            {STATUS_META[o.status].label} · {fmtTime(o.windowStart)}–{fmtTime(o.windowEnd)}
            {o.eta != null && <> · ETA {fmtTime(o.eta)}</>}
          </Tooltip>
        </Marker>
      ))}

      {vehicles.map((v) => (
        <Marker key={v.id} position={toLL(v.location)} icon={vehicleIcon(v)}>
          <Tooltip direction="top">
            <span style={{ fontWeight: 600 }}>{v.name}</span> · {v.driver}
            <br />
            {v.status}
            {v.status === "BROKEN" ? " (driver unavailable)" : ""}
          </Tooltip>
        </Marker>
      ))}
    </MapContainer>
  );
}
