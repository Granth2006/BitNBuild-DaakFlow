// Socket.IO client for the DaakFlow realtime layer (Phase 7).
//
// The backend (app/main.py) mounts a Socket.IO server that broadcasts live world
// state. This module owns a single shared connection to it; the world store
// (useWorldStore) subscribes to the broadcast events and mirrors them into React
// state. Commands still go over REST (see api.ts) — sockets are broadcast-only.
//
// Server -> client events (all camelCase JSON, matching ./types.ts):
//   state:update   -> full WorldSnapshot
//   vehicle:move   -> { simTime, vehicles:[{id,location,progress,status}], completed:[orderId], running }
//   plan:changed   -> { plan, metrics }
//   event:applied  -> WorldEvent

import { io, type Socket } from "socket.io-client";
import { API_BASE } from "./api";

let socket: Socket | null = null;

// Lazily create (once) the shared connection to the backend's Socket.IO server.
// Called from the store's init() inside a browser-only effect, so it never runs
// during SSR / prerender.
export function getSocket(): Socket {
  if (socket) return socket;
  socket = io(API_BASE, {
    // Force a pure WebSocket connection so we never spend the first frames on
    // HTTP long-polling (which adds request/round-trip latency before the
    // transport upgrades). The backend Socket.IO server speaks WebSocket, so
    // there is no need for the polling fallback on localhost/dev.
    transports: ["websocket"],
    autoConnect: true,
  });
  return socket;
}
