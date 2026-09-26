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
  const activeSection = useWorldStore((s) => s.activeSection);

  const isSim = activeSection === "simulator";
  const trafficPct = Math.round((traffic - 1) * 100);
  const trafficColor = traffic >= 1.9 ? "#ef4444" : traffic >= 1.4 ? "#f97316" : "#4ade80";

  return (
    <header className="flex flex-none items-center gap-4 border-b border-line bg-surface/70 px-4 py-2.5 backdrop-blur">
      <div className="flex items-center gap-2">
        <span className="grid h-8 w-8 place-items-center rounded-md bg-brand2/15 text-brand">
          <Truck width={18} height={18} />
        </span>
        <div className="leading-tight">
          <h1 className="text-sm font-semibold tracking-tight text-ink">DaakFlow</h1>
          <div className="text-[10px] uppercase tracking-widest text-faint">Adaptive Routing</div>
        </div>
      </div>

      {isSim && (
        <>
          <div className="ml-2 flex items-center gap-2 rounded-md border border-line bg-surface2/60 px-3 py-1.5">
            <span className="text-[10px] uppercase tracking-wider text-faint">Sim clock</span>
            <span className="font-mono text-lg font-semibold tabular-nums text-ink">{fmtTime(simTime)}</span>
          </div>

          <div
            className="flex items-center gap-1.5 rounded-md border border-line bg-surface2/60 px-2.5 py-1.5"
            aria-live="polite"
          >
            <span
              className={`h-2 w-2 rounded-full ${running ? "live-dot bg-live" : "bg-faint"}`}
              aria-hidden="true"
            />
            <span className={`text-[10px] font-semibold uppercase tracking-wider ${running ? "text-live" : "text-faint"}`}>
              {running ? "Live" : "Paused"}
            </span>
          </div>

          <button
            onClick={running ? pause : play}
            aria-label={running ? "Pause simulation" : "Play simulation"}
            className="flex items-center gap-2 rounded-md bg-brand2 px-3 py-2 text-sm font-medium text-white transition hover:bg-brand"
          >
            {running ? <Pause /> : <Play />}
            {running ? "Pause" : "Play"}
          </button>

          <div className="flex items-center overflow-hidden rounded-md border border-line" role="group" aria-label="Playback speed">
            {SPEEDS.map((s) => (
              <button
                key={s.value}
                onClick={() => setSpeed(s.value)}
                aria-pressed={speed === s.value}
                aria-label={`${s.label} speed`}
                className={`px-2.5 py-2 text-xs font-medium transition ${
                  speed === s.value ? "bg-surface3 text-ink" : "bg-surface2/60 text-faint hover:bg-surface2"
                }`}
              >
                {s.label}
              </button>
            ))}
          </div>

          <div className="ml-auto flex items-center gap-2">
            <div className="flex items-center gap-2 rounded-md border border-line bg-surface2/60 px-3 py-1.5">
              <span className="text-[10px] uppercase tracking-wider text-faint">Traffic</span>
              <span className="font-mono text-sm font-semibold" style={{ color: trafficColor }}>
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
              className="flex items-center gap-2 rounded-md border border-line2 bg-surface2/60 px-3 py-2 text-sm font-medium text-muted transition hover:bg-surface3 hover:text-ink"
            >
              <Reset />
              Reset
            </button>
          </div>
        </>
      )}
    </header>
  );
}
