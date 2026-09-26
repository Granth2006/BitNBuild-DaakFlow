"use client";

import { useWorldStore } from "../store/useWorldStore";
import { STATUS_META, PRIORITY_META } from "../lib/palette";
import { fmtTime } from "../lib/geo";
import { Plus, Close } from "./icons";
import type { Order } from "../lib/types";

const TERMINAL: Order["status"][] = ["COMPLETED", "CANCELLED", "DROPPED"];

function StatusBadge({ status }: { status: Order["status"] }) {
  const m = STATUS_META[status];
  return (
    <span
      className="rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide"
      style={{ background: `${m.color}22`, color: m.color }}
    >
      {m.label}
    </span>
  );
}

export default function OrderPanel() {
  const orders = useWorldStore((s) => s.orders);
  const vehicles = useWorldStore((s) => s.vehicles);
  const selectedId = useWorldStore((s) => s.selectedId);
  const select = useWorldStore((s) => s.select);
  const cancelOrder = useWorldStore((s) => s.cancelOrder);
  const fireEvent = useWorldStore((s) => s.fireEvent);

  const vName: Record<string, string> = {};
  for (const v of vehicles) vName[v.id] = v.name;

  const counts = orders.reduce<Record<string, number>>((acc, o) => {
    acc[o.status] = (acc[o.status] || 0) + 1;
    return acc;
  }, {});

  const sorted = [...orders].sort((a, b) => {
    const at = TERMINAL.includes(a.status) ? 1 : 0;
    const bt = TERMINAL.includes(b.status) ? 1 : 0;
    return at - bt || b.priority - a.priority || a.windowEnd - b.windowEnd;
  });

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-line px-3 py-2">
        <div className="flex flex-wrap gap-1.5 text-[10px] text-muted">
          <span>{orders.length} orders</span>
          <span className="text-faint">·</span>
          <span className="text-emerald-400">{counts.COMPLETED || 0} done</span>
          <span className="text-faint">·</span>
          <span className="text-cyan-400">{counts.IN_PROGRESS || 0} en route</span>
          <span className="text-faint">·</span>
          <span className="text-muted">{(counts.PENDING || 0) + (counts.ASSIGNED || 0)} queued</span>
        </div>
        <button
          onClick={() => fireEvent("NEW_ORDER")}
          className="flex items-center gap-1 rounded bg-brand2/15 px-2 py-1 text-xs font-medium text-brand transition hover:bg-brand2/25"
        >
          <Plus width={12} height={12} />
          Add
        </button>
      </div>

      <div className="panel-scroll flex-1 overflow-y-auto">
        {sorted.map((o) => {
          const terminal = TERMINAL.includes(o.status);
          const pr = PRIORITY_META[o.priority];
          const selected = o.id === selectedId;
          return (
            <div
              key={o.id}
              onClick={() => select(selected ? null : o.id)}
              className={`cursor-pointer border-b border-line/60 px-3 py-2 transition ${
                selected ? "bg-surface3/70" : "hover:bg-surface2/60"
              } ${terminal ? "opacity-60" : ""}`}
            >
              <div className="flex items-center gap-2">
                <span
                  className="grid h-6 w-6 flex-none place-items-center rounded font-mono text-[11px] font-bold text-slate-950"
                  style={{ background: pr.color }}
                  title={`${pr.label} priority`}
                >
                  {o.label}
                </span>
                <span className="truncate text-sm text-ink">{o.address}</span>
                <div className="ml-auto flex items-center gap-2">
                  <StatusBadge status={o.status} />
                  {!terminal && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        cancelOrder(o.id);
                      }}
                      className="rounded p-0.5 text-faint transition hover:bg-rose-500/20 hover:text-rose-400"
                      aria-label={`Cancel order ${o.label}`}
                      title="Cancel order"
                    >
                      <Close width={13} height={13} />
                    </button>
                  )}
                </div>
              </div>
              <div className="mt-1 flex items-center gap-2 pl-8 text-[11px] text-faint">
                <span>
                  {fmtTime(o.windowStart)}–{fmtTime(o.windowEnd)}
                </span>
                <span className="text-line2">·</span>
                <span>{o.weight} kg</span>
                {o.assignedVehicle && (
                  <>
                    <span className="text-line2">·</span>
                    <span className="text-muted">{vName[o.assignedVehicle]}</span>
                  </>
                )}
                {o.eta != null && !terminal && (
                  <>
                    <span className="text-line2">·</span>
                    <span className={o.eta > o.windowEnd ? "text-rose-400" : "text-muted"}>ETA {fmtTime(o.eta)}</span>
                  </>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
