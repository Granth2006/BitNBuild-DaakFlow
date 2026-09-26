"use client";

import { useWorldStore } from "../store/useWorldStore";
import { fmtTime } from "../lib/geo";
import { Play, Pause, Reset, Bolt, Truck } from "./icons";

const SPEEDS: { label: string; value: number }[] = [
  { label: "1×", value: 1 },
  { label: "2×", value: 3 },
  { label: "4×", value: 6 },
  { label: "8×", value: 12 },
];

export default function Topbar() {
  const simTime = useWorldStore((s) => s.simTime);
  const running = useWorldStore((s) => s.running);
  const speed = useWorldStore((s) => s.speed);
  const traffic = useWorldStore((s) => s.trafficFactor);
  const play = useWorldStore((s) => s.play);
  const pause = useWorldStore((s) => s.pause);
  const setSpeed = useWorldStore((s) => s.setSpeed);
  const reoptimize = useWorldStore((s) => s.reoptimize);
  const reset = useWorldStore((s) => s.reset);

  const trafficPct = Math.round((traffic - 1) * 100);
  const trafficColor =
    traffic >= 1.9 ? "#ef4444" : traffic >= 1.4 ? "#f97316" : "#4ade80";

  return (
    <header className="flex items-center gap-4 border-b border-slate-800 bg-slate-900/70 px-4 py-2.5 backdrop-blur">
      <div className="flex items-center gap-2">
        <span className="grid h-8 w-8 place-items-center rounded-md bg-sky-500/15 text-sky-400">
          <Truck width={18} height={18} />
        </span>
        <div className="leading-tight">
          <div className="text-sm font-semibold tracking-tight text-slate-100">
            FleetView
          </div>
          <div className="text-[10px] uppercase tracking-widest text-slate-500">
            Adaptive Routing
          </div>
        </div>
      </div>

      <div className="ml-2 flex items-center gap-2 rounded-md border border-slate-800 bg-slate-950/60 px-3 py-1.5">
        <span className="text-[10px] uppercase tracking-wider text-slate-500">
          Sim clock
        </span>
        <span className="font-mono text-lg font-semibold tabular-nums text-slate-100">
          {fmtTime(simTime)}
        </span>
      </div>

      <button
        onClick={running ? pause : play}
        className="flex items-center gap-2 rounded-md bg-sky-500 px-3 py-2 text-sm font-medium text-slate-950 transition hover:bg-sky-400"
      >
        {running ? <Pause /> : <Play />}
        {running ? "Pause" : "Play"}
      </button>

      <div className="flex items-center overflow-hidden rounded-md border border-slate-800">
        {SPEEDS.map((s) => (
          <button
            key={s.value}
            onClick={() => setSpeed(s.value)}
            className={`px-2.5 py-2 text-xs font-medium transition ${
              speed === s.value
                ? "bg-slate-700 text-slate-100"
                : "bg-slate-950/60 text-slate-400 hover:bg-slate-800"
            }`}
          >
            {s.label}
          </button>
        ))}
      </div>

      <div className="ml-auto flex items-center gap-2">
        <div className="flex items-center gap-2 rounded-md border border-slate-800 bg-slate-950/60 px-3 py-1.5">
          <span className="text-[10px] uppercase tracking-wider text-slate-500">
            Traffic
          </span>
          <span
            className="font-mono text-sm font-semibold"
            style={{ color: trafficColor }}
          >
            {trafficPct > 0 ? `+${trafficPct}%` : "clear"}
          </span>
        </div>

        <button
          onClick={reoptimize}
          className="flex items-center gap-2 rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm font-medium text-amber-300 transition hover:bg-amber-500/20"
        >
          <Bolt />
          Re-optimize
        </button>

        <button
          onClick={reset}
          className="flex items-center gap-2 rounded-md border border-slate-700 bg-slate-800/60 px-3 py-2 text-sm font-medium text-slate-300 transition hover:bg-slate-700"
        >
          <Reset />
          Reset
        </button>
      </div>
    </header>
  );
}
