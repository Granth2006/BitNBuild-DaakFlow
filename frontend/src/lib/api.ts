// Typed client for the DaakFlow backend API (Phase 4).
//
// OPT-IN ONLY: nothing here is wired into the app by default — the live demo
// still runs on `mock/seed.ts` + the client-side optimizer. Full cutover is
// Phase 7. Import these helpers to load world state from the real backend.
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
  Priority,
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
  simTime: number;
  trafficFactor: number;
  events: WorldEvent[];
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

  // Vehicles
  listVehicles: () => request<Vehicle[]>("/vehicles"),
  getVehicle: (id: string) => request<Vehicle>(`/vehicles/${id}`),
  createVehicle: (draft: VehicleDraft) =>
    request<Vehicle>("/vehicles", { method: "POST", body: JSON.stringify(draft) }),
  updateVehicle: (id: string, patch: Partial<VehicleDraft>) =>
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
