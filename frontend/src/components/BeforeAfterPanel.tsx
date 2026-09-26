"use client";

import { useWorldStore } from "../store/useWorldStore";
import { projectStatic } from "../lib/optimizer";
import { fmtTime } from "../lib/geo";
import type { Metrics } from "../lib/types";

type Row = {
  key: keyof Metrics;
  label: string;
  unit: string;
  goodDir: "down" | "up";
  fmt: (n: number) => string;
};

const ROWS: Row[] = [
  { key: "totalDistanceKm", label: "Total distance", unit: "km", goodDir: "down", fmt: (n) => `${n}` },
  { key: "totalTimeMin", label: "Completion time", unit: "", goodDir: "down", fmt: (n) => fmtTime(n) },
  { key: "lateDeliveries", label: "Late deliveries", unit: "stops", goodDir: "down", fmt: (n) => `${n}` },
  { key: "dropped", label: "Unserved stops", unit: "stops", goodDir: "down", fmt: (n) => `${n}` },
  { key: "utilizationPct", label: "Fleet utilization", unit: "%", goodDir: "up", fmt: (n) => `${n}` },
];

function Delta({ before, after, goodDir }: { before: number; after: number; goodDir: "down" | "up" }) {
  if (after === before) return <span className="text-[10px] font-medium text-faint">no change</span>;
  const decreased = after < before;
  const arrow = decreased ? "▼" : "▲";
  const better = goodDir === "down" ? decreased : !decreased;
  const pct = before === 0 ? 100 : Math.round(Math.abs((after - before) / before) * 100);
  return (
    <span className={`text-[10px] font-semibold ${better ? "text-emerald-400" : "text-rose-400"}`}>
      {arrow} {better ? "better" : "worse"} · {pct}%
    </span>
  );
}

function Bar({ value, scale, kind }: { value: number; scale: number; kind: "before" | "after" }) {
  const pct = Math.round((value / scale) * 100);
  return (
    <div className="h-2 overflow-hidden rounded-full bg-surface3">
      <div
        className={`h-full rounded-full ${kind === "before" ? "bg-line2" : "bg-gradient-to-r from-brand2 to-brand"}`}
        style={{ width: `${Math.max(2, pct)}%` }}
      />
    </div>
  );
}

export default function BeforeAfterPanel() {
  const metrics = useWorldStore((s) => s.metrics);
  const initialPlan = useWorldStore((s) => s.initialPlan);
  const initialVehicles = useWorldStore((s) => s.initialVehicles);
  const vehicles = useWorldStore((s) => s.vehicles);
  const orders = useWorldStore((s) => s.orders);
  const trafficFactor = useWorldStore((s) => s.trafficFactor);
  const events = useWorldStore((s) => s.events);

  if (!metrics || Object.keys(initialPlan).length === 0) {
    return <div className="p-3 text-[11px] text-faint">Initializing baseline…</div>;
  }

  const baseline = projectStatic(initialPlan, initialVehicles, vehicles, orders, trafficFactor);
  const n = events.length;
  const avgReopt = n ? Math.round(events.reduce((a, e) => a + e.reoptMs, 0) / n) : 0;

  return (
    <div className="panel-scroll flex h-full flex-col gap-3 overflow-y-auto p-3">
      <div className="flex items-center gap-3 text-[10px]">
        <span className="flex items-center gap-1.5 text-faint">
          <span className="h-2 w-4 rounded-full bg-line2" /> Initial plan
        </span>
        <span className="flex items-center gap-1.5 text-muted">
          <span className="h-2 w-4 rounded-full bg-gradient-to-r from-brand2 to-brand" /> Live adaptive
        </span>
      </div>

      <div className="flex flex-col gap-2">
        {ROWS.map((r) => {
          const before = baseline[r.key];
          const after = metrics[r.key];
          const scale = Math.max(before, after, 1);
          return (
            <div key={r.key} className="rounded-lg border border-line bg-surface2/60 p-3">
              <div className="flex items-center justify-between">
                <span className="text-[12px] font-medium text-ink">{r.label}</span>
                <Delta before={before} after={after} goodDir={r.goodDir} />
              </div>
              <div className="mt-2 flex flex-col gap-1.5">
                <div className="flex items-center gap-2">
                  <Bar value={before} scale={scale} kind="before" />
                  <span className="w-16 flex-none text-right font-mono text-[10px] tabular-nums text-faint">
                    {r.fmt(before)}
                    {r.unit && ` ${r.unit}`}
                  </span>
                </div>
                <div className="flex items-center gap-2">
                  <Bar value={after} scale={scale} kind="after" />
                  <span className="w-16 flex-none text-right font-mono text-[10px] tabular-nums text-ink">
                    {r.fmt(after)}
                    {r.unit && ` ${r.unit}`}
                  </span>
                </div>
              </div>
            </div>
          );
        })}
      </div>

      <p className="rounded-lg border border-line bg-surface2/50 px-3 py-2 text-[11px] leading-relaxed text-faint">
        <span className="text-muted">Initial plan</span> is the route set optimized at 08:00 before any disruption.{" "}
        <span className="text-muted">Live adaptive</span> is the current plan after {n} event{n === 1 ? "" : "s"}, each
        absorbed by an incremental re-optimization in ~{avgReopt} ms — without replanning from scratch.
      </p>
    </div>
  );
}
