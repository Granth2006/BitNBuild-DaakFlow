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
import { Package, AlertTriangle, Wrench, Cone, Ban, Clock, MapPin } from "./icons";
import type { EventType } from "../lib/types";

const EVENTS: { type: EventType; label: string; Icon: typeof Package; desc: string; accent: string }[] = [
  { type: "NEW_ORDER", label: "New order", Icon: Package, desc: "Drop a fresh delivery", accent: "#38bdf8" },
  { type: "PRIORITY_ORDER", label: "Priority order", Icon: AlertTriangle, desc: "Critical, tight window", accent: "#f43f5e" },
  { type: "BREAKDOWN", label: "Breakdown", Icon: Wrench, desc: "Disable busiest vehicle", accent: "#f97316" },
  { type: "TRAFFIC", label: "Traffic surge", Icon: Cone, desc: "Slow every vehicle", accent: "#fbbf24" },
  { type: "CANCELLATION", label: "Cancellation", Icon: Ban, desc: "Customer cancels a stop", accent: "#94a3b8" },
  { type: "TIME_CHANGE", label: "Window change", Icon: Clock, desc: "Tighten a window", accent: "#a78bfa" },
  { type: "ADDRESS_CHANGE", label: "Address change", Icon: MapPin, desc: "Relocate a stop", accent: "#2dd4bf" },
];

export default function EventConsole() {
  const fireEvent = useWorldStore((s) => s.fireEvent);
  const events = useWorldStore((s) => s.events);
  const metrics = useWorldStore((s) => s.metrics);

  const chartData = events
    .slice(0, 10)
    .reverse()
    .map((e) => ({ name: fmtTime(e.simTime), ms: e.reoptMs }));

  return (
    <div className="panel-scroll flex h-full flex-col gap-3 overflow-y-auto p-3">
      <p className="rounded-lg border border-line bg-surface2/50 px-3 py-2 text-[11px] leading-relaxed text-muted">
        Inject a live disruption. Each one triggers an <span className="text-brand">incremental re-optimization</span> —
        completed & in-progress stops stay frozen; only the unvisited tail re-routes.
      </p>

      <div className="grid grid-cols-2 gap-2">
        {EVENTS.map((e) => (
          <button
            key={e.type}
            onClick={() => fireEvent(e.type)}
            className="group flex flex-col gap-1 rounded-lg border border-line bg-surface2/50 px-2.5 py-2 text-left transition hover:border-line2 hover:bg-surface3"
          >
            <span
              className="grid h-8 w-8 place-items-center rounded-md"
              style={{ background: `${e.accent}1a`, color: e.accent }}
            >
              <e.Icon width={16} height={16} />
            </span>
            <span className="text-[12px] font-medium text-ink">{e.label}</span>
            <span className="text-[10px] text-faint">{e.desc}</span>
          </button>
        ))}
      </div>

      {metrics && (
        <div className="grid grid-cols-2 gap-2">
          <div className="rounded-lg border border-line bg-surface2/60 px-3 py-2">
            <div className="text-[10px] uppercase tracking-wider text-faint">Last re-opt</div>
            <div className="font-mono text-lg font-semibold text-amber-300">
              {metrics.reoptMs}
              <span className="text-[11px] text-faint"> ms</span>
            </div>
          </div>
          <div className="rounded-lg border border-line bg-surface2/60 px-3 py-2">
            <div className="text-[10px] uppercase tracking-wider text-faint">Route changes</div>
            <div className="font-mono text-lg font-semibold text-ink">{metrics.routeChanges}</div>
          </div>
        </div>
      )}

      <div>
        <div className="mb-1 text-[10px] uppercase tracking-wider text-faint">Re-optimization time / event</div>
        {chartData.length === 0 ? (
          <div className="rounded-lg border border-dashed border-line py-5 text-center text-[11px] text-faint">
            Fire an event to measure re-opt speed
          </div>
        ) : (
          <div className="h-28 w-full">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={chartData} margin={{ top: 4, right: 4, bottom: 0, left: -22 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e2840" vertical={false} />
                <XAxis dataKey="name" tick={{ fill: "#79859f", fontSize: 9 }} tickLine={false} axisLine={{ stroke: "#1e2840" }} />
                <YAxis tick={{ fill: "#79859f", fontSize: 9 }} tickLine={false} axisLine={false} />
                <Tooltip
                  contentStyle={{ background: "#0d1321", border: "1px solid #2c3a5c", borderRadius: 8, fontSize: 11 }}
                  labelStyle={{ color: "#e6eaf2" }}
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

      <div className="min-h-0 flex-1">
        <div className="mb-1 text-[10px] uppercase tracking-wider text-faint">Event log</div>
        {events.length === 0 ? (
          <div className="text-[11px] text-faint">No events yet.</div>
        ) : (
          <div className="flex flex-col gap-1">
            {events.map((e) => (
              <div key={e.id} className="flex items-center gap-2 rounded-md border border-line bg-surface2/40 px-2.5 py-1.5">
                <span className="font-mono text-[10px] text-faint">{fmtTime(e.simTime)}</span>
                <span className="truncate text-[12px] text-muted">{e.description}</span>
                <span className="ml-auto font-mono text-[10px] text-faint">Δ{e.routeChanges}</span>
                <span className="font-mono text-[10px] text-amber-300">{e.reoptMs}ms</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
