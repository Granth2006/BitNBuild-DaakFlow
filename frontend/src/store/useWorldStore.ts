import { create } from "zustand";
import type {
  Depot,
  Vehicle,
  Order,
  Plan,
  Metrics,
  WorldEvent,
  EventType,
  OrderStatus,
  Priority,
} from "../lib/types";
import { optimize, type OrderAssignment } from "../lib/optimizer";
import { roadKm, lerp } from "../lib/geo";
import {
  DEPOT,
  makeVehicles,
  makeOrders,
  makeOrder,
  DAY_START,
  DAY_END,
} from "../mock/seed";

let evtSeq = 0;

interface WorldState {
  depot: Depot;
  vehicles: Vehicle[];
  orders: Order[];
  plan: Plan;
  assignments: Record<string, OrderAssignment>;
  metrics: Metrics | null;
  baseline: Metrics | null; // first plan, for before/after
  simTime: number;
  running: boolean;
  speed: number; // sim minutes advanced per tick
  trafficFactor: number;
  events: WorldEvent[];
  selectedId: string | null;

  init: () => void;
  reset: () => void;
  play: () => void;
  pause: () => void;
  setSpeed: (s: number) => void;
  tick: () => void;
  reoptimize: () => void;
  select: (id: string | null) => void;

  // event simulator
  fireEvent: (type: EventType) => void;

  // targeted controls driven from the side panels
  cancelOrder: (id: string) => void;
  toggleBreakdown: (id: string) => void;
}

// Push assignment results back onto the order records.
function applyAssignments(
  orders: Order[],
  assignments: Record<string, OrderAssignment>,
): Order[] {
  return orders.map((o) => {
    const a = assignments[o.id];
    if (!a) return o;
    if (o.status === "COMPLETED" || o.status === "CANCELLED") return o;
    if (a.status === "DROPPED") {
      return { ...o, status: "DROPPED", assignedVehicle: null, seqIndex: null, eta: null };
    }
    const status: OrderStatus = o.status === "IN_PROGRESS" ? "IN_PROGRESS" : "ASSIGNED";
    return {
      ...o,
      status,
      assignedVehicle: a.vehicle,
      seqIndex: a.seq,
      eta: a.eta,
    };
  });
}

const EVENT_LABEL: Record<EventType, string> = {
  NEW_ORDER: "New order arrived",
  PRIORITY_ORDER: "Priority order arrived",
  BREAKDOWN: "Vehicle breakdown",
  TRAFFIC: "Traffic surge",
  CANCELLATION: "Order cancelled",
  TIME_CHANGE: "Delivery window changed",
  ADDRESS_CHANGE: "Delivery address changed",
};

// Choose the active vehicle with the most remaining (unfinished) stops.
function pickBreakdownTarget(
  active: Vehicle[],
  plan: Plan,
  orders: Order[],
): Vehicle {
  const done = new Set(
    orders.filter((o) => o.status === "COMPLETED").map((o) => o.id),
  );
  let best = active[0];
  let bestRemaining = -1;
  for (const v of active) {
    const remaining = (plan[v.id] || []).filter((s) => !done.has(s.orderId)).length;
    if (remaining > bestRemaining) {
      bestRemaining = remaining;
      best = v;
    }
  }
  return best;
}

export const useWorldStore = create<WorldState>((set, get) => ({
  depot: DEPOT,
  vehicles: [],
  orders: [],
  plan: {},
  assignments: {},
  metrics: null,
  baseline: null,
  simTime: DAY_START,
  running: false,
  speed: 3,
  trafficFactor: 1,
  events: [],
  selectedId: null,

  init: () => {
    const vehicles = makeVehicles();
    const orders = makeOrders();
    const res = optimize({
      depot: DEPOT,
      vehicles,
      orders,
      simTime: DAY_START,
      trafficFactor: 1,
    });
    set({
      depot: DEPOT,
      vehicles,
      orders: applyAssignments(orders, res.assignments),
      plan: res.plan,
      assignments: res.assignments,
      metrics: res.metrics,
      baseline: res.metrics,
      simTime: DAY_START,
      running: false,
      speed: 3,
      trafficFactor: 1,
      events: [],
      selectedId: null,
    });
  },

  reset: () => get().init(),
  play: () => set({ running: true }),
  pause: () => set({ running: false }),
  setSpeed: (s) => set({ speed: s }),
  select: (id) => set({ selectedId: id }),

  reoptimize: () => {
    const s = get();
    const res = optimize({
      depot: s.depot,
      vehicles: s.vehicles,
      orders: s.orders,
      simTime: s.simTime,
      trafficFactor: s.trafficFactor,
      previousPlan: s.plan,
    });
    set({
      plan: res.plan,
      assignments: res.assignments,
      metrics: res.metrics,
      orders: applyAssignments(s.orders, res.assignments),
    });
  },

  tick: () => {
    const s = get();
    if (!s.running) return;
    const simTime = Math.min(DAY_END, s.simTime + s.speed);
    const vehicles = s.vehicles.map((v) => ({ ...v, location: { ...v.location } }));
    const orders = s.orders.map((o) => ({ ...o }));
    const byId: Record<string, Order> = {};
    for (const o of orders) byId[o.id] = o;

    for (const v of vehicles) {
      if (v.status !== "ACTIVE" || !v.driverAvailable) continue;
      let budget = (s.speed * (v.speedKmh / Math.max(1, s.trafficFactor))) / 60; // km
      for (const stop of s.plan[v.id] || []) {
        const o = byId[stop.orderId];
        if (!o || o.status === "COMPLETED" || o.status === "CANCELLED" || o.status === "DROPPED")
          continue;
        if (o.status === "ASSIGNED") o.status = "IN_PROGRESS";
        o.assignedVehicle = v.id;
        const d = roadKm(v.location, o.location);
        if (budget >= d) {
          budget -= d;
          v.location = { ...o.location };
          o.status = "COMPLETED";
          o.eta = simTime;
        } else {
          v.location = lerp(v.location, o.location, d > 0 ? budget / d : 1);
          budget = 0;
          break;
        }
      }
    }
    set({ simTime, vehicles, orders, running: simTime < DAY_END });
  },

  fireEvent: (type) => {
    const s = get();
    let vehicles = s.vehicles;
    let orders = s.orders;
    let trafficFactor = s.trafficFactor;
    const affectedVehicles: string[] = [];
    const affectedOrders: string[] = [];
    const rand = <T,>(arr: T[]): T => arr[Math.floor(Math.random() * arr.length)];

    if (type === "NEW_ORDER" || type === "PRIORITY_ORDER") {
      const o =
        type === "PRIORITY_ORDER"
          ? makeOrder(s.simTime, { priority: 4 as Priority, tightWindow: true })
          : makeOrder(s.simTime);
      orders = [...orders, o];
      affectedOrders.push(o.id);
    } else if (type === "BREAKDOWN") {
      const active = vehicles.filter((v) => v.status === "ACTIVE" && v.driverAvailable);
      if (active.length) {
        const target = pickBreakdownTarget(active, s.plan, orders);
        affectedVehicles.push(target.id);
        vehicles = vehicles.map((v) =>
          v.id === target.id ? { ...v, status: "BROKEN", driverAvailable: false } : v,
        );
        orders = orders.map((o) => {
          if (o.assignedVehicle === target.id && o.status !== "COMPLETED") {
            affectedOrders.push(o.id);
            return { ...o, status: "PENDING", assignedVehicle: null, seqIndex: null, eta: null };
          }
          return o;
        });
      }
    } else if (type === "TRAFFIC") {
      trafficFactor = Math.min(2.4, +(trafficFactor + 0.6).toFixed(2));
      affectedVehicles.push(...vehicles.filter((v) => v.status === "ACTIVE").map((v) => v.id));
    } else if (type === "CANCELLATION") {
      const cand = orders.filter((o) => o.status === "ASSIGNED" || o.status === "PENDING");
      if (cand.length) {
        const pick = rand(cand);
        affectedOrders.push(pick.id);
        orders = orders.map((o) =>
          o.id === pick.id
            ? { ...o, status: "CANCELLED", assignedVehicle: null, seqIndex: null, eta: null }
            : o,
        );
      }
    } else if (type === "TIME_CHANGE") {
      const cand = orders.filter(
        (o) => o.status === "ASSIGNED" || o.status === "PENDING" || o.status === "IN_PROGRESS",
      );
      if (cand.length) {
        const pick = rand(cand);
        affectedOrders.push(pick.id);
        orders = orders.map((o) => {
          if (o.id !== pick.id) return o;
          const we = Math.max(s.simTime + 40, o.windowEnd - 90);
          return { ...o, windowEnd: we, windowStart: Math.min(o.windowStart, we - 30) };
        });
      }
    } else if (type === "ADDRESS_CHANGE") {
      const cand = orders.filter((o) => o.status === "ASSIGNED" || o.status === "PENDING");
      if (cand.length) {
        const pick = rand(cand);
        affectedOrders.push(pick.id);
        orders = orders.map((o) =>
          o.id === pick.id
            ? {
                ...o,
                location: { lat: 12.9 + Math.random() * 0.15, lng: 77.53 + Math.random() * 0.24 },
                address: "Relocated stop",
              }
            : o,
        );
      }
    }
    const res = optimize({
      depot: s.depot,
      vehicles,
      orders,
      simTime: s.simTime,
      trafficFactor,
      previousPlan: s.plan,
    });
    const evt: WorldEvent = {
      id: `e${++evtSeq}`,
      type,
      description: EVENT_LABEL[type],
      simTime: s.simTime,
      affectedVehicles,
      affectedOrders,
      reoptMs: res.metrics.reoptMs,
      routeChanges: res.metrics.routeChanges,
    };
    set({
      vehicles,
      trafficFactor,
      plan: res.plan,
      assignments: res.assignments,
      metrics: res.metrics,
      orders: applyAssignments(orders, res.assignments),
      events: [evt, ...s.events],
    });
  },

  cancelOrder: (id) => {
    const s = get();
    const target = s.orders.find((o) => o.id === id);
    if (!target || target.status === "COMPLETED" || target.status === "CANCELLED")
      return;
    const orders = s.orders.map((o) =>
      o.id === id
        ? { ...o, status: "CANCELLED" as const, assignedVehicle: null, seqIndex: null, eta: null }
        : o,
    );
    const res = optimize({
      depot: s.depot,
      vehicles: s.vehicles,
      orders,
      simTime: s.simTime,
      trafficFactor: s.trafficFactor,
      previousPlan: s.plan,
    });
    const evt: WorldEvent = {
      id: `e${++evtSeq}`,
      type: "CANCELLATION",
      description: `Order ${target.label} cancelled`,
      simTime: s.simTime,
      affectedVehicles: [],
      affectedOrders: [id],
      reoptMs: res.metrics.reoptMs,
      routeChanges: res.metrics.routeChanges,
    };
    set({
      plan: res.plan,
      assignments: res.assignments,
      metrics: res.metrics,
      orders: applyAssignments(orders, res.assignments),
      events: [evt, ...s.events],
    });
  },

  toggleBreakdown: (id) => {
    const s = get();
    const target = s.vehicles.find((v) => v.id === id);
    if (!target) return;
    const breaking = target.status !== "BROKEN";
    const vehicles = s.vehicles.map((v) =>
      v.id === id
        ? breaking
          ? { ...v, status: "BROKEN" as const, driverAvailable: false }
          : { ...v, status: "ACTIVE" as const, driverAvailable: true }
        : v,
    );
    const affectedOrders: string[] = [];
    const orders = breaking
      ? s.orders.map((o) => {
          if (o.assignedVehicle === id && o.status !== "COMPLETED") {
            affectedOrders.push(o.id);
            return { ...o, status: "PENDING" as const, assignedVehicle: null, seqIndex: null, eta: null };
          }
          return o;
        })
      : s.orders;
    const res = optimize({
      depot: s.depot,
      vehicles,
      orders,
      simTime: s.simTime,
      trafficFactor: s.trafficFactor,
      previousPlan: s.plan,
    });
    const evt: WorldEvent = {
      id: `e${++evtSeq}`,
      type: "BREAKDOWN",
      description: breaking
        ? `${target.name} broke down`
        : `${target.name} back in service`,
      simTime: s.simTime,
      affectedVehicles: [id],
      affectedOrders,
      reoptMs: res.metrics.reoptMs,
      routeChanges: res.metrics.routeChanges,
    };
    set({
      vehicles,
      plan: res.plan,
      assignments: res.assignments,
      metrics: res.metrics,
      orders: applyAssignments(orders, res.assignments),
      events: [evt, ...s.events],
    });
  },
}));
