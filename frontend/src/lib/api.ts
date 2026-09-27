// Typed client for the DaakFlow backend API.
//
// As of Phase 7 this is the live command surface: the world store (useWorldStore)
// drives all mutations through these helpers and mirrors the backend's Socket.IO
// broadcasts (see ./socket.ts) into React state. Commands are REST; sockets are
// broadcast-only.
//
// The response shapes are typed against ./types.ts, which is the authoritative
// contract the backend mirrors (camelCase field names).

import type {
  Depot,
  Vehicle,
  Order,
  Plan,
  Metrics,
  WorldEvent,
  VehicleType,
  VehicleStatus,
  Priority,
  EventType,
} from "./types";

// Base URL of the backend. Override with NEXT_PUBLIC_API_URL at build time.
export const API_BASE =
  (typeof process !== "undefined" && process.env?.NEXT_PUBLIC_API_URL) ||
  "http://localhost:8000";

// Full world returned by GET /state — a superset the store can consume.
export interface WorldSnapshot {
  depot: Depot;
  vehicles: Vehicle[];
  orders: Order[];
  plan: Plan;
  metrics: Metrics | null;
  // Static "no re-optimization" projection of the frozen 08:00 plan, scored by
  // the same backend code as `metrics` (null until the first plan is captured).
  baseline: Metrics | null;
  simTime: number;
  trafficFactor: number;
  events: WorldEvent[];
  // Phase 7 — simulation clock state (mirrors the backend WorldState).
  running: boolean;
  speed: number;
}

// CRUD payloads — mirror the store's VehicleDraft / OrderDraft.
export interface VehicleDraft {
  name: string;
  driver: string;
  type: VehicleType;
  capacityWeight: number;
  speedKmh: number;
}

export interface OrderDraft {
  address: string;
  lat: number;
  lng: number;
  weight: number;
  priority: Priority;
  windowStart: number;
  windowEnd: number;
}

// Optional body for POST /events (mirrors the backend EventPayload). Every field
// is optional: a bare event synthesises deterministic defaults; callers may pin a
// target (orderId / vehicleId) or an order body for reproducible scenarios.
export interface EventPayloadInput {
  lat?: number;
  lng?: number;
  weight?: number;
  priority?: Priority;
  windowStart?: number;
  windowEnd?: number;
  address?: string;
  label?: string;
  vehicleId?: string;
  orderId?: string;
  factorDelta?: number;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!res.ok) {
    const detail = await res.text().catch(() => "");
    throw new Error(`${init?.method ?? "GET"} ${path} failed: ${res.status} ${detail}`);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const api = {
  health: () => request<{ status: string; db: string }>("/health"),

  // World
  getState: () => request<WorldSnapshot>("/state"),
  getDepot: () => request<Depot>("/depot"),
  seed: () => request<WorldSnapshot>("/seed", { method: "POST" }),
  reset: () => request<WorldSnapshot>("/reset", { method: "POST" }),

  // Optimization (Phase 5 cold solve / Phase 6 warm re-solve)
  optimize: () => request<WorldSnapshot>("/optimize", { method: "POST" }),
  reoptimize: () => request<WorldSnapshot>("/reoptimize", { method: "POST" }),

  // Disruptions (Phase 6) — apply a typed event, backend re-optimizes the tail.
  fireEvent: (type: EventType, payload: EventPayloadInput = {}) =>
    request<WorldEvent>("/events", {
      method: "POST",
      body: JSON.stringify({ type, payload }),
    }),

  // Simulation clock controls (Phase 7)
  simPlay: () => request<WorldSnapshot>("/sim/play", { method: "POST" }),
  simPause: () => request<WorldSnapshot>("/sim/pause", { method: "POST" }),
  simSpeed: (speed: number) =>
    request<WorldSnapshot>("/sim/speed", {
      method: "POST",
      body: JSON.stringify({ speed }),
    }),

  // Vehicles
  listVehicles: () => request<Vehicle[]>("/vehicles"),
  getVehicle: (id: string) => request<Vehicle>(`/vehicles/${id}`),
  createVehicle: (draft: VehicleDraft) =>
    request<Vehicle>("/vehicles", { method: "POST", body: JSON.stringify(draft) }),
  updateVehicle: (
    id: string,
    patch: Partial<VehicleDraft> & { status?: VehicleStatus; driverAvailable?: boolean },
  ) =>
    request<Vehicle>(`/vehicles/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteVehicle: (id: string) =>
    request<void>(`/vehicles/${id}`, { method: "DELETE" }),

  // Orders
  listOrders: () => request<Order[]>("/orders"),
  getOrder: (id: string) => request<Order>(`/orders/${id}`),
  createOrder: (draft: OrderDraft) =>
    request<Order>("/orders", { method: "POST", body: JSON.stringify(draft) }),
  updateOrder: (id: string, patch: Partial<OrderDraft>) =>
    request<Order>(`/orders/${id}`, { method: "PATCH", body: JSON.stringify(patch) }),
  deleteOrder: (id: string) =>
    request<void>(`/orders/${id}`, { method: "DELETE" }),
};

// Lightweight runtime check that a /state payload matches the expected shape.
// Useful for the opt-in "load from backend" path before feeding the store.
export function isWorldSnapshot(value: unknown): value is WorldSnapshot {
  if (typeof value !== "object" || value === null) return false;
  const v = value as Record<string, unknown>;
  return (
    typeof v.depot === "object" &&
    Array.isArray(v.vehicles) &&
    Array.isArray(v.orders) &&
    typeof v.plan === "object" &&
    typeof v.simTime === "number"
  );
}
