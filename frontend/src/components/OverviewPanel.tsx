"use client";

import { useWorldStore } from "../store/useWorldStore";
import { fmtTime } from "../lib/geo";
import type { Section } from "./Sidebar";
import { Bolt, TrendingDown } from "./icons";

function Stat({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "brand" | "good" | "bad";
}) {
  const color =
    tone === "good" ? "text-emerald-400" : tone === "bad" ? "text-rose-400" : tone === "brand" ? "text-brand" : "text-ink";
  return (
    <div className="rounded-lg border border-line bg-surface2/60 px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-wider text-faint">{label}</div>
      <div className="mt-1 flex items-baseline gap-1">
        <span className={`font-mono text-xl font-semibold tabular-nums ${color}`}>{value}</span>
        {sub && <span className="text-[11px] text-faint">{sub}</span>}
      </div>
    </div>
  );
}

export default function OverviewPanel({ onJump }: { onJump: (s: Section) => void }) {
  const orders = useWorldStore((s) => s.orders);
  const vehicles = useWorldStore((s) => s.vehicles);
  const metrics = useWorldStore((s) => s.metrics);
  const events = useWorldStore((s) => s.events);

  const total = orders.length;
  const done = orders.filter((o) => o.status === "COMPLETED").length;
  const enRoute = orders.filter((o) => o.status === "IN_PROGRESS").length;
  const queued = orders.filter((o) => o.status === "PENDING" || o.status === "ASSIGNED").length;
  const active = vehicles.filter((v) => v.status === "ACTIVE" && v.driverAvailable).length;
  const donePct = total ? Math.round((done / total) * 100) : 0;

  return (
    <div className="panel-scroll flex h-full flex-col gap-3 overflow-y-auto p-3">
      <div className="grid grid-cols-2 gap-2">
        <Stat label="Active trucks" value={`${active}`} sub={`/ ${vehicles.length}`} tone="brand" />
        <Stat label="Completed" value={`${done}`} sub={`/ ${total}`} tone="good" />
        <Stat label="En route" value={`${enRoute}`} />
        <Stat label="Queued" value={`${queued}`} />
        <Stat label="Distance" value={metrics ? `${metrics.totalDistanceKm}` : "—"} sub="km" />
        <Stat label="Dropped" value={metrics ? `${metrics.dropped}` : "—"} tone={metrics && metrics.dropped > 0 ? "bad" : undefined} />
      </div>

      <div className="rounded-lg border border-line bg-surface2/60 px-3 py-2.5">
        <div className="flex items-center justify-between text-[11px]">
          <span className="text-faint">Day progress</span>
          <span className="font-mono text-muted">{donePct}%</span>
        </div>
        <div className="mt-2 h-2 overflow-hidden rounded-full bg-surface3">
          <div className="h-full rounded-full bg-gradient-to-r from-brand2 to-brand transition-all" style={{ width: `${donePct}%` }} />
        </div>
      </div>

      <div className="grid grid-cols-1 gap-2">
        <button
          onClick={() => onJump("simulator")}
          className="flex items-center gap-2 rounded-lg bg-brand2 px-3 py-2.5 text-sm font-medium text-white transition hover:bg-brand"
        >
          <Bolt width={15} height={15} /> Open Event Simulator
        </button>
        <button
          onClick={() => onJump("compare")}
          className="flex items-center gap-2 rounded-lg border border-line2 bg-surface2/60 px-3 py-2.5 text-sm font-medium text-muted transition hover:bg-surface3 hover:text-ink"
        >
          <TrendingDown width={15} height={15} /> See before / after impact
        </button>
      </div>

      <div className="min-h-0 flex-1">
        <div className="mb-1.5 text-[10px] uppercase tracking-wider text-faint">Recent activity</div>
        {events.length === 0 ? (
          <div className="rounded-lg border border-dashed border-line py-6 text-center text-[11px] text-faint">
            No disruptions yet — fire an event in the simulator.
          </div>
        ) : (
          <div className="flex flex-col gap-1">
            {events.slice(0, 6).map((e) => (
              <div key={e.id} className="flex items-center gap-2 rounded-md border border-line bg-surface2/40 px-2.5 py-1.5">
                <span className="font-mono text-[10px] text-faint">{fmtTime(e.simTime)}</span>
                <span className="truncate text-[12px] text-muted">{e.description}</span>
                <span className="ml-auto font-mono text-[10px] text-amber-300">{e.reoptMs}ms</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
