"""Distance-matrix service.

Primary path: OSRM/ORS road distances (only when ``OSRM_URL`` is configured).
Fallback: haversine great-circle distance x 1.3 road factor — fully offline,
matching ``frontend/src/lib/geo.ts`` (``roadKm``). Results are cached in memory.
"""

from __future__ import annotations

import math
from typing import Optional

import httpx

from .config import settings
from .models import LatLng

EARTH_R_KM = 6371.0
ROAD_FACTOR = 1.3


def haversine_km(a: LatLng, b: LatLng) -> float:
    """Great-circle distance in km (mirror of geo.ts haversineKm)."""
    d_lat = math.radians(b.lat - a.lat)
    d_lng = math.radians(b.lng - a.lng)
    lat1 = math.radians(a.lat)
    lat2 = math.radians(b.lat)
    h = math.sin(d_lat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(d_lng / 2) ** 2
    return 2 * EARTH_R_KM * math.asin(math.sqrt(h))


def road_km(a: LatLng, b: LatLng) -> float:
    """Straight-line distance inflated by the road factor (geo.ts roadKm)."""
    return haversine_km(a, b) * ROAD_FACTOR


def travel_min(a: LatLng, b: LatLng, speed_kmh: float, traffic_factor: float = 1.0) -> float:
    """Travel time in minutes, scaled by traffic factor (>= 1)."""
    if speed_kmh <= 0:
        return math.inf
    return (road_km(a, b) / speed_kmh) * 60.0 * traffic_factor


class DistanceService:
    def __init__(self, osrm_url: Optional[str] = None) -> None:
        # Explicit arg wins; else settings; blank string counts as "unset".
        self.osrm_url = (osrm_url if osrm_url is not None else settings.osrm_url) or None
        self._cache: dict[tuple[float, float, float, float], float] = {}
        self.last_source: str = "haversine"

    @staticmethod
    def _key(a: LatLng, b: LatLng) -> tuple[float, float, float, float]:
        return (round(a.lat, 5), round(a.lng, 5), round(b.lat, 5), round(b.lng, 5))

    def distance_km(self, a: LatLng, b: LatLng) -> float:
        key = self._key(a, b)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        dist: Optional[float] = None
        if self.osrm_url:
            dist = self._osrm_distance(a, b)
        if dist is None:
            dist = road_km(a, b)
            self.last_source = "haversine"
        else:
            self.last_source = "osrm"
        self._cache[key] = dist
        return dist

    def _osrm_distance(self, a: LatLng, b: LatLng) -> Optional[float]:
        """Try OSRM; any failure returns None so the caller falls back."""
        try:
            url = f"{self.osrm_url.rstrip('/')}/route/v1/driving/{a.lng},{a.lat};{b.lng},{b.lat}"
            resp = httpx.get(url, params={"overview": "false"}, timeout=3.0)
            resp.raise_for_status()
            payload = resp.json()
            routes = payload.get("routes") or []
            if not routes:
                return None
            return float(routes[0]["distance"]) / 1000.0
        except Exception:
            return None

    def matrix(self, points: list[LatLng]) -> list[list[float]]:
        n = len(points)
        return [
            [0.0 if i == j else self.distance_km(points[i], points[j]) for j in range(n)]
            for i in range(n)
        ]

    def cache_size(self) -> int:
        return len(self._cache)


# Module-level singleton.
distances = DistanceService()
