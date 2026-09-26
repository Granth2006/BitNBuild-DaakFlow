"""Distance service: haversine x 1.3 fallback works offline and caches."""

from __future__ import annotations

import math

from app.distances import DistanceService, haversine_km, road_km, travel_min
from app.models import LatLng

DEPOT = LatLng(lat=12.9716, lng=77.5946)
HEBBAL = LatLng(lat=13.0298, lng=77.5709)


def test_haversine_known_distance():
    # Depot -> Hebbal is ~6.6 km great-circle; allow tolerance.
    d = haversine_km(DEPOT, HEBBAL)
    assert 5.5 < d < 7.5


def test_road_factor():
    assert math.isclose(road_km(DEPOT, HEBBAL), haversine_km(DEPOT, HEBBAL) * 1.3)


def test_zero_distance():
    assert haversine_km(DEPOT, DEPOT) == 0.0
    assert road_km(DEPOT, DEPOT) == 0.0


def test_travel_min():
    minutes = travel_min(DEPOT, HEBBAL, speed_kmh=30)
    assert minutes > 0
    assert travel_min(DEPOT, HEBBAL, speed_kmh=0) == math.inf


def test_fallback_offline_and_cache():
    # No OSRM configured -> pure offline haversine fallback.
    svc = DistanceService(osrm_url=None)
    d1 = svc.distance_km(DEPOT, HEBBAL)
    assert svc.last_source == "haversine"
    assert math.isclose(d1, road_km(DEPOT, HEBBAL))
    assert svc.cache_size() == 1
    # Second call is served from cache (same value).
    d2 = svc.distance_km(DEPOT, HEBBAL)
    assert d1 == d2
    assert svc.cache_size() == 1


def test_matrix_shape():
    svc = DistanceService(osrm_url=None)
    pts = [DEPOT, HEBBAL, LatLng(lat=12.93, lng=77.61)]
    m = svc.matrix(pts)
    assert len(m) == 3 and all(len(row) == 3 for row in m)
    assert m[0][0] == 0.0 and m[1][1] == 0.0
    assert m[0][1] > 0
