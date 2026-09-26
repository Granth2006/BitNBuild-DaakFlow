"use client";

import { useState } from "react";
import { useWorldStore, type VehicleDraft } from "../store/useWorldStore";
import { fmtTime } from "../lib/geo";
import { VEHICLE_TYPE_META } from "../mock/seed";
import { Plus, Pencil, Trash, Close } from "./icons";
import type { Order, Vehicle, VehicleType } from "../lib/types";

const DONE: Order["status"][] = ["COMPLETED", "CANCELLED", "DROPPED"];
const TYPES: VehicleType[] = ["TRUCK", "VAN", "BIKE"];

const STATUS_TONE: Record<Vehicle["status"], { label: string; cls: string }> = {
  ACTIVE: { label: "Active", cls: "bg-emerald-500/15 text-emerald-300" },
  BROKEN: { label: "Broken", cls: "bg-rose-500/15 text-rose-300" },
  IDLE: { label: "Idle", cls: "bg-slate-500/15 text-slate-300" },
};

const BLANK: VehicleDraft = {
  name: "",
  driver: "",
  type: "TRUCK",
  capacityWeight: VEHICLE_TYPE_META.TRUCK.capacityWeight,
  speedKmh: VEHICLE_TYPE_META.TRUCK.speedKmh,
};

const inputCls =
  "w-full rounded-md border border-line bg-surface3 px-2 py-1.5 text-[12px] text-ink outline-none focus:border-line2";
const labelCls = "mb-1 block text-[10px] uppercase tracking-wider text-faint";

export default function DriverPanel() {
  const vehicles = useWorldStore((s) => s.vehicles);
  const orders = useWorldStore((s) => s.orders);
  const plan = useWorldStore((s) => s.plan);
  const toggleBreakdown = useWorldStore((s) => s.toggleBreakdown);
  const addVehicle = useWorldStore((s) => s.addVehicle);
  const updateVehicle = useWorldStore((s) => s.updateVehicle);
  const deleteVehicle = useWorldStore((s) => s.deleteVehicle);

  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [form, setForm] = useState<VehicleDraft>(BLANK);

  const byId: Record<string, Order> = {};
  for (const o of orders) byId[o.id] = o;

  function openAdd() {
    setForm(BLANK);
    setEditing("new");
  }
  function openEdit(v: Vehicle) {
    setForm({
      name: v.name,
      driver: v.driver,
      type: v.type,
      capacityWeight: v.capacityWeight,
      speedKmh: v.speedKmh,
    });
    setEditing(v.id);
  }
  function changeType(type: VehicleType) {
    const meta = VEHICLE_TYPE_META[type];
    setForm((f) => ({ ...f, type, capacityWeight: meta.capacityWeight, speedKmh: meta.speedKmh }));
  }
  function save() {
    if (editing === "new") addVehicle(form);
    else if (editing) updateVehicle(editing, form);
    setEditing(null);
  }

  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-line px-3 py-2">
        <span className="text-[11px] text-muted">{vehicles.length} drivers · fleet</span>
        <button
          onClick={openAdd}
          className="flex items-center gap-1 rounded bg-brand2/15 px-2 py-1 text-xs font-medium text-brand transition hover:bg-brand2/25"
        >
          <Plus width={12} height={12} />
          Add driver
        </button>
      </div>

      <div className="panel-scroll flex flex-1 flex-col gap-2 overflow-y-auto p-3">
        {editing !== null && (
          <div className="rounded-lg border border-brand2/40 bg-surface2/60 p-3">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[12px] font-semibold text-ink">
                {editing === "new" ? "Add driver" : "Edit driver"}
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
                <label className={labelCls}>Vehicle name</label>
                <input
                  className={inputCls}
                  value={form.name}
                  onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
                  placeholder="e.g. Truck 05"
                />
              </div>
              <div>
                <label className={labelCls}>Driver</label>
                <input
                  className={inputCls}
                  value={form.driver}
                  onChange={(e) => setForm((f) => ({ ...f, driver: e.target.value }))}
                  placeholder="Driver name"
                />
              </div>
              <div>
                <label className={labelCls}>Type</label>
                <select
                  className={inputCls}
                  value={form.type}
                  onChange={(e) => changeType(e.target.value as VehicleType)}
                >
                  {TYPES.map((t) => (
                    <option key={t} value={t}>
                      {VEHICLE_TYPE_META[t].label}
                    </option>
                  ))}
                </select>
              </div>
              <div className="grid grid-cols-2 gap-2">
                <div>
                  <label className={labelCls}>Capacity (kg)</label>
                  <input
                    type="number"
                    min={0}
                    className={inputCls}
                    value={form.capacityWeight}
                    onChange={(e) => setForm((f) => ({ ...f, capacityWeight: Number(e.target.value) }))}
                  />
                </div>
                <div>
                  <label className={labelCls}>Speed (km/h)</label>
                  <input
                    type="number"
                    min={1}
                    className={inputCls}
                    value={form.speedKmh}
                    onChange={(e) => setForm((f) => ({ ...f, speedKmh: Number(e.target.value) }))}
                  />
                </div>
              </div>
              <div className="mt-1 flex gap-2">
                <button
                  onClick={save}
                  className="flex-1 rounded-md bg-brand2 px-3 py-2 text-[12px] font-medium text-white transition hover:bg-brand"
                >
                  {editing === "new" ? "Add driver" : "Save changes"}
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
        )}
        {vehicles.map((v) => {
          const stops = plan[v.id] || [];
          const remaining = stops.filter((s) => {
            const o = byId[s.orderId];
            return o && !DONE.includes(o.status);
          });
          const load = remaining.reduce((a, s) => a + (byId[s.orderId]?.weight || 0), 0);
          const pct = Math.min(100, Math.round((load / v.capacityWeight) * 100));
          const broken = v.status === "BROKEN";
          const next = remaining[0] ? byId[remaining[0].orderId] : null;
          const tone = STATUS_TONE[v.status];

          return (
            <div key={v.id} className="rounded-lg border border-line bg-surface2/60 p-3">
              <div className="flex items-center gap-2.5">
                <span
                  className="grid h-9 w-9 flex-none place-items-center rounded-lg text-sm font-semibold text-slate-950"
                  style={{ background: broken ? "#ef4444" : v.color }}
                >
                  {v.driver.charAt(0)}
                </span>
                <div className="min-w-0">
                  <div className="truncate text-sm font-medium text-ink">{v.driver}</div>
                  <div className="text-[11px] text-faint">
                    {v.name} · {v.speedKmh} km/h
                  </div>
                </div>
                <div className="ml-auto flex items-center gap-1.5">
                  <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${tone.cls}`}>
                    {tone.label}
                  </span>
                  <button
                    onClick={() => openEdit(v)}
                    aria-label={`Edit ${v.name}`}
                    title="Edit driver"
                    className="rounded p-1 text-faint transition hover:bg-surface3 hover:text-ink"
                  >
                    <Pencil width={13} height={13} />
                  </button>
                  <button
                    onClick={() => deleteVehicle(v.id)}
                    aria-label={`Delete ${v.name}`}
                    title="Delete driver"
                    className="rounded p-1 text-faint transition hover:bg-rose-500/20 hover:text-rose-400"
                  >
                    <Trash width={13} height={13} />
                  </button>
                </div>
              </div>
              <div className="mt-2.5 flex items-center gap-2">
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-surface3">
                  <div
                    className="h-full rounded-full transition-all"
                    style={{ width: `${pct}%`, background: pct > 90 ? "#f97316" : v.color }}
                  />
                </div>
                <span className="font-mono text-[10px] tabular-nums text-faint">
                  {load}/{v.capacityWeight}kg
                </span>
              </div>

              <div className="mt-2 flex items-center justify-between gap-2">
                <div className="min-w-0 text-[11px] text-faint">
                  {broken ? (
                    <span className="text-rose-400">Out of service — orders reassigned</span>
                  ) : (
                    <span>
                      {remaining.length} stops left
                      {next && (
                        <>
                          {" "}
                          · next <span className="text-muted">{next.label}</span> @ {next.eta != null ? fmtTime(next.eta) : "—"}
                        </>
                      )}
                    </span>
                  )}
                </div>
                <button
                  onClick={() => toggleBreakdown(v.id)}
                  aria-label={broken ? `Mark ${v.name} repaired` : `Report ${v.name} broken down`}
                  className={`flex-none rounded px-2 py-1 text-[10px] font-semibold uppercase tracking-wide transition ${
                    broken
                      ? "bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25"
                      : "bg-rose-500/15 text-rose-300 hover:bg-rose-500/25"
                  }`}
                >
                  {broken ? "Repair" : "Break"}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
