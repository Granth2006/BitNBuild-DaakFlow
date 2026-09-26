import type { Priority, OrderStatus } from "./types";

// Distinct, high-contrast hues for vehicle routes on the dark map.
export const VEHICLE_COLORS = [
  "#38bdf8", // cyan
  "#a78bfa", // violet
  "#4ade80", // green
  "#fb7185", // rose
  "#fbbf24", // amber
  "#f472b6", // pink
  "#2dd4bf", // teal
];

export const PRIORITY_META: Record<Priority, { label: string; color: string }> = {
  1: { label: "Low", color: "#64748b" },
  2: { label: "Medium", color: "#eab308" },
  3: { label: "High", color: "#f97316" },
  4: { label: "Critical", color: "#ef4444" },
};

export const STATUS_META: Record<OrderStatus, { label: string; color: string }> = {
  PENDING: { label: "Pending", color: "#94a3b8" },
  ASSIGNED: { label: "Assigned", color: "#38bdf8" },
  IN_PROGRESS: { label: "In progress", color: "#22d3ee" },
  COMPLETED: { label: "Completed", color: "#4ade80" },
  CANCELLED: { label: "Cancelled", color: "#475569" },
  DROPPED: { label: "Dropped", color: "#ef4444" },
};

export function colorForVehicle(index: number): string {
  return VEHICLE_COLORS[index % VEHICLE_COLORS.length];
}
