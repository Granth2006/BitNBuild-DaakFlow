"""Model serialization: the API must emit the frontend's camelCase contract."""

from __future__ import annotations

from app.models import (
    LatLng,
    Metrics,
    Order,
    OrderStatus,
    RouteStop,
    Vehicle,
    VehicleStatus,
    VehicleType,
)

# Field sets copied from frontend/src/lib/types.ts (the authoritative contract).
ORDER_KEYS = {
    "id", "label", "location", "address", "windowStart", "windowEnd",
    "weight", "volume", "priority", "status", "assignedVehicle",
    "seqIndex", "eta", "createdAt",
}
VEHICLE_KEYS = {
    "id", "name", "type", "color", "location", "home", "capacityWeight",
    "capacityVolume", "speedKmh", "status", "driver", "driverAvailable",
    "shiftStart", "shiftEnd", "progress",
}
METRICS_KEYS = {
    "totalDistanceKm", "totalTimeMin", "lateDeliveries", "routeChanges",
    "utilizationPct", "reoptMs", "dropped",
}
ROUTESTOP_KEYS = {"orderId", "seq", "eta", "locked"}


def _order() -> Order:
    return Order(
        id="o1", label="A", location=LatLng(lat=13.0, lng=77.5), address="Hebbal",
        window_start=500, window_end=620, weight=80, volume=10, priority=2,
        status=OrderStatus.PENDING, assigned_vehicle=None, seq_index=None,
        eta=None, created_at=480,
    )


def _vehicle() -> Vehicle:
    return Vehicle(
        id="v1", name="Truck 01", type=VehicleType.TRUCK, color="#38bdf8",
        location=LatLng(lat=12.97, lng=77.59), home=LatLng(lat=12.97, lng=77.59),
        capacity_weight=600, capacity_volume=100, speed_kmh=34,
        status=VehicleStatus.ACTIVE, driver="Arjun", driver_available=True,
        shift_start=480, shift_end=1080, progress=0.0,
    )


def test_order_aliases():
    dumped = _order().model_dump(by_alias=True)
    assert set(dumped.keys()) == ORDER_KEYS
    assert dumped["windowStart"] == 500
    assert dumped["assignedVehicle"] is None
    assert dumped["status"] == "PENDING"
    assert dumped["location"] == {"lat": 13.0, "lng": 77.5}


def test_vehicle_aliases():
    dumped = _vehicle().model_dump(by_alias=True)
    assert set(dumped.keys()) == VEHICLE_KEYS
    assert dumped["capacityWeight"] == 600
    assert dumped["speedKmh"] == 34
    assert dumped["driverAvailable"] is True
    assert dumped["status"] == "ACTIVE"
    assert dumped["type"] == "TRUCK"


def test_metrics_and_routestop_aliases():
    metrics = Metrics(
        total_distance_km=1.0, total_time_min=2.0, late_deliveries=0,
        route_changes=0, utilization_pct=50.0, reopt_ms=5.0, dropped=0,
    )
    assert set(metrics.model_dump(by_alias=True).keys()) == METRICS_KEYS
    stop = RouteStop(order_id="o1", seq=0, eta=500.0, locked=False)
    assert set(stop.model_dump(by_alias=True).keys()) == ROUTESTOP_KEYS


def test_populate_by_name_roundtrip():
    # The API must also accept camelCase input (populate_by_name).
    v = Vehicle.model_validate(
        {
            "id": "v9", "name": "X", "type": "VAN", "color": "#fff",
            "location": {"lat": 1, "lng": 2}, "home": {"lat": 1, "lng": 2},
            "capacityWeight": 400, "capacityVolume": 90, "speedKmh": 42,
            "status": "ACTIVE", "driver": "Z", "driverAvailable": True,
            "shiftStart": 480, "shiftEnd": 1080, "progress": 0,
        }
    )
    assert v.capacity_weight == 400
    assert v.speed_kmh == 42
