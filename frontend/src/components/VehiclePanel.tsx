"use client";

import { useWorldStore } from "../store/useWorldStore";
import { fmtTime } from "../lib/geo";
import type { Order } from "../lib/types";

const DONE: Order["status"][] = ["COMPLETED", "CANCELLED", "DROPPED"];

export default function VehiclePanel() {
  const vehicles = useWorldStore((s) => s.vehicles);
  const orders = useWorldStore((s) => s.orders);
  const plan = useWorldStore((s) => s.plan);
  const toggleBreakdown = useWorldStore((s) => s.toggleBreakdown);

  const byId: Record<string, Order> = {};
  for (const o of orders) byId[o.id] = o;

  return (
    <div className="panel-scroll flex h-full flex-col overflow-y-auto">
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

        return (
          <div key={v.id} className="border-b border-slate-800/60 px-3 py-2.5">
            <div className="flex items-center gap-2">
              <span
                className="h-2.5 w-2.5 flex-none rounded-full"
                style={{
                  background: broken ? "#ef4444" : v.color,
                  boxShadow: `0 0 6px ${broken ? "#ef4444" : v.color}`,
                }}
              />
              <span className="text-sm font-medium text-slate-200">{v.name}</span>
              <span className="text-xs text-slate-500">{v.driver}</span>
              <button
                onClick={() => toggleBreakdown(v.id)}
                className={`ml-auto rounded px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide transition ${
                  broken
                    ? "bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25"
                    : "bg-rose-500/15 text-rose-300 hover:bg-rose-500/25"
                }`}
              >
                {broken ? "Repair" : "Break"}
              </button>
            </div>

            <div className="mt-2 flex items-center gap-2">
              <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-slate-800">
                <div
                  className="h-full rounded-full transition-all"
                  style={{
                    width: `${pct}%`,
                    background: pct > 90 ? "#f97316" : v.color,
                  }}
                />
              </div>
              <span className="font-mono text-[10px] tabular-nums text-slate-400">
                {load}/{v.capacityWeight} kg
              </span>
            </div>

            <div className="mt-1.5 flex items-center gap-2 text-[11px] text-slate-500">
              {broken ? (
                <span className="text-rose-400">Out of service — orders reassigned</span>
              ) : (
                <>
                  <span>{remaining.length} stops left</span>
                  {next && (
                    <>
                      <span className="text-slate-600">·</span>
                      <span>
                        next {next.label} @ {next.eta != null ? fmtTime(next.eta) : "—"}
                      </span>
                    </>
                  )}
                </>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
