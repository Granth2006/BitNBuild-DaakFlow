"""Tests for the distance service (``app.distances``).

The suite runs offline: OSRM is never really contacted. The OSRM code path is
exercised only through a monkeypatched ``httpx.get``.
"""

from __future__ import annotations

import math

import httpx
import pytest

from app.distances import (
    EARTH_R_KM,
    ROAD_FACTOR,
    DistanceService,
    haversine_km,
    road_km,
    travel_min,
)
from app.models import LatLng

DEPOT = LatLng(lat=12.9716, lng=77.5946)
HEBBAL = LatLng(lat=13.0298, lng=77.5709)


def test_haversine_zero_for_same_point():
    assert haversine_km(DEPOT, DEPOT) == pytest.approx(0.0, abs=1e-9)


def test_haversine_is_symmetric_and_positive():
    d1 = haversine_km(DEPOT, HEBBAL)
    d2 = haversine_km(HEBBAL, DEPOT)
    assert d1 == pytest.approx(d2)
    assert d1 > 0


def test_haversine_known_distance():
    # Depot -> Hebbal is roughly 6.8 km great-circle.
    assert haversine_km(DEPOT, HEBBAL) == pytest.approx(6.8, abs=0.4)


def test_haversine_one_degree_latitude():
    # One degree of latitude ~= 111.19 km on this earth radius.
    a = LatLng(lat=0.0, lng=0.0)
    b = LatLng(lat=1.0, lng=0.0)
    expected = 2 * EARTH_R_KM * math.asin(math.sin(math.radians(0.5)))
    assert haversine_km(a, b) == pytest.approx(expected)


def test_road_km_applies_road_factor():
    assert road_km(DEPOT, HEBBAL) == pytest.approx(haversine_km(DEPOT, HEBBAL) * ROAD_FACTOR)
    assert ROAD_FACTOR == 1.3


def test_travel_min_formula():
    km = road_km(DEPOT, HEBBAL)
    assert travel_min(DEPOT, HEBBAL, speed_kmh=30.0) == pytest.approx(km / 30.0 * 60.0)


def test_travel_min_scales_with_traffic():
    base = travel_min(DEPOT, HEBBAL, speed_kmh=30.0, traffic_factor=1.0)
    heavy = travel_min(DEPOT, HEBBAL, speed_kmh=30.0, traffic_factor=2.0)
    assert heavy == pytest.approx(base * 2.0)


def test_travel_min_zero_speed_is_infinite():
    assert travel_min(DEPOT, HEBBAL, speed_kmh=0.0) == math.inf


def test_service_defaults_to_haversine_offline():
    svc = DistanceService(osrm_url=None)
    d = svc.distance_km(DEPOT, HEBBAL)
    assert svc.last_source == "haversine"
    assert d == pytest.approx(road_km(DEPOT, HEBBAL))


def test_service_caches_results():
    svc = DistanceService(osrm_url=None)
    assert svc.cache_size() == 0
    first = svc.distance_km(DEPOT, HEBBAL)
    assert svc.cache_size() == 1
    second = svc.distance_km(DEPOT, HEBBAL)
    assert first == second
    assert svc.cache_size() == 1  # served from cache, not recomputed


def test_matrix_shape_and_diagonal():
    svc = DistanceService(osrm_url=None)
    pts = [DEPOT, HEBBAL, LatLng(lat=12.95, lng=77.62)]
    m = svc.matrix(pts)
    assert len(m) == 3 and all(len(row) == 3 for row in m)
    for i in range(3):
        assert m[i][i] == 0.0
    assert m[0][1] == pytest.approx(m[1][0])  # symmetric


def test_service_uses_osrm_when_configured(monkeypatch):
    class FakeResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"routes": [{"distance": 5000.0}]}  # metres

    calls = {}

    def fake_get(url, params=None, timeout=None):
        calls["url"] = url
        return FakeResp()

    monkeypatch.setattr("app.distances.httpx.get", fake_get)
    svc = DistanceService(osrm_url="http://osrm.example")
    d = svc.distance_km(DEPOT, HEBBAL)
    assert d == pytest.approx(5.0)  # 5000 m / 1000
    assert svc.last_source == "osrm"
    assert calls["url"].startswith("http://osrm.example/route/v1/driving/")


def test_service_falls_back_when_osrm_fails(monkeypatch):
    def boom(*args, **kwargs):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr("app.distances.httpx.get", boom)
    svc = DistanceService(osrm_url="http://osrm.example")
    d = svc.distance_km(DEPOT, HEBBAL)
    assert svc.last_source == "haversine"
    assert d == pytest.approx(road_km(DEPOT, HEBBAL))


def test_service_falls_back_on_empty_routes(monkeypatch):
    class EmptyResp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"routes": []}

    monkeypatch.setattr("app.distances.httpx.get", lambda *a, **k: EmptyResp())
    svc = DistanceService(osrm_url="http://osrm.example")
    d = svc.distance_km(DEPOT, HEBBAL)
    assert svc.last_source == "haversine"
    assert d == pytest.approx(road_km(DEPOT, HEBBAL))
