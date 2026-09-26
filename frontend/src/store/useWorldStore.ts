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
  VehicleType,
  Section,
  Reassignment,
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
  VEHICLE_TYPE_META,
  VEHICLE_HUES,
} from "../mock/seed";

let evtSeq = 0;
let vehSeq = 0;
let ordSeq = 0;

// Form payloads the management panels hand to the CRUD actions.
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

interface WorldState {
  depot: Depot;
  vehicles: Vehicle[];
  orders: Order[];
  plan: Plan;
  assignments: Record<string, OrderAssignment>;
  metrics: Metrics | null;

  // Snapshot of the initial 08:00 world — the "no re-optimization" baseline
  // that projectStatic() replays for the before/after comparison.
  initialPlan: Plan;
  initialVehicles: Vehicle[];

  simTime: number;
  running: boolean;
  speed: number; // sim minutes advanced per tick
  trafficFactor: number;
  events: WorldEvent[];
  selectedId: string | null;

  // Dashboard shell state.
  activeSection: Section;
  focusVehicleId: string | null; // map: show one driver's route, null = all

  init: () => void;
  reset: () => void;
  play: () => void;
  pause: () => void;
  setSpeed: (s: number) => void;
  tick: () => void;
  reoptimize: () => void;
  select: (id: string | null) => void;
  setSection: (s: Section) => void;
  setFocus: (id: string | null) => void;

  // Event simulator (disruptions — these emit a WorldEvent).
  fireEvent: (type: EventType) => void;
  cancelOrder: (id: string) => void;
  toggleBreakdown: (id: string) => void;

  // Management (CRUD — re-optimizes silently, emits no disruption event).
  addVehicle: (draft: VehicleDraft) => void;
  updateVehicle: (id: string, patch: Partial<VehicleDraft>) => void;
  deleteVehicle: (id: string) => void;
  addOrder: (draft: OrderDraft) => void;
  updateOrder: (id: string, patch: Partial<OrderDraft>) => void;
  deleteOrder: (id: string) => void;
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

// Diff two plans into a list of orders that moved vehicles (or in/out of the plan).
// Drives the live "order reassignment" feed in the simulator.
function diffReassignments(
  prevPlan: Plan,
  nextPlan: Plan,
  assignments: Record<string, OrderAssignment>,
  orders: Order[],
): Reassignment[] {
  const labelOf: Record<string, string> = {};
  for (const o of orders) labelOf[o.id] = o.label;
  const prevV: Record<string, string> = {};
  for (const vid of Object.keys(prevPlan))
    for (const st of prevPlan[vid]) prevV[st.orderId] = vid;
  const nextV: Record<string, string> = {};
  for (const vid of Object.keys(nextPlan))
    for (const st of nextPlan[vid]) nextV[st.orderId] = vid;
  const out: Reassignment[] = [];
  const ids = new Set([...Object.keys(prevV), ...Object.keys(nextV)]);
  for (const id of ids) {
    const from = prevV[id] ?? null;
    const to = assignments[id]?.status === "DROPPED" ? null : nextV[id] ?? null;
    if (from !== to) out.push({ orderId: id, label: labelOf[id] ?? id, from, to });
  }
  return out;
}

export const useWorldStore = create<WorldState>((set, get) => {
  // Re-optimize against a new world state and push the result. Used by every
  // silent management action (CRUD) and by reoptimize(); event actions inline
  // their own optimize() call so they can also emit a WorldEvent.
  const commit = (
    vehicles: Vehicle[],
    orders: Order[],
    trafficFactor: number,
    extra: Partial<WorldState> = {},
  ) => {
    const s = get();
    const res = optimize({
      depot: s.depot,
      vehicles,
      orders,
      simTime: s.simTime,
      trafficFactor,
      previousPlan: s.plan,
    });
    set({
      vehicles,
      orders: applyAssignments(orders, res.assignments),
      trafficFactor,
      plan: res.plan,
      assignments: res.assignments,
      metrics: res.metrics,
      ...extra,
    });
  };

  return {
    depot: DEPOT,
    vehicles: [],
    orders: [],
    plan: {},
    assignments: {},
    metrics: null,
    initialPlan: {},
    initialVehicles: [],
    simTime: DAY_START,
    running: false,
    speed: 3,
    trafficFactor: 1,
    events: [],
    selectedId: null,
    activeSection: "overview",
    focusVehicleId: null,

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
        // Freeze the committed 08:00 world so projectStatic() can replay it.
        initialPlan: res.plan,
        initialVehicles: vehicles.map((v) => ({
          ...v,
          location: { ...v.location },
          home: { ...v.home },
        })),
        simTime: DAY_START,
        running: false,
        speed: 3,
        trafficFactor: 1,
        events: [],
        selectedId: null,
        focusVehicleId: null,
      });
    },

    reset: () => get().init(),
    play: () => set({ running: true }),
    pause: () => set({ running: false }),
    setSpeed: (s) => set({ speed: s }),
    select: (id) => set({ selectedId: id }),
    setSection: (section) => set({ activeSection: section }),
    setFocus: (id) => set({ focusVehicleId: id }),

    reoptimize: () => {
      const s = get();
      commit(s.vehicles, s.orders, s.trafficFactor);
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
      const reassignments = diffReassignments(s.plan, res.plan, res.assignments, orders);
      const evt: WorldEvent = {
        id: `e${++evtSeq}`,
        type,
        description: EVENT_LABEL[type],
        simTime: s.simTime,
        affectedVehicles,
        affectedOrders,
        reoptMs: res.metrics.reoptMs,
        routeChanges: res.metrics.routeChanges,
        reassignments,
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
      const reassignments = diffReassignments(s.plan, res.plan, res.assignments, orders);
      const evt: WorldEvent = {
        id: `e${++evtSeq}`,
        type: "CANCELLATION",
        description: `Order ${target.label} cancelled`,
        simTime: s.simTime,
        affectedVehicles: [],
        affectedOrders: [id],
        reoptMs: res.metrics.reoptMs,
        routeChanges: res.metrics.routeChanges,
        reassignments,
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
      const reassignments = diffReassignments(s.plan, res.plan, res.assignments, orders);
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
        reassignments,
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

    addVehicle: (draft) => {
      const s = get();
      const meta = VEHICLE_TYPE_META[draft.type];
      const v: Vehicle = {
        id: `v-usr-${++vehSeq}`,
        name: draft.name.trim() || `${meta.label} ${s.vehicles.length + 1}`,
        type: draft.type,
        color: VEHICLE_HUES[s.vehicles.length % VEHICLE_HUES.length],
        location: { ...s.depot.location },
        home: { ...s.depot.location },
        capacityWeight: draft.capacityWeight,
        capacityVolume: meta.capacityVolume,
        speedKmh: draft.speedKmh,
        status: "ACTIVE",
        driver: draft.driver.trim() || "Unassigned",
        driverAvailable: true,
        shiftStart: DAY_START,
        shiftEnd: DAY_END,
        progress: 0,
      };
      commit([...s.vehicles, v], s.orders, s.trafficFactor);
    },

    updateVehicle: (id, patch) => {
      const s = get();
      const vehicles = s.vehicles.map((v) => {
        if (v.id !== id) return v;
        const next = { ...v };
        if (patch.name !== undefined) next.name = patch.name.trim() || v.name;
        if (patch.driver !== undefined) next.driver = patch.driver.trim() || v.driver;
        if (patch.capacityWeight !== undefined) next.capacityWeight = patch.capacityWeight;
        if (patch.speedKmh !== undefined) next.speedKmh = patch.speedKmh;
        if (patch.type !== undefined && patch.type !== v.type) {
          next.type = patch.type;
          next.capacityVolume = VEHICLE_TYPE_META[patch.type].capacityVolume;
        }
        return next;
      });
      commit(vehicles, s.orders, s.trafficFactor);
    },

    deleteVehicle: (id) => {
      const s = get();
      const vehicles = s.vehicles.filter((v) => v.id !== id);
      // Free that vehicle's unfinished orders back into the pool.
      const orders = s.orders.map((o) =>
        o.assignedVehicle === id &&
        o.status !== "COMPLETED" &&
        o.status !== "CANCELLED"
          ? { ...o, status: "PENDING" as const, assignedVehicle: null, seqIndex: null, eta: null }
          : o,
      );
      const extra: Partial<WorldState> =
        s.focusVehicleId === id ? { focusVehicleId: null } : {};
      commit(vehicles, orders, s.trafficFactor, extra);
    },

    addOrder: (draft) => {
      const s = get();
      const o: Order = {
        id: `o-usr-${++ordSeq}`,
        label: `U${ordSeq}`,
        location: { lat: draft.lat, lng: draft.lng },
        address: draft.address.trim() || "Custom stop",
        windowStart: draft.windowStart,
        windowEnd: draft.windowEnd,
        weight: draft.weight,
        volume: Math.max(1, Math.round(draft.weight / 8)),
        priority: draft.priority,
        status: "PENDING",
        assignedVehicle: null,
        seqIndex: null,
        eta: null,
        createdAt: s.simTime,
      };
      commit(s.vehicles, [...s.orders, o], s.trafficFactor);
    },

    updateOrder: (id, patch) => {
      const s = get();
      const orders = s.orders.map((o) => {
        if (o.id !== id) return o;
        const next = { ...o };
        if (patch.address !== undefined) next.address = patch.address.trim() || o.address;
        if (patch.lat !== undefined) next.location = { ...next.location, lat: patch.lat };
        if (patch.lng !== undefined) next.location = { ...next.location, lng: patch.lng };
        if (patch.weight !== undefined) {
          next.weight = patch.weight;
          next.volume = Math.max(1, Math.round(patch.weight / 8));
        }
        if (patch.priority !== undefined) next.priority = patch.priority;
        if (patch.windowStart !== undefined) next.windowStart = patch.windowStart;
        if (patch.windowEnd !== undefined) next.windowEnd = patch.windowEnd;
        return next;
      });
      commit(s.vehicles, orders, s.trafficFactor);
    },

    deleteOrder: (id) => {
      const s = get();
      const orders = s.orders.filter((o) => o.id !== id);
      const extra: Partial<WorldState> =
        s.selectedId === id ? { selectedId: null } : {};
      commit(s.vehicles, orders, s.trafficFactor, extra);
    },
  };
});
