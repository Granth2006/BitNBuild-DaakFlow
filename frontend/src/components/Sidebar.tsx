"use client";

import { useState } from "react";
import { useWorldStore } from "../store/useWorldStore";
import OverviewPanel from "./OverviewPanel";
import OrderPanel from "./OrderPanel";
import DriverPanel from "./DriverPanel";
import EventConsole from "./EventConsole";
import BeforeAfterPanel from "./BeforeAfterPanel";
import { Grid, Package, Users, Bolt, TrendingDown, ChevronLeft, Truck } from "./icons";

export type Section = "overview" | "orders" | "drivers" | "simulator" | "compare";

const SECTIONS: { id: Section; label: string; desc: string; icon: typeof Grid }[] = [
  { id: "overview", label: "Overview", desc: "Live operations summary", icon: Grid },
  { id: "orders", label: "Orders", desc: "Delivery queue & management", icon: Package },
  { id: "drivers", label: "Drivers", desc: "Fleet & driver status", icon: Users },
  { id: "simulator", label: "Event Simulator", desc: "Inject disruptions · watch re-routing", icon: Bolt },
  { id: "compare", label: "Before / After", desc: "Impact of adaptive routing", icon: TrendingDown },
];

export default function Sidebar() {
  const [active, setActive] = useState<Section>("overview");
  const [open, setOpen] = useState(true);
  const eventCount = useWorldStore((s) => s.events.length);
  const meta = SECTIONS.find((s) => s.id === active)!;

  return (
    <aside className="flex h-full flex-none">
      {/* icon rail — always visible */}
      <nav
        className="flex w-14 flex-none flex-col items-center gap-1 border-r border-line bg-surface/60 py-3"
        aria-label="Dashboard sections"
      >
        <span
          className="mb-2 grid h-9 w-9 place-items-center rounded-lg bg-brand2/15 text-brand"
          aria-hidden="true"
        >
          <Truck width={18} height={18} />
        </span>
        {SECTIONS.map((s) => {
          const Icon = s.icon;
          const isActive = s.id === active;
          return (
            <button
              key={s.id}
              onClick={() => {
                setActive(s.id);
                setOpen(true);
              }}
              title={s.label}
              aria-label={s.id === "simulator" && eventCount > 0 ? `${s.label}, ${eventCount} new events` : s.label}
              aria-current={isActive ? "page" : undefined}
              className={`relative grid h-10 w-10 place-items-center rounded-lg transition ${
                isActive ? "bg-surface3 text-ink" : "text-faint hover:bg-surface2 hover:text-muted"
              }`}
            >
              <Icon width={18} height={18} />
              {s.id === "simulator" && eventCount > 0 && (
                <span className="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-amber-500 px-1 text-[9px] font-bold text-slate-950" aria-hidden="true">
                  {eventCount}
                </span>
              )}
              {isActive && (
                <span className="absolute left-0 top-1/2 h-5 w-0.5 -translate-y-1/2 rounded-r bg-brand" />
              )}
            </button>
          );
        })}
        <button
          onClick={() => setOpen((o) => !o)}
          title={open ? "Collapse panel" : "Expand panel"}
          aria-label={open ? "Collapse panel" : "Expand panel"}
          aria-expanded={open}
          className="mt-auto grid h-10 w-10 place-items-center rounded-lg text-faint transition hover:bg-surface2 hover:text-muted"
        >
          <ChevronLeft width={18} height={18} className={`transition-transform ${open ? "" : "rotate-180"}`} />
        </button>
      </nav>

      {/* section panel — collapses away */}
      {open && (
        <div className="flex w-[340px] flex-none flex-col border-r border-line bg-surface/40">
          <header className="flex-none border-b border-line px-4 py-3">
            <h2 className="text-sm font-semibold text-ink">{meta.label}</h2>
            <p className="mt-0.5 text-[11px] text-faint">{meta.desc}</p>
          </header>
          <div key={active} className="fade-in min-h-0 flex-1">
            {active === "overview" && <OverviewPanel onJump={setActive} />}
            {active === "orders" && <OrderPanel />}
            {active === "drivers" && <DriverPanel />}
            {active === "simulator" && <EventConsole />}
            {active === "compare" && <BeforeAfterPanel />}
          </div>
        </div>
      )}
    </aside>
  );
}
