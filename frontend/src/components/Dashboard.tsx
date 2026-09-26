"use client";

import { useEffect } from "react";
import dynamic from "next/dynamic";
import Topbar from "./Topbar";
import Sidebar from "./Sidebar";
import MapOverlay from "./MapOverlay";
import { useWorldStore } from "../store/useWorldStore";

// Leaflet touches `window`, so the map must never render on the server.
const MapView = dynamic(() => import("./MapView"), {
  ssr: false,
  loading: () => (
    <div className="grid h-full w-full place-items-center bg-[#e8eef5] text-sm text-slate-400">
      Loading map…
    </div>
  ),
});

const TICK_MS = 600;

export default function Dashboard() {
  useEffect(() => {
    useWorldStore.getState().init();
    const id = setInterval(() => useWorldStore.getState().tick(), TICK_MS);
    return () => clearInterval(id);
  }, []);

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden">
      <Topbar />
      <div className="flex min-h-0 flex-1">
        <Sidebar />
        <main className="min-w-0 flex-1 p-3">
          <div className="relative h-full w-full overflow-hidden rounded-xl border border-line shadow-[0_18px_50px_-24px_rgba(0,0,0,0.7)]">
            <MapView />
            <MapOverlay />
          </div>
        </main>
      </div>
    </div>
  );
}
