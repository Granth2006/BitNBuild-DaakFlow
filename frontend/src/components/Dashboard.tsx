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

export default function Dashboard() {
  useEffect(() => {
    // Connect to the backend, subscribe to live broadcasts, and load state.
    // The backend Simulator now drives the sim clock, so there is no local tick.
    useWorldStore.getState().init();
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
