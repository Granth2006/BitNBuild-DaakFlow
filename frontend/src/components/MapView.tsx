"use client";

import { MapContainer, TileLayer, Marker, Polyline, Tooltip, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { Fragment, memo, useEffect, useMemo } from "react";
import { useWorldStore } from "../store/useWorldStore";
import { PRIORITY_META, STATUS_META } from "../lib/palette";
import type { LatLng, Order, Vehicle } from "../lib/types";
import { fmtTime } from "../lib/geo";

const CENTER: [number, number] = [12.9716, 77.5946];

// Light "Voyager" basemap from CARTO (matches the reference). The key is read
// from NEXT_PUBLIC_CARTO_KEY (frontend/.env.local). If it's missing we fall
// back to keyless OpenStreetMap tiles so the map still renders. You can also
// hard-override the URL with NEXT_PUBLIC_MAP_TILE_URL.
const CARTO_KEY = process.env.NEXT_PUBLIC_CARTO_KEY;
const TILE_URL =
  process.env.NEXT_PUBLIC_MAP_TILE_URL ??
  (CARTO_KEY
    ? `https://basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}.png?key=${CARTO_KEY}`
    : "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png");
const TILE_ATTRIBUTION =
  process.env.NEXT_PUBLIC_MAP_TILE_ATTRIBUTION ??
  (CARTO_KEY
    ? '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>'
    : '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>');

const TRUCK_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M1 3h13v11H1zM14 7h4l3 3v4h-7"/><circle cx="5" cy="17.5" r="1.7"/><circle cx="17.5" cy="17.5" r="1.7"/></svg>`;
const WARN_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M10.3 3.2 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.2a2 2 0 0 0-3.4 0Z"/><path d="M12 9v4M12 17h.01"/></svg>`;
const HOME_SVG = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 8.35V21H2V8.35a2 2 0 0 1 1.26-1.86l8-3.2a2 2 0 0 1 1.48 0l8 3.2A2 2 0 0 1 22 8.35Z"/><path d="M6 18v-6h12v6M6 15h12"/></svg>`;

function depotIcon() {
  return L.divIcon({
    className: "",
    html: `<div class="mk-depot">${HOME_SVG}</div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  });
}

function vehicleIcon(v: Vehicle) {
  const broken = v.status === "BROKEN";
  const glyph = broken ? WARN_SVG : TRUCK_SVG;
  return L.divIcon({
    className: "",
    html: `<div class="mk-veh${broken ? " mk-veh--broken" : ""}" style="--c:${v.color}">${glyph}</div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15],
  });
}

function orderIcon(o: Order, selected: boolean) {
  const s = STATUS_META[o.status];
  const p = PRIORITY_META[o.priority];
  const dim = o.status === "COMPLETED" || o.status === "CANCELLED" || o.status === "DROPPED";
  const cls = `mk-order${dim ? " mk-order--dim" : ""}${selected ? " mk-order--sel" : ""}`;
  return L.divIcon({
    className: "",
    html: `<div class="${cls}"><div class="mk-order__pin" style="--fill:${s.color};--ring:${p.color}"><span class="mk-order__lbl">${o.label.replace("#", "")}</span></div></div>`,
    iconSize: [24, 24],
    iconAnchor: [12, 22],
    tooltipAnchor: [0, -18],
  });
}

const toLL = (p: LatLng): [number, number] => [p.lat, p.lng];

// Order states that drop out of a vehicle's live route.
const TERMINAL_STATUS = new Set(["COMPLETED", "CANCELLED", "DROPPED"]);

// Keeps Leaflet's canvas in sync when the surrounding layout resizes
// (sidebar collapse, dock changes) — otherwise tiles show grey gaps.
function ResizeSync() {
  const map = useMap();
  useEffect(() => {
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(map.getContainer());
    return () => ro.disconnect();
  }, [map]);
  return null;
}

// When a driver is focused, ease the viewport to that vehicle + its stops.
// Reads live state via getState() so it fires only on focus change, not on
// every simulation tick.
function FocusFly({ focusVehicleId }: { focusVehicleId: string | null }) {
  const map = useMap();
  useEffect(() => {
    if (!focusVehicleId) return;
    const { vehicles, plan, orders } = useWorldStore.getState();
    const v = vehicles.find((x) => x.id === focusVehicleId);
    if (!v) return;
    const byId: Record<string, Order> = {};
    for (const o of orders) byId[o.id] = o;
    const pts: [number, number][] = [toLL(v.location)];
    for (const st of plan[focusVehicleId] || []) {
      const o = byId[st.orderId];
      if (o) pts.push(toLL(o.location));
    }
    if (pts.length <= 1) map.flyTo(pts[0] ?? CENTER, 14, { duration: 0.6 });
    else map.flyToBounds(pts, { padding: [60, 60], duration: 0.6, maxZoom: 14 });
  }, [focusVehicleId, map]);
  return null;
}

// The depot never moves — its own component so a vehicle:move tick can't
// re-render it.
const DepotLayer = memo(function DepotLayer() {
  const depot = useWorldStore((s) => s.depot);
  return (
    <Marker position={toLL(depot.location)} icon={depotIcon()}>
      <Tooltip direction="top">{depot.name}</Tooltip>
    </Marker>
  );
});

// Order markers subscribe ONLY to slices that change on user action or a
// re-solve (orders / selection / focus / plan) — never to `vehicles`. The store
// keeps the `orders` array reference stable on ticks with no completion, so the
// 15 order markers no longer rebuild ~2x/sec while the sim runs. The markers are
// memoized so a focus/selection change is the only thing that recomputes them.
const OrderMarkers = memo(function OrderMarkers() {
  const orders = useWorldStore((s) => s.orders);
  const plan = useWorldStore((s) => s.plan);
  const selectedId = useWorldStore((s) => s.selectedId);
  const focusVehicleId = useWorldStore((s) => s.focusVehicleId);
  const select = useWorldStore((s) => s.select);

  const focusedOrderIds = useMemo(() => {
    const set = new Set<string>();
    if (focusVehicleId) for (const st of plan[focusVehicleId] || []) set.add(st.orderId);
    return set;
  }, [focusVehicleId, plan]);

  const markers = useMemo(
    () =>
      orders.map((o) => (
        <Marker
          key={o.id}
          position={toLL(o.location)}
          icon={orderIcon(o, o.id === selectedId)}
          opacity={focusVehicleId && !focusedOrderIds.has(o.id) ? 0.25 : 1}
          eventHandlers={{ click: () => select(o.id) }}
        >
          <Tooltip direction="top">
            <span style={{ fontWeight: 600 }}>{o.label}</span> · {o.address}
            <br />
            {STATUS_META[o.status].label} · {fmtTime(o.windowStart)}–{fmtTime(o.windowEnd)}
            {o.eta != null && <> · ETA {fmtTime(o.eta)}</>}
          </Tooltip>
        </Marker>
      )),
    [orders, selectedId, focusVehicleId, focusedOrderIds, select],
  );

  return <>{markers}</>;
});

// Route polylines follow the fleet, so they legitimately re-render each tick —
// but that is only ~4 vehicles, not the whole marker tree. Split from the order
// layer so the two don't share a render.
const VehicleRoutes = memo(function VehicleRoutes() {
  const vehicles = useWorldStore((s) => s.vehicles);
  const orders = useWorldStore((s) => s.orders);
  const plan = useWorldStore((s) => s.plan);
  const focusVehicleId = useWorldStore((s) => s.focusVehicleId);

  const byId = useMemo(() => {
    const m: Record<string, Order> = {};
    for (const o of orders) m[o.id] = o;
    return m;
  }, [orders]);

  return (
    <>
      {vehicles.map((v) => {
        if (focusVehicleId && v.id !== focusVehicleId) return null;
        const stops = (plan[v.id] || [])
          .map((st) => byId[st.orderId])
          .filter((o) => o && !TERMINAL_STATUS.has(o.status));
        if (!stops.length) return null;
        const path: [number, number][] = [toLL(v.location), ...stops.map((o) => toLL(o.location))];
        const dashed = v.status === "BROKEN";
        return (
          <Fragment key={`route-${v.id}`}>
            {/* white casing underneath for contrast on the light basemap */}
            <Polyline positions={path} pathOptions={{ color: "#ffffff", weight: 6, opacity: 0.9 }} />
            <Polyline
              positions={path}
              pathOptions={{ color: v.color, weight: 3.5, opacity: 0.95, dashArray: dashed ? "5 8" : undefined }}
            />
          </Fragment>
        );
      })}
    </>
  );
});

// Vehicle markers move each tick (the intended animation). Rendered last so the
// stacking order matches the original layering (routes < depot < orders <
// vehicles).
const VehicleMarkers = memo(function VehicleMarkers() {
  const vehicles = useWorldStore((s) => s.vehicles);
  const focusVehicleId = useWorldStore((s) => s.focusVehicleId);

  return (
    <>
      {vehicles.map((v) => {
        if (focusVehicleId && v.id !== focusVehicleId) return null;
        return (
          <Marker key={v.id} position={toLL(v.location)} icon={vehicleIcon(v)}>
            <Tooltip direction="top">
              <span style={{ fontWeight: 600 }}>{v.name}</span> · {v.driver}
              <br />
              {v.status}
              {v.status === "BROKEN" ? " (driver unavailable)" : ""}
            </Tooltip>
          </Marker>
        );
      })}
    </>
  );
});

export default function MapView() {
  // The shell subscribes only to `focusVehicleId` (for FocusFly), so a
  // vehicle:move tick re-renders just the layers that actually changed, not the
  // whole map. Each layer owns its own narrow store subscription below.
  const focusVehicleId = useWorldStore((s) => s.focusVehicleId);

  return (
    <MapContainer center={CENTER} zoom={12} className="h-full w-full" zoomControl={true}>
      <TileLayer url={TILE_URL} attribution={TILE_ATTRIBUTION} />
      <ResizeSync />
      <FocusFly focusVehicleId={focusVehicleId} />

      <VehicleRoutes />
      <DepotLayer />
      <OrderMarkers />
      <VehicleMarkers />
    </MapContainer>
  );
}
