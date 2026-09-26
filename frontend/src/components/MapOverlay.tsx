"use client";

import { useWorldStore } from "../store/useWorldStore";
import { STATUS_META } from "../lib/palette";

const LEGEND: (keyof typeof STATUS_META)[] = ["IN_PROGRESS", "ASSIGNED", "PENDING", "COMPLETED"];

function Chip({ label, value, tone }: { label: string; value: string; tone?: "good" | "bad" }) {
  const color = tone === "bad" ? "text-rose-300" : tone === "good" ? "text-emerald-300" : "text-ink";
  return (
    <div className="glass rounded-lg border border-line px-2.5 py-1.5 shadow-lg">
      <div className="text-[9px] uppercase tracking-wider text-faint">{label}</div>
      <div className={`font-mono text-sm font-semibold tabular-nums ${color}`}>{value}</div>
    </div>
  );
}

export default function MapOverlay() {
  const orders = useWorldStore((s) => s.orders);
  const vehicles = useWorldStore((s) => s.vehicles);
  const metrics = useWorldStore((s) => s.metrics);
  const focusVehicleId = useWorldStore((s) => s.focusVehicleId);
  const setFocus = useWorldStore((s) => s.setFocus);

  const active = vehicles.filter((v) => v.status === "ACTIVE" && v.driverAvailable).length;
  const live = orders.filter(
    (o) => o.status === "IN_PROGRESS" || o.status === "ASSIGNED" || o.status === "PENDING",
  ).length;

  return (
    <>
      {/* driver picker — top left, clear of the Leaflet zoom control */}
      <div className="pointer-events-auto absolute left-14 top-3 z-[1000]">
        <label className="flex items-center gap-2 rounded-lg border border-black/10 bg-white/85 px-2.5 py-1.5 shadow-lg backdrop-blur">
          <span className="text-[9px] font-semibold uppercase tracking-wider text-slate-500">Driver</span>
          <select
            value={focusVehicleId ?? ""}
            onChange={(e) => setFocus(e.target.value || null)}
            aria-label="Focus a driver's route on the map"
            className="bg-transparent text-[12px] font-medium text-slate-700 outline-none"
          >
            <option value="">All drivers</option>
            {vehicles.map((v) => (
              <option key={v.id} value={v.id}>
                {v.driver} · {v.name}
              </option>
            ))}
          </select>
        </label>
      </div>

      {/* KPI chips — top right (keeps Leaflet zoom clear top-left) */}
      <div className="pointer-events-none absolute right-3 top-3 z-[1000] flex gap-2">
        <Chip label="Active" value={`${active}`} />
        <Chip label="Live orders" value={`${live}`} />
        {metrics && (
          <Chip label="Late" value={`${metrics.lateDeliveries}`} tone={metrics.lateDeliveries > 0 ? "bad" : "good"} />
        )}
      </div>

      {/* legend — bottom left (attribution sits bottom-right) */}
      <div className="pointer-events-none absolute bottom-3 left-3 z-[1000] flex flex-col gap-1 rounded-lg border border-black/10 bg-white/85 px-2.5 py-2 shadow-lg backdrop-blur">
        {LEGEND.map((k) => {
          const m = STATUS_META[k];
          return (
            <div key={k} className="flex items-center gap-1.5 text-[10px] font-medium text-slate-600">
              <span className="h-2 w-2 rounded-full" style={{ background: m.color }} />
              {m.label}
            </div>
          );
        })}
      </div>
    </>
  );
}
