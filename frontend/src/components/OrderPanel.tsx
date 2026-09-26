"use client";

import { useState } from "react";
import { useWorldStore, type OrderDraft } from "../store/useWorldStore";
import { STATUS_META, PRIORITY_META } from "../lib/palette";
import { fmtTime, parseTime } from "../lib/geo";
import { Plus, Pencil, Trash, Close } from "./icons";
import type { Order, Priority } from "../lib/types";

const TERMINAL: Order["status"][] = ["COMPLETED", "CANCELLED", "DROPPED"];
const PRIORITIES: Priority[] = [1, 2, 3, 4];

interface OrderForm {
  address: string;
  lat: number;
  lng: number;
  weight: number;
  priority: Priority;
  windowStart: string; // "HH:MM"
  windowEnd: string; // "HH:MM"
}

const inputCls =
  "w-full rounded-md border border-line bg-surface3 px-2 py-1.5 text-[12px] text-ink outline-none focus:border-line2";
const labelCls = "mb-1 block text-[10px] uppercase tracking-wider text-faint";

function blankForm(lat: number, lng: number, simTime: number): OrderForm {
  return {
    address: "",
    lat,
    lng,
    weight: 50,
    priority: 2,
    windowStart: fmtTime(simTime),
    windowEnd: fmtTime(simTime + 120),
  };
}

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
  const depot = useWorldStore((s) => s.depot);
  const simTime = useWorldStore((s) => s.simTime);
  const selectedId = useWorldStore((s) => s.selectedId);
  const select = useWorldStore((s) => s.select);
  const addOrder = useWorldStore((s) => s.addOrder);
  const updateOrder = useWorldStore((s) => s.updateOrder);
  const deleteOrder = useWorldStore((s) => s.deleteOrder);

  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [form, setForm] = useState<OrderForm>(() =>
    blankForm(depot.location.lat, depot.location.lng, simTime),
  );

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

  function openAdd() {
    setForm(blankForm(depot.location.lat, depot.location.lng, simTime));
    setEditing("new");
  }
  function openEdit(o: Order) {
    setForm({
      address: o.address,
      lat: o.location.lat,
      lng: o.location.lng,
      weight: o.weight,
      priority: o.priority,
      windowStart: fmtTime(o.windowStart),
      windowEnd: fmtTime(o.windowEnd),
    });
    setEditing(o.id);
  }
  function save() {
    const draft: OrderDraft = {
      address: form.address,
      lat: form.lat,
      lng: form.lng,
      weight: form.weight,
      priority: form.priority,
      windowStart: parseTime(form.windowStart),
      windowEnd: parseTime(form.windowEnd),
    };
    if (editing === "new") addOrder(draft);
    else if (editing) updateOrder(editing, draft);
    setEditing(null);
  }

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
          onClick={openAdd}
          className="flex items-center gap-1 rounded bg-brand2/15 px-2 py-1 text-xs font-medium text-brand transition hover:bg-brand2/25"
        >
          <Plus width={12} height={12} />
          Add
        </button>
      </div>

      <div className="panel-scroll flex-1 overflow-y-auto">
        {editing !== null && (
          <div className="border-b border-line p-3">
            <div className="rounded-lg border border-brand2/40 bg-surface2/60 p-3">
              <div className="mb-2 flex items-center justify-between">
                <span className="text-[12px] font-semibold text-ink">
                  {editing === "new" ? "Add order" : "Edit order"}
                </span>
                <button
                  onClick={() => setEditing(null)}
                  aria-label="Cancel"
                  className="rounded p-0.5 text-faint transition hover:text-ink"
                >
                  <Close width={14} height={14} />
                </button>
              </div>
              <div className="flex flex-col gap-2">
                <div>
                  <label className={labelCls}>Address</label>
                  <input
                    className={inputCls}
                    value={form.address}
                    onChange={(e) => setForm((f) => ({ ...f, address: e.target.value }))}
                    placeholder="e.g. Koramangala"
                  />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className={labelCls}>Latitude</label>
                    <input
                      type="number"
                      step="any"
                      className={inputCls}
                      value={form.lat}
                      onChange={(e) => setForm((f) => ({ ...f, lat: Number(e.target.value) }))}
                    />
                  </div>
                  <div>
                    <label className={labelCls}>Longitude</label>
                    <input
                      type="number"
                      step="any"
                      className={inputCls}
                      value={form.lng}
                      onChange={(e) => setForm((f) => ({ ...f, lng: Number(e.target.value) }))}
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className={labelCls}>Weight (kg)</label>
                    <input
                      type="number"
                      min={0}
                      className={inputCls}
                      value={form.weight}
                      onChange={(e) => setForm((f) => ({ ...f, weight: Number(e.target.value) }))}
                    />
                  </div>
                  <div>
                    <label className={labelCls}>Priority</label>
                    <select
                      className={inputCls}
                      value={form.priority}
                      onChange={(e) => setForm((f) => ({ ...f, priority: Number(e.target.value) as Priority }))}
                    >
                      {PRIORITIES.map((p) => (
                        <option key={p} value={p}>
                          {PRIORITY_META[p].label}
                        </option>
                      ))}
                    </select>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className={labelCls}>Window start</label>
                    <input
                      type="time"
                      className={inputCls}
                      value={form.windowStart}
                      onChange={(e) => setForm((f) => ({ ...f, windowStart: e.target.value }))}
                    />
                  </div>
                  <div>
                    <label className={labelCls}>Window end</label>
                    <input
                      type="time"
                      className={inputCls}
                      value={form.windowEnd}
                      onChange={(e) => setForm((f) => ({ ...f, windowEnd: e.target.value }))}
                    />
                  </div>
                </div>
                <div className="mt-1 flex gap-2">
                  <button
                    onClick={save}
                    className="flex-1 rounded-md bg-brand2 px-3 py-2 text-[12px] font-medium text-white transition hover:bg-brand"
                  >
                    {editing === "new" ? "Add order" : "Save changes"}
                  </button>
                  <button
                    onClick={() => setEditing(null)}
                    className="rounded-md border border-line2 bg-surface2/60 px-3 py-2 text-[12px] font-medium text-muted transition hover:bg-surface3 hover:text-ink"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
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
                <div className="ml-auto flex items-center gap-1.5">
                  <StatusBadge status={o.status} />
                  {!terminal && (
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        openEdit(o);
                      }}
                      className="rounded p-1 text-faint transition hover:bg-surface3 hover:text-ink"
                      aria-label={`Edit order ${o.label}`}
                      title="Edit order"
                    >
                      <Pencil width={13} height={13} />
                    </button>
                  )}
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      deleteOrder(o.id);
                    }}
                    className="rounded p-1 text-faint transition hover:bg-rose-500/20 hover:text-rose-400"
                    aria-label={`Delete order ${o.label}`}
                    title="Delete order"
                  >
                    <Trash width={13} height={13} />
                  </button>
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
