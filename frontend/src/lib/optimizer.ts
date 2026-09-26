import type {
  Depot,
  Vehicle,
  Order,
  Plan,
  RouteStop,
  Metrics,
  OrderStatus,
  LatLng,
} from "./types";
import { roadKm, travelMin } from "./geo";

const SERVICE_MIN = 5; // minutes spent servicing each delivery
const LATE_SLACK = 0; // grace minutes before a stop counts as late

export interface OptimizeInput {
  depot: Depot;
  vehicles: Vehicle[];
  orders: Order[];
  simTime: number;
  trafficFactor: number;
  previousPlan?: Plan;
}

export interface OrderAssignment {
  vehicle: string | null;
  seq: number | null;
  eta: number | null;
  status: OrderStatus;
}

export interface OptimizeResult {
  plan: Plan;
  assignments: Record<string, OrderAssignment>;
  metrics: Metrics;
}

interface VState {
  v: Vehicle;
  stops: string[]; // order ids in visit order
  lockedCount: number; // number of leading frozen stops
  load: number;
}

function orderMap(orders: Order[]): Record<string, Order> {
  const m: Record<string, Order> = {};
  for (const o of orders) m[o.id] = o;
  return m;
}

// Simulate arrival times along a stop list; returns eta (minutes) per order id.
function simulateEtas(
  start: LatLng,
  startTime: number,
  stops: string[],
  om: Record<string, Order>,
  speed: number,
  traffic: number,
): Record<string, number> {
  const etas: Record<string, number> = {};
  let cur = start;
  let t = startTime;
  for (const id of stops) {
    const o = om[id];
    t += travelMin(cur, o.location, speed, traffic);
    if (t < o.windowStart) t = o.windowStart; // wait for the window to open
    etas[id] = t;
    t += SERVICE_MIN;
    cur = o.location;
  }
  return etas;
}

// Total minutes late across a candidate stop list.
function lateness(
  start: LatLng,
  startTime: number,
  stops: string[],
  om: Record<string, Order>,
  speed: number,
  traffic: number,
): number {
  const etas = simulateEtas(start, startTime, stops, om, speed, traffic);
  let late = 0;
  for (const id of stops) {
    const over = etas[id] - om[id].windowEnd;
    if (over > LATE_SLACK) late += over;
  }
  return late;
}

// Extra road distance of inserting order o at position pos in a vehicle route.
function insertionDistance(
  start: LatLng,
  stops: string[],
  pos: number,
  o: Order,
  om: Record<string, Order>,
): number {
  const prev = pos === 0 ? start : om[stops[pos - 1]].location;
  const nextId = stops[pos];
  if (!nextId) return roadKm(prev, o.location);
  const next = om[nextId].location;
  return roadKm(prev, o.location) + roadKm(o.location, next) - roadKm(prev, next);
}

/**
 * Assign orders to vehicles and sequence each route.
 *
 * Freeze rules that make this a *re*-optimizer rather than a from-scratch solve:
 *  - COMPLETED / CANCELLED / DROPPED orders are never touched.
 *  - IN_PROGRESS orders are pinned as the first (locked) stop on their vehicle.
 *  - Each vehicle re-enters the model at its current live position.
 * Only PENDING / ASSIGNED (unvisited) orders are free to move.
 */
export function optimize(input: OptimizeInput): OptimizeResult {
  const t0 = typeof performance !== "undefined" ? performance.now() : Date.now();
  const { vehicles, orders, simTime, trafficFactor } = input;
  const om = orderMap(orders);

  const assignable = orders.filter(
    (o) =>
      o.status === "PENDING" ||
      o.status === "ASSIGNED" ||
      o.status === "IN_PROGRESS",
  );

  // Active vehicles can take free work; broken / unavailable ones cannot.
  const states: Record<string, VState> = {};
  for (const v of vehicles) {
    if (v.status !== "ACTIVE" || !v.driverAvailable) continue;
    states[v.id] = { v, stops: [], lockedCount: 0, load: 0 };
  }

  // 1) Freeze in-progress deliveries as the locked first stop per vehicle.
  for (const o of assignable) {
    if (
      o.status === "IN_PROGRESS" &&
      o.assignedVehicle &&
      states[o.assignedVehicle]
    ) {
      const st = states[o.assignedVehicle];
      st.stops.push(o.id);
      st.lockedCount += 1;
      st.load += o.weight;
    }
  }
  // 2) Everything else (PENDING / previously ASSIGNED) is free to reassign.
  const pool = assignable.filter(
    (o) =>
      !(
        o.status === "IN_PROGRESS" &&
        o.assignedVehicle &&
        states[o.assignedVehicle]
      ),
  );
  pool.sort(
    (a, b) =>
      b.priority - a.priority ||
      a.windowEnd - b.windowEnd ||
      a.createdAt - b.createdAt,
  );

  const assignments: Record<string, OrderAssignment> = {};
  for (const o of orders) {
    if (
      o.status === "COMPLETED" ||
      o.status === "CANCELLED" ||
      o.status === "DROPPED"
    ) {
      assignments[o.id] = {
        vehicle: o.assignedVehicle,
        seq: o.seqIndex,
        eta: o.eta,
        status: o.status,
      };
    }
  }

  // 3) Greedy cheapest-insertion, preferring window-feasible placements.
  for (const o of pool) {
    let best: { vid: string; pos: number; cost: number; feasible: boolean } | null =
      null;
    for (const vid of Object.keys(states)) {
      const st = states[vid];
      if (st.load + o.weight > st.v.capacityWeight) continue; // capacity limit
      const startTime = Math.max(simTime, st.v.shiftStart);
      for (let pos = st.lockedCount; pos <= st.stops.length; pos++) {
        const cand = [...st.stops.slice(0, pos), o.id, ...st.stops.slice(pos)];
        const addDist = insertionDistance(st.v.location, st.stops, pos, o, om);
        const late = lateness(
          st.v.location,
          startTime,
          cand,
          om,
          st.v.speedKmh,
          trafficFactor,
        );
        const feasible = late === 0;
        const cost = addDist + late * 2; // soft lateness penalty
        if (
          best === null ||
          (feasible && !best.feasible) ||
          (feasible === best.feasible && cost < best.cost)
        ) {
          best = { vid, pos, cost, feasible };
        }
      }
    }
    if (best) {
      const st = states[best.vid];
      st.stops.splice(best.pos, 0, o.id);
      st.load += o.weight;
    } else {
      // Nowhere feasible (capacity exhausted) — drop the lowest-value order.
      assignments[o.id] = { vehicle: null, seq: null, eta: null, status: "DROPPED" };
    }
  }
  // 4) Materialize the plan, compute final ETAs, and record assignments.
  const plan: Plan = {};
  for (const vid of Object.keys(states)) {
    const st = states[vid];
    const startTime = Math.max(simTime, st.v.shiftStart);
    const etas = simulateEtas(
      st.v.location,
      startTime,
      st.stops,
      om,
      st.v.speedKmh,
      trafficFactor,
    );
    const stops: RouteStop[] = st.stops.map((id, i) => ({
      orderId: id,
      seq: i,
      eta: etas[id],
      locked: i < st.lockedCount,
    }));
    plan[vid] = stops;
    for (const s of stops) {
      const o = om[s.orderId];
      assignments[s.orderId] = {
        vehicle: vid,
        seq: s.seq,
        eta: s.eta,
        status: o.status === "IN_PROGRESS" ? "IN_PROGRESS" : "ASSIGNED",
      };
    }
  }

  const t1 = typeof performance !== "undefined" ? performance.now() : Date.now();
  const metrics = computeMetrics(
    plan,
    vehicles,
    om,
    assignments,
    input.previousPlan,
    t1 - t0,
  );
  return { plan, assignments, metrics };
}

export function computeMetrics(
  plan: Plan,
  vehicles: Vehicle[],
  om: Record<string, Order>,
  assignments: Record<string, OrderAssignment>,
  previousPlan: Plan | undefined,
  reoptMs: number,
): Metrics {
  let dist = 0;
  let late = 0;
  let makespan = 0;
  const vById: Record<string, Vehicle> = {};
  for (const v of vehicles) vById[v.id] = v;

  for (const vid of Object.keys(plan)) {
    const v = vById[vid];
    let cur = v.location;
    for (const s of plan[vid]) {
      const o = om[s.orderId];
      dist += roadKm(cur, o.location);
      cur = o.location;
      if (s.eta > o.windowEnd) late += 1;
      if (s.eta > makespan) makespan = s.eta;
    }
  }

  const active = vehicles.filter(
    (v) => v.status === "ACTIVE" && v.driverAvailable,
  );
  let util = 0;
  if (active.length) {
    let sum = 0;
    for (const v of active) {
      const load = (plan[v.id] || []).reduce(
        (a, s) => a + om[s.orderId].weight,
        0,
      );
      sum += Math.min(1, load / v.capacityWeight);
    }
    util = (sum / active.length) * 100;
  }

  const routeChanges = previousPlan
    ? countRouteChanges(previousPlan, plan)
    : 0;
  const dropped = Object.values(assignments).filter(
    (a) => a.status === "DROPPED",
  ).length;

  return {
    totalDistanceKm: round1(dist),
    totalTimeMin: Math.round(makespan),
    lateDeliveries: late,
    routeChanges,
    utilizationPct: Math.round(util),
    reoptMs: Math.round(reoptMs),
    dropped,
  };
}

// Count stops whose (vehicle, seq) differs from the previous plan.
function countRouteChanges(prev: Plan, next: Plan): number {
  const prevPos: Record<string, string> = {};
  for (const vid of Object.keys(prev)) {
    for (const s of prev[vid]) prevPos[s.orderId] = `${vid}:${s.seq}`;
  }
  let changes = 0;
  const seen = new Set<string>();
  for (const vid of Object.keys(next)) {
    for (const s of next[vid]) {
      seen.add(s.orderId);
      if (prevPos[s.orderId] !== `${vid}:${s.seq}`) changes += 1;
    }
  }
  for (const id of Object.keys(prevPos)) {
    if (!seen.has(id)) changes += 1;
  }
  return changes;
}

function round1(n: number): number {
  return Math.round(n * 10) / 10;
}


