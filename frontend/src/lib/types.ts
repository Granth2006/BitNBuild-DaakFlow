// Core domain types for the adaptive delivery routing system.

export type LatLng = { lat: number; lng: number };

export type Priority = 1 | 2 | 3 | 4; // 4 = critical

export type OrderStatus =
  | "PENDING"
  | "ASSIGNED"
  | "IN_PROGRESS"
  | "COMPLETED"
  | "CANCELLED"
  | "DROPPED";

export interface Order {
  id: string;
  label: string;
  location: LatLng;
  address: string;
  windowStart: number; // minutes from start of sim day
  windowEnd: number;
  weight: number; // kg
  volume: number; // arbitrary units
  priority: Priority;
  status: OrderStatus;
  assignedVehicle: string | null;
  seqIndex: number | null;
  eta: number | null; // minutes
  createdAt: number; // sim time when the order entered the system
}

export type VehicleStatus = "ACTIVE" | "BROKEN" | "IDLE";

export interface Vehicle {
  id: string;
  name: string;
  color: string;
  location: LatLng; // live position
  home: LatLng; // depot location
  capacityWeight: number;
  capacityVolume: number;
  speedKmh: number;
  status: VehicleStatus;
  driver: string;
  driverAvailable: boolean;
  shiftStart: number; // minutes
  shiftEnd: number; // minutes — working-hour limit
  progress: number; // 0..1 along the current leg (for animation)
}

export interface Depot {
  id: string;
  name: string;
  location: LatLng;
}

export interface RouteStop {
  orderId: string;
  seq: number;
  eta: number; // minutes
  locked: boolean;
}

export type Plan = Record<string, RouteStop[]>; // vehicleId -> ordered stops

export interface Metrics {
  totalDistanceKm: number;
  totalTimeMin: number;
  lateDeliveries: number;
  routeChanges: number;
  utilizationPct: number;
  reoptMs: number;
  dropped: number;
}

export type EventType =
  | "NEW_ORDER"
  | "PRIORITY_ORDER"
  | "BREAKDOWN"
  | "TRAFFIC"
  | "CANCELLATION"
  | "TIME_CHANGE"
  | "ADDRESS_CHANGE";

export interface WorldEvent {
  id: string;
  type: EventType;
  description: string;
  simTime: number;
  affectedVehicles: string[];
  affectedOrders: string[];
  reoptMs: number;
  routeChanges: number;
}
