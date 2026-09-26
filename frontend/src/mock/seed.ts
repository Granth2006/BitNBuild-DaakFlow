import type { Depot, Vehicle, Order, Priority } from "../lib/types";

// Sim day runs 08:00 (480) to 18:00 (1080), minutes from midnight.
export const DAY_START = 480;
export const DAY_END = 1080;

// Depot: central Bengaluru.
export const DEPOT: Depot = {
  id: "depot",
  name: "Central Hub",
  location: { lat: 12.9716, lng: 77.5946 },
};

const VEHICLE_HUES = ["#38bdf8", "#a78bfa", "#4ade80", "#fb7185"];

export function makeVehicles(): Vehicle[] {
  const base = {
    home: DEPOT.location,
    capacityVolume: 100,
    status: "ACTIVE" as const,
    driverAvailable: true,
    shiftStart: DAY_START,
    shiftEnd: DAY_END,
    progress: 0,
  };
  return [
    {
      ...base,
      id: "v1",
      name: "Truck 01",
      color: VEHICLE_HUES[0],
      location: { ...DEPOT.location },
      capacityWeight: 600,
      speedKmh: 34,
      driver: "Arjun",
    },
    {
      ...base,
      id: "v2",
      name: "Truck 02",
      color: VEHICLE_HUES[1],
      location: { ...DEPOT.location },
      capacityWeight: 550,
      speedKmh: 38,
      driver: "Meera",
    },
    {
      ...base,
      id: "v3",
      name: "Van 03",
      color: VEHICLE_HUES[2],
      location: { ...DEPOT.location },
      capacityWeight: 400,
      speedKmh: 42,
      driver: "Rahul",
    },
    {
      ...base,
      id: "v4",
      name: "Van 04",
      color: VEHICLE_HUES[3],
      location: { ...DEPOT.location },
      capacityWeight: 400,
      speedKmh: 40,
      driver: "Sofia",
    },
  ];
}

interface SeedSpec {
  label: string;
  lat: number;
  lng: number;
  address: string;
  ws: number; // window start
  we: number; // window end
  weight: number;
  priority: Priority;
}

const SEED_ORDERS: SeedSpec[] = [
  { label: "A", lat: 13.0298, lng: 77.5709, address: "Hebbal", ws: 500, we: 620, weight: 80, priority: 2 },
  { label: "B", lat: 12.9345, lng: 77.6100, address: "Koramangala", ws: 510, we: 600, weight: 120, priority: 3 },
  { label: "C", lat: 12.9784, lng: 77.6408, address: "Indiranagar", ws: 520, we: 660, weight: 60, priority: 2 },
  { label: "D", lat: 12.9141, lng: 77.6412, address: "HSR Layout", ws: 540, we: 700, weight: 150, priority: 4 },
  { label: "E", lat: 12.9698, lng: 77.7500, address: "Whitefield", ws: 560, we: 780, weight: 90, priority: 1 },
  { label: "F", lat: 12.9250, lng: 77.5938, address: "Jayanagar", ws: 500, we: 640, weight: 110, priority: 3 },
  { label: "G", lat: 13.0067, lng: 77.5573, address: "Malleshwaram", ws: 530, we: 680, weight: 70, priority: 2 },
  { label: "H", lat: 12.9081, lng: 77.5679, address: "JP Nagar", ws: 520, we: 660, weight: 130, priority: 2 },
  { label: "I", lat: 12.9855, lng: 77.6060, address: "MG Road", ws: 505, we: 590, weight: 50, priority: 3 },
  { label: "J", lat: 13.0358, lng: 77.5970, address: "Yelahanka Rd", ws: 570, we: 760, weight: 100, priority: 1 },
  { label: "K", lat: 12.9569, lng: 77.7011, address: "Marathahalli", ws: 550, we: 720, weight: 140, priority: 3 },
  { label: "L", lat: 12.9121, lng: 77.6446, address: "BTM Layout", ws: 515, we: 650, weight: 65, priority: 2 },
  { label: "M", lat: 12.9992, lng: 77.6607, address: "CV Raman Nagar", ws: 560, we: 740, weight: 95, priority: 1 },
  { label: "N", lat: 12.9438, lng: 77.5738, address: "Banashankari", ws: 510, we: 630, weight: 115, priority: 4 },
  { label: "O", lat: 12.9855, lng: 77.5354, address: "Rajajinagar", ws: 525, we: 690, weight: 75, priority: 2 },
];

export function makeOrders(): Order[] {
  return SEED_ORDERS.map((s, i) => ({
    id: `o${i + 1}`,
    label: s.label,
    location: { lat: s.lat, lng: s.lng },
    address: s.address,
    windowStart: s.ws,
    windowEnd: s.we,
    weight: s.weight,
    volume: Math.round(s.weight / 8),
    priority: s.priority,
    status: "PENDING",
    assignedVehicle: null,
    seqIndex: null,
    eta: null,
    createdAt: DAY_START,
  }));
}

// Random-ish point within the metro bounding box (deterministic-friendly RNG).
const NAMES = [
  "Electronic City", "Bellandur", "Sarjapur Rd", "Hennur", "Kengeri",
  "Ulsoor", "Domlur", "RT Nagar", "Vijayanagar", "Frazer Town",
];

let genCount = 0;
export function makeOrder(
  simTime: number,
  opts: { priority?: Priority; tightWindow?: boolean } = {},
): Order {
  genCount += 1;
  const lat = 12.90 + Math.random() * 0.15;
  const lng = 77.53 + Math.random() * 0.24;
  const priority = opts.priority ?? ((1 + Math.floor(Math.random() * 3)) as Priority);
  const span = opts.tightWindow ? 60 : 120 + Math.floor(Math.random() * 120);
  const start = Math.max(simTime, DAY_START) + 10;
  return {
    id: `o-gen-${genCount}`,
    label: `#${genCount}`,
    location: { lat, lng },
    address: NAMES[Math.floor(Math.random() * NAMES.length)],
    windowStart: start,
    windowEnd: start + span,
    weight: 40 + Math.floor(Math.random() * 120),
    volume: 10,
    priority,
    status: "PENDING",
    assignedVehicle: null,
    seqIndex: null,
    eta: null,
    createdAt: simTime,
  };
}
