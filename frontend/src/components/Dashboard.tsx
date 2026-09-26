"use client";

import { useEffect } from "react";
import dynamic from "next/dynamic";
import Topbar from "./Topbar";
import Sidebar from "./Sidebar";
import { useWorldStore } from "../store/useWorldStore";

// Leaflet touches `window`, so the map must never render on the server.
const MapView = dynamic(() => import("./MapView"), {
  ssr: false,
  loading: () => (
    <div className="grid h-full w-full place-items-center bg-[#0b1120] text-sm text-slate-600">
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
        <main className="relative min-w-0 flex-1">
          <MapView />
        </main>
        <Sidebar />
      </div>
    </div>
  );
}
