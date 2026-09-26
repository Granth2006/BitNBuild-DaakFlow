"use client";

import { useWorldStore } from "../store/useWorldStore";
import { fmtTime } from "../lib/geo";
import type { Order, Vehicle } from "../lib/types";

const DONE: Order["status"][] = ["COMPLETED", "CANCELLED", "DROPPED"];

const STATUS_TONE: Record<Vehicle["status"], { label: string; cls: string }> = {
  ACTIVE: { label: "Active", cls: "bg-emerald-500/15 text-emerald-300" },
  BROKEN: { label: "Broken", cls: "bg-rose-500/15 text-rose-300" },
  IDLE: { label: "Idle", cls: "bg-slate-500/15 text-slate-300" },
};

export default function DriverPanel() {
  const vehicles = useWorldStore((s) => s.vehicles);
  const orders = useWorldStore((s) => s.orders);
  const plan = useWorldStore((s) => s.plan);
  const toggleBreakdown = useWorldStore((s) => s.toggleBreakdown);

  const byId: Record<string, Order> = {};
  for (const o of orders) byId[o.id] = o;

  return (
    <div className="panel-scroll flex h-full flex-col gap-2 overflow-y-auto p-3">
      {vehicles.map((v) => {
        const stops = plan[v.id] || [];
        const remaining = stops.filter((s) => {
          const o = byId[s.orderId];
          return o && !DONE.includes(o.status);
        });
        const load = remaining.reduce((a, s) => a + (byId[s.orderId]?.weight || 0), 0);
        const pct = Math.min(100, Math.round((load / v.capacityWeight) * 100));
        const broken = v.status === "BROKEN";
        const next = remaining[0] ? byId[remaining[0].orderId] : null;
        const tone = STATUS_TONE[v.status];

        return (
          <div key={v.id} className="rounded-lg border border-line bg-surface2/60 p-3">
            <div className="flex items-center gap-2.5">
              <span
                className="grid h-9 w-9 flex-none place-items-center rounded-lg text-sm font-semibold text-slate-950"
                style={{ background: broken ? "#ef4444" : v.color }}
              >
                {v.driver.charAt(0)}
              </span>
              <div className="min-w-0">
                <div className="truncate text-sm font-medium text-ink">{v.driver}</div>
                <div className="text-[11px] text-faint">
                  {v.name} · {v.speedKmh} km/h
                </div>
              </div>
              <span className={`ml-auto rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${tone.cls}`}>
                {tone.label}
              </span>
            </div>

            <div className="mt-2.5 flex items-center gap-2">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface3">
                <div
                  className="h-full rounded-full transition-all"
                  style={{ width: `${pct}%`, background: pct > 90 ? "#f97316" : v.color }}
                />
              </div>
              <span className="font-mono text-[10px] tabular-nums text-faint">
                {load}/{v.capacityWeight}kg
              </span>
            </div>

            <div className="mt-2 flex items-center justify-between gap-2">
              <div className="min-w-0 text-[11px] text-faint">
                {broken ? (
                  <span className="text-rose-400">Out of service — orders reassigned</span>
                ) : (
                  <span>
                    {remaining.length} stops left
                    {next && (
                      <>
                        {" "}
                        · next <span className="text-muted">{next.label}</span> @ {next.eta != null ? fmtTime(next.eta) : "—"}
                      </>
                    )}
                  </span>
                )}
              </div>
              <button
                onClick={() => toggleBreakdown(v.id)}
                aria-label={broken ? `Mark ${v.name} repaired` : `Report ${v.name} broken down`}
                className={`flex-none rounded px-2 py-1 text-[10px] font-semibold uppercase tracking-wide transition ${
                  broken
                    ? "bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25"
                    : "bg-rose-500/15 text-rose-300 hover:bg-rose-500/25"
                }`}
              >
                {broken ? "Repair" : "Break"}
              </button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
