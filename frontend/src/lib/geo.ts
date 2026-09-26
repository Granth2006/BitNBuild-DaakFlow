import type { LatLng } from "./types";

const EARTH_R = 6371; // km

function toRad(d: number): number {
  return (d * Math.PI) / 180;
}

// Great-circle distance in km.
export function haversineKm(a: LatLng, b: LatLng): number {
  const dLat = toRad(b.lat - a.lat);
  const dLng = toRad(b.lng - a.lng);
  const lat1 = toRad(a.lat);
  const lat2 = toRad(b.lat);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLng / 2) ** 2;
  return 2 * EARTH_R * Math.asin(Math.sqrt(h));
}

// Rough on-road distance: straight line inflated by a road factor.
export function roadKm(a: LatLng, b: LatLng): number {
  return haversineKm(a, b) * 1.3;
}

// Travel time in minutes, optionally scaled by a traffic factor (>=1).
export function travelMin(
  a: LatLng,
  b: LatLng,
  speedKmh: number,
  trafficFactor = 1,
): number {
  if (speedKmh <= 0) return Infinity;
  return (roadKm(a, b) / speedKmh) * 60 * trafficFactor;
}

// Linear interpolation between two points, t in [0,1].
export function lerp(a: LatLng, b: LatLng, t: number): LatLng {
  return {
    lat: a.lat + (b.lat - a.lat) * t,
    lng: a.lng + (b.lng - a.lng) * t,
  };
}

// Format minutes-from-midnight as HH:MM.
export function fmtTime(min: number): string {
  const m = ((Math.round(min) % 1440) + 1440) % 1440;
  const hh = Math.floor(m / 60);
  const mm = m % 60;
  return `${String(hh).padStart(2, "0")}:${String(mm).padStart(2, "0")}`;
}

// Parse "HH:MM" into minutes-from-midnight (inverse of fmtTime).
export function parseTime(hhmm: string): number {
  const [h, m] = hhmm.split(":");
  const hh = parseInt(h, 10);
  const mm = parseInt(m, 10);
  return (Number.isNaN(hh) ? 0 : hh) * 60 + (Number.isNaN(mm) ? 0 : mm);
}
