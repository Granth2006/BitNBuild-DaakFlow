"""Tests for the data models (``app.models``).

Focus: the camelCase JSON contract the frontend consumes, enum-value handling,
the ``from`` alias, and the CRUD-payload defaults.
"""

from __future__ import annotations

from app.models import (
    ApiModel,
    Depot,
    EventPayload,
    EventRequest,
    LatLng,
    Metrics,
    Order,
    OrderCreate,
    OrderStatus,
    Reassignment,
    RouteStop,
    Vehicle,
    VehicleCreate,
    VehicleStatus,
    VehicleType,
    WorldEvent,
    WorldSnapshot,
    to_camel,
)


def test_to_camel_conversion():
    assert to_camel("total_distance_km") == "totalDistanceKm"
    assert to_camel("reopt_ms") == "reoptMs"
    assert to_camel("window_start") == "windowStart"
    assert to_camel("assigned_vehicle") == "assignedVehicle"
    assert to_camel("id") == "id"


def test_latlng_serializes_plainly():
    ll = LatLng(lat=12.9716, lng=77.5946)
    assert ll.model_dump() == {"lat": 12.9716, "lng": 77.5946}


def test_metrics_camelcase_aliases():
    m = Metrics(
        total_distance_km=10.5,
        total_time_min=42.0,
        late_deliveries=0,
        route_changes=3,
        utilization_pct=61.2,
        reopt_ms=1234.5,
        dropped=1,
    )
    dumped = m.model_dump(by_alias=True)
    assert set(dumped) == {
        "totalDistanceKm",
        "totalTimeMin",
        "lateDeliveries",
        "routeChanges",
        "utilizationPct",
        "reoptMs",
        "dropped",
    }
    assert dumped["totalDistanceKm"] == 10.5
    assert dumped["reoptMs"] == 1234.5


def test_order_uses_enum_values_not_enum_objects():
    order = Order(
        id="o1",
        label="A",
        location=LatLng(lat=1.0, lng=2.0),
        address="somewhere",
        window_start=500,
        window_end=600,
        weight=80.0,
        volume=10,
        priority=2,
        created_at=480,
    )
    # use_enum_values=True => the stored value is the plain string.
    assert order.status == "PENDING"
    assert order.status == OrderStatus.PENDING.value
    assert isinstance(order.status, str)


def test_order_camelcase_dump_keys():
    order = Order(
        id="o1",
        label="A",
        location=LatLng(lat=1.0, lng=2.0),
        address="x",
        window_start=500,
        window_end=600,
        weight=80.0,
        volume=10,
        priority=2,
        created_at=480,
    )
    dumped = order.model_dump(by_alias=True)
    for key in ("windowStart", "windowEnd", "assignedVehicle", "seqIndex", "createdAt"):
        assert key in dumped
    assert "window_start" not in dumped


def test_order_accepts_camelcase_and_snake_case_input():
    payload = {
        "id": "o1",
        "label": "A",
        "location": {"lat": 1.0, "lng": 2.0},
        "address": "x",
        "windowStart": 500,
        "windowEnd": 600,
        "weight": 80.0,
        "volume": 10,
        "priority": 2,
        "createdAt": 480,
    }
    from_camel = Order.model_validate(payload)
    assert from_camel.window_start == 500 and from_camel.created_at == 480
    # populate_by_name=True also allows the python field names on input.
    payload_snake = dict(payload)
    payload_snake["window_start"] = payload_snake.pop("windowStart")
    from_snake = Order.model_validate(payload_snake)
    assert from_snake.window_start == 500


def test_vehicle_type_and_status_are_strings():
    v = Vehicle(
        id="v1",
        name="Truck 01",
        type=VehicleType.TRUCK,
        color="#fff",
        location=LatLng(lat=1.0, lng=2.0),
        home=LatLng(lat=1.0, lng=2.0),
        capacity_weight=600,
        capacity_volume=100,
        speed_kmh=34,
        driver="Arjun",
        shift_start=480,
        shift_end=1080,
    )
    assert v.type == "TRUCK"
    assert v.status == VehicleStatus.ACTIVE.value
    assert isinstance(v.type, str)


def test_reassignment_from_alias():
    r = Reassignment(order_id="o1", label="A", from_="v1", to="v2")
    dumped = r.model_dump(by_alias=True)
    assert dumped["from"] == "v1"
    assert dumped["to"] == "v2"
    assert dumped["orderId"] == "o1"
    assert "from_" not in dumped
    # And it accepts the wire name "from" on the way in.
    r2 = Reassignment.model_validate({"orderId": "o2", "label": "B", "from": "v3"})
    assert r2.from_ == "v3"


def test_worldevent_defaults_and_aliases():
    e = WorldEvent(id="e1", type="TRAFFIC", description="surge", sim_time=500)
    assert e.affected_vehicles == []
    assert e.reassignments == []
    dumped = e.model_dump(by_alias=True)
    for key in ("simTime", "affectedVehicles", "affectedOrders", "reoptMs", "routeChanges"):
        assert key in dumped


def test_worldsnapshot_camelcase_keys():
    snap = WorldSnapshot(
        depot=Depot(id="depot", name="Hub", location=LatLng(lat=1.0, lng=2.0)),
        vehicles=[],
        orders=[],
        sim_time=480,
    )
    dumped = snap.model_dump(by_alias=True)
    assert dumped["simTime"] == 480
    assert dumped["trafficFactor"] == 1.0
    assert dumped["plan"] == {}
    assert dumped["metrics"] is None


def test_routestop_defaults():
    stop = RouteStop(order_id="o1", seq=0, eta=510.0)
    assert stop.locked is False
    assert stop.model_dump(by_alias=True)["orderId"] == "o1"


def test_event_request_default_payload():
    req = EventRequest(type="TRAFFIC")
    assert isinstance(req.payload, EventPayload)
    assert req.payload.factor_delta is None
    # Round-trips from a bare JSON body.
    req2 = EventRequest.model_validate({"type": "NEW_ORDER"})
    assert req2.type == "NEW_ORDER"


def test_vehicle_create_defaults():
    draft = VehicleCreate()
    assert draft.type == VehicleType.VAN.value
    assert draft.capacity_weight == 400
    assert draft.speed_kmh == 40


def test_order_create_requires_geometry_and_window():
    draft = OrderCreate(lat=12.9, lng=77.6, weight=50.0, window_start=500, window_end=600)
    assert draft.priority == 2  # default
    assert draft.label is None
