"use client";

import { useState } from "react";
import OrderPanel from "./OrderPanel";
import VehiclePanel from "./VehiclePanel";
import EventSimulator from "./EventSimulator";
import MetricsPanel from "./MetricsPanel";
import { Package, Truck, Bolt, Activity } from "./icons";
import { useWorldStore } from "../store/useWorldStore";

type Tab = "orders" | "vehicles" | "events" | "metrics";

const TABS: { id: Tab; label: string; icon: typeof Package }[] = [
  { id: "orders", label: "Orders", icon: Package },
  { id: "vehicles", label: "Fleet", icon: Truck },
  { id: "events", label: "Events", icon: Bolt },
  { id: "metrics", label: "Metrics", icon: Activity },
];

export default function Sidebar() {
  const [tab, setTab] = useState<Tab>("orders");
  const eventCount = useWorldStore((s) => s.events.length);

  return (
    <aside className="flex w-[380px] flex-none flex-col border-l border-slate-800 bg-slate-900/40">
      <nav className="flex flex-none border-b border-slate-800">
        {TABS.map((t) => {
          const Icon = t.icon;
          const active = tab === t.id;
          return (
            <button
              key={t.id}
              onClick={() => setTab(t.id)}
              className={`relative flex flex-1 items-center justify-center gap-1.5 py-2.5 text-xs font-medium transition ${
                active
                  ? "text-slate-100"
                  : "text-slate-500 hover:text-slate-300"
              }`}
            >
              <Icon width={14} height={14} />
              {t.label}
              {t.id === "events" && eventCount > 0 && (
                <span className="ml-0.5 rounded-full bg-amber-500/20 px-1.5 text-[10px] font-semibold text-amber-300">
                  {eventCount}
                </span>
              )}
              {active && (
                <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-sky-400" />
              )}
            </button>
          );
        })}
      </nav>

      <div className="min-h-0 flex-1">
        {tab === "orders" && <OrderPanel />}
        {tab === "vehicles" && <VehiclePanel />}
        {tab === "events" && <EventSimulator />}
        {tab === "metrics" && <MetricsPanel />}
      </div>
    </aside>
  );
}
