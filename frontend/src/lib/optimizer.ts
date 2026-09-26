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
// __APPEND__

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
// __APPEND__


