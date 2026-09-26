"use client";

import { useWorldStore } from "../store/useWorldStore";
import type { EventType } from "../lib/types";

const EVENTS: {
  type: EventType;
  label: string;
  glyph: string;
  desc: string;
  accent: string;
}[] = [
  { type: "NEW_ORDER", label: "New order", glyph: "📦", desc: "Drop a fresh delivery", accent: "#38bdf8" },
  { type: "PRIORITY_ORDER", label: "Priority order", glyph: "🚨", desc: "Critical, tight window", accent: "#ef4444" },
  { type: "BREAKDOWN", label: "Breakdown", glyph: "🔧", desc: "Disable busiest vehicle", accent: "#f97316" },
  { type: "TRAFFIC", label: "Traffic surge", glyph: "🚦", desc: "Slow every vehicle down", accent: "#eab308" },
  { type: "CANCELLATION", label: "Cancellation", glyph: "✖", desc: "Customer cancels a stop", accent: "#94a3b8" },
  { type: "TIME_CHANGE", label: "Window change", glyph: "⏱", desc: "Tighten a delivery window", accent: "#a78bfa" },
  { type: "ADDRESS_CHANGE", label: "Address change", glyph: "📍", desc: "Relocate a delivery", accent: "#2dd4bf" },
];

export default function EventSimulator() {
  const fireEvent = useWorldStore((s) => s.fireEvent);

  return (
    <div className="panel-scroll flex h-full flex-col overflow-y-auto p-3">
      <p className="mb-3 text-[11px] leading-relaxed text-slate-500">
        Inject a real-world disruption. Each event triggers an{" "}
        <span className="text-slate-300">incremental re-optimization</span> —
        completed and in-progress stops stay frozen.
      </p>
      <div className="grid grid-cols-1 gap-2">
        {EVENTS.map((e) => (
          <button
            key={e.type}
            onClick={() => fireEvent(e.type)}
            className="group flex items-center gap-3 rounded-lg border border-slate-800 bg-slate-950/50 px-3 py-2.5 text-left transition hover:border-slate-600 hover:bg-slate-800/50"
          >
            <span
              className="grid h-9 w-9 flex-none place-items-center rounded-md text-lg"
              style={{ background: `${e.accent}1a` }}
            >
              {e.glyph}
            </span>
            <span className="min-w-0">
              <span className="block text-sm font-medium text-slate-200">
                {e.label}
              </span>
              <span className="block text-[11px] text-slate-500">{e.desc}</span>
            </span>
          </button>
        ))}
      </div>
    </div>
  );
}
