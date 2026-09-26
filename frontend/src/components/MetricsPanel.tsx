"use client";

import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  Cell,
} from "recharts";
import { useWorldStore } from "../store/useWorldStore";
import { fmtTime } from "../lib/geo";

function Delta({ cur, base, goodDown }: { cur: number; base: number; goodDown: boolean }) {
  const diff = +(cur - base).toFixed(1);
  if (diff === 0) return <span className="text-slate-500">±0</span>;
  const good = goodDown ? diff < 0 : diff > 0;
  return (
    <span className={good ? "text-emerald-400" : "text-rose-400"}>
      {diff > 0 ? "▲" : "▼"} {Math.abs(diff)}
    </span>
  );
}

function Card({
  label,
  value,
  unit,
  cur,
  base,
  goodDown,
}: {
  label: string;
  value: string;
  unit?: string;
  cur: number;
  base: number;
  goodDown: boolean;
}) {
  return (
    <div className="rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2">
      <div className="text-[10px] uppercase tracking-wider text-slate-500">{label}</div>
      <div className="mt-0.5 flex items-baseline gap-1">
        <span className="font-mono text-lg font-semibold text-slate-100">{value}</span>
        {unit && <span className="text-[11px] text-slate-500">{unit}</span>}
      </div>
      <div className="mt-0.5 text-[10px] text-slate-500">
        base {base} · <Delta cur={cur} base={base} goodDown={goodDown} />
      </div>
    </div>
  );
}
export default function MetricsPanel() {
  const metrics = useWorldStore((s) => s.metrics);
  const baseline = useWorldStore((s) => s.baseline);
  const events = useWorldStore((s) => s.events);

  if (!metrics || !baseline) {
    return <div className="p-4 text-sm text-slate-500">Initializing…</div>;
  }

  const chartData = events
    .slice(0, 12)
    .reverse()
    .map((e) => ({ name: fmtTime(e.simTime), ms: e.reoptMs }));

  return (
    <div className="panel-scroll flex h-full flex-col overflow-y-auto p-3">
      <div className="grid grid-cols-2 gap-2">
        <Card label="Distance" value={String(metrics.totalDistanceKm)} unit="km" cur={metrics.totalDistanceKm} base={baseline.totalDistanceKm} goodDown />
        <Card label="Finish" value={fmtTime(metrics.totalTimeMin)} cur={metrics.totalTimeMin} base={baseline.totalTimeMin} goodDown />
        <Card label="Late" value={String(metrics.lateDeliveries)} unit="stops" cur={metrics.lateDeliveries} base={baseline.lateDeliveries} goodDown />
        <Card label="Utilization" value={`${metrics.utilizationPct}`} unit="%" cur={metrics.utilizationPct} base={baseline.utilizationPct} goodDown={false} />
        <Card label="Dropped" value={String(metrics.dropped)} unit="orders" cur={metrics.dropped} base={baseline.dropped} goodDown />
        <div className="rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2">
          <div className="text-[10px] uppercase tracking-wider text-slate-500">Last re-opt</div>
          <div className="mt-0.5 flex items-baseline gap-1">
            <span className="font-mono text-lg font-semibold text-amber-300">{metrics.reoptMs}</span>
            <span className="text-[11px] text-slate-500">ms</span>
          </div>
          <div className="mt-0.5 text-[10px] text-slate-500">{metrics.routeChanges} route changes</div>
        </div>
      </div>
      <div className="mt-4">
        <div className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">
          Re-optimization time per event
        </div>
        {chartData.length === 0 ? (
          <div className="rounded-lg border border-dashed border-slate-800 py-6 text-center text-[11px] text-slate-600">
            Fire an event to see re-optimization performance
          </div>
        ) : (
          <div className="h-36 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" vertical={false} />
                <XAxis dataKey="name" tick={{ fill: "#64748b", fontSize: 9 }} tickLine={false} axisLine={{ stroke: "#1e293b" }} />
                <YAxis tick={{ fill: "#64748b", fontSize: 9 }} tickLine={false} axisLine={false} />
                <Tooltip
                  contentStyle={{ background: "#0f172a", border: "1px solid #334155", borderRadius: 8, fontSize: 11 }}
                  labelStyle={{ color: "#e2e8f0" }}
                  formatter={(v) => [`${v} ms`, "re-opt"]}
                />
                <Bar dataKey="ms" radius={[3, 3, 0, 0]}>
                  {chartData.map((_, i) => (
                    <Cell key={i} fill="#fbbf24" />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>

      <div className="mt-4">
        <div className="mb-1 text-[10px] uppercase tracking-wider text-slate-500">
          Event log
        </div>
        {events.length === 0 ? (
          <div className="text-[11px] text-slate-600">No events yet.</div>
        ) : (
          <div className="overflow-hidden rounded-lg border border-slate-800">
            <table className="w-full text-left text-[11px]">
              <thead className="bg-slate-900/60 text-slate-500">
                <tr>
                  <th className="px-2 py-1.5 font-medium">Time</th>
                  <th className="px-2 py-1.5 font-medium">Event</th>
                  <th className="px-2 py-1.5 text-right font-medium">Δ routes</th>
                  <th className="px-2 py-1.5 text-right font-medium">ms</th>
                </tr>
              </thead>
              <tbody>
                {events.map((e) => (
                  <tr key={e.id} className="border-t border-slate-800/60">
                    <td className="px-2 py-1.5 font-mono text-slate-400">{fmtTime(e.simTime)}</td>
                    <td className="px-2 py-1.5 text-slate-300">{e.description}</td>
                    <td className="px-2 py-1.5 text-right font-mono text-slate-400">{e.routeChanges}</td>
                    <td className="px-2 py-1.5 text-right font-mono text-amber-300">{e.reoptMs}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
