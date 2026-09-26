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
// __BODY__
