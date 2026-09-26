"""WorldState CRUD and seed behavior."""

from __future__ import annotations

from app.models import (
    OrderCreate,
    OrderStatus,
    OrderUpdate,
    VehicleCreate,
    VehicleType,
    VehicleUpdate,
)
from app.state import WorldState


def fresh() -> WorldState:
    w = WorldState()
    w.seed()
    return w


def test_seed_matches_mock_scenario():
    w = fresh()
    assert len(w.vehicles) == 4
    assert len(w.orders) == 15
    assert w.depot.id == "depot"
    v1 = w.get_vehicle("v1")
    assert v1.name == "Truck 01"
    assert v1.capacity_weight == 600
    assert v1.capacity_volume == 100  # seed base overrides type meta
    assert v1.speed_kmh == 34
    o1 = w.get_order("o1")
    assert o1.label == "A"
    assert o1.volume == round(80 / 8)
    assert o1.status == OrderStatus.PENDING.value
    assert o1.assigned_vehicle is None


def test_vehicle_crud_roundtrip():
    w = fresh()
    v = w.add_vehicle(VehicleCreate(name="Test", driver="Dev", type=VehicleType.BIKE,
                                    capacity_weight=60, speed_kmh=30))
    assert v.id == "v-usr-1"
    assert v.capacity_volume == 20  # BIKE meta
    assert w.get_vehicle("v-usr-1") is not None

    updated = w.update_vehicle("v-usr-1", VehicleUpdate(capacity_weight=75, type=VehicleType.VAN))
    assert updated.capacity_weight == 75
    assert updated.capacity_volume == 90  # VAN meta after type change

    assert w.delete_vehicle("v-usr-1") is True
    assert w.get_vehicle("v-usr-1") is None
    assert w.delete_vehicle("nope") is False


def test_delete_vehicle_frees_orders():
    w = fresh()
    order = w.get_order("o1")
    order.status = OrderStatus.ASSIGNED.value
    order.assigned_vehicle = "v1"
    order.seq_index = 0
    w.delete_vehicle("v1")
    freed = w.get_order("o1")
    assert freed.status == OrderStatus.PENDING.value
    assert freed.assigned_vehicle is None
    assert freed.seq_index is None


def test_order_crud_roundtrip():
    w = fresh()
    o = w.add_order(OrderCreate(address="Test Stop", lat=12.9, lng=77.6, weight=64,
                                priority=3, window_start=500, window_end=600))
    assert o.id == "o-usr-1"
    assert o.label == "U1"
    assert o.volume == max(1, round(64 / 8))
    assert o.status == OrderStatus.PENDING.value

    updated = w.update_order("o-usr-1", OrderUpdate(weight=80, address="Moved"))
    assert updated.weight == 80
    assert updated.volume == round(80 / 8)
    assert updated.address == "Moved"

    assert w.delete_order("o-usr-1") is True
    assert w.get_order("o-usr-1") is None
    assert w.delete_order("nope") is False


def test_snapshot_shape():
    w = fresh()
    snap = w.snapshot().model_dump(by_alias=True)
    assert set(snap.keys()) >= {"depot", "vehicles", "orders", "plan", "metrics",
                                "simTime", "trafficFactor", "events"}
    assert snap["simTime"] == 480
    assert snap["plan"] == {}
    assert snap["metrics"] is None
