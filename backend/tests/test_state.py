"""Tests for the in-memory ``WorldState`` (``app.state``)."""

from __future__ import annotations

from app.models import (
    OrderCreate,
    OrderStatus,
    OrderUpdate,
    VehicleCreate,
    VehicleStatus,
    VehicleType,
    VehicleUpdate,
)
from app.state import (
    DAY_END,
    DAY_START,
    WorldState,
    _max_seq,
    build_seed_orders,
    build_seed_vehicles,
)


def test_seed_populates_default_scenario(seeded_world):
    assert len(seeded_world.vehicles) == 4
    assert len(seeded_world.orders) == 15
    assert seeded_world.sim_time == DAY_START
    assert seeded_world.traffic_factor == 1.0
    assert seeded_world.plan == {}
    assert seeded_world.metrics is None
    assert seeded_world.events == []


def test_reset_is_seed(seeded_world):
    seeded_world.traffic_factor = 2.0
    seeded_world.orders = []
    seeded_world.reset()
    assert len(seeded_world.orders) == 15
    assert seeded_world.traffic_factor == 1.0


def test_seed_builders_shapes():
    vehicles = build_seed_vehicles()
    orders = build_seed_orders()
    assert [v.id for v in vehicles] == ["v1", "v2", "v3", "v4"]
    assert all(v.shift_start == DAY_START and v.shift_end == DAY_END for v in vehicles)
    assert all(v.capacity_volume == 100 for v in vehicles)
    assert orders[0].id == "o1" and orders[0].label == "A"
    # volume derived from weight / 8
    assert orders[0].volume == round(orders[0].weight / 8)
    assert all(o.status == OrderStatus.PENDING.value for o in orders)


def test_add_vehicle_defaults(fresh_world):
    veh = fresh_world.add_vehicle(VehicleCreate(name="", driver="", type=VehicleType.TRUCK))
    assert veh.id == "v-usr-1"
    assert veh.type == VehicleType.TRUCK.value
    assert veh.capacity_volume == 120  # from TRUCK type meta
    assert veh.driver == "Unassigned"
    assert veh.name.startswith("Truck")
    assert len(fresh_world.vehicles) == 1


def test_add_vehicle_custom_fields(fresh_world):
    veh = fresh_world.add_vehicle(
        VehicleCreate(name="Zippy", driver="Sam", type=VehicleType.BIKE, capacity_weight=50, speed_kmh=25)
    )
    assert veh.name == "Zippy" and veh.driver == "Sam"
    assert veh.capacity_weight == 50 and veh.speed_kmh == 25
    assert veh.capacity_volume == 20  # BIKE meta


def test_update_vehicle_changes_type_updates_volume(seeded_world):
    v1 = seeded_world.get_vehicle("v1")
    assert v1.type == VehicleType.TRUCK.value
    updated = seeded_world.update_vehicle("v1", VehicleUpdate(type=VehicleType.BIKE))
    assert updated.type == VehicleType.BIKE.value
    assert updated.capacity_volume == 20


def test_update_vehicle_status_and_missing(seeded_world):
    updated = seeded_world.update_vehicle("v2", VehicleUpdate(status=VehicleStatus.BROKEN, driver_available=False))
    assert updated.status == VehicleStatus.BROKEN.value
    assert updated.driver_available is False
    assert seeded_world.update_vehicle("nope", VehicleUpdate(name="x")) is None


def test_delete_vehicle_frees_unfinished_orders(seeded_world):
    order = seeded_world.orders[0]
    order.assigned_vehicle = "v1"
    order.status = OrderStatus.ASSIGNED.value
    order.seq_index = 0
    order.eta = 510.0
    assert seeded_world.delete_vehicle("v1") is True
    assert order.status == OrderStatus.PENDING.value
    assert order.assigned_vehicle is None
    assert order.seq_index is None
    assert seeded_world.delete_vehicle("v1") is False  # already gone


def test_delete_vehicle_keeps_completed_orders(seeded_world):
    order = seeded_world.orders[0]
    order.assigned_vehicle = "v1"
    order.status = OrderStatus.COMPLETED.value
    seeded_world.delete_vehicle("v1")
    assert order.status == OrderStatus.COMPLETED.value


def test_add_order_derives_volume_and_id(fresh_world):
    order = fresh_world.add_order(
        OrderCreate(lat=12.9, lng=77.6, weight=80.0, window_start=500, window_end=600)
    )
    assert order.id == "o-usr-1"
    assert order.volume == max(1, round(80.0 / 8))
    assert order.status == OrderStatus.PENDING.value
    assert order.created_at == fresh_world.sim_time


def test_add_order_volume_floor(fresh_world):
    order = fresh_world.add_order(
        OrderCreate(lat=12.9, lng=77.6, weight=1.0, window_start=500, window_end=600)
    )
    assert order.volume == 1  # max(1, round(1/8)) == 1


def test_update_order_weight_updates_volume_and_missing(seeded_world):
    oid = seeded_world.orders[0].id
    updated = seeded_world.update_order(oid, OrderUpdate(weight=160.0, priority=4))
    assert updated.weight == 160.0
    assert updated.volume == max(1, round(160.0 / 8))
    assert updated.priority == 4
    assert seeded_world.update_order("nope", OrderUpdate(weight=1.0)) is None


def test_update_order_location_and_status(seeded_world):
    oid = seeded_world.orders[0].id
    updated = seeded_world.update_order(
        oid, OrderUpdate(lat=13.1, lng=77.7, status=OrderStatus.CANCELLED)
    )
    assert updated.location.lat == 13.1 and updated.location.lng == 77.7
    assert updated.status == OrderStatus.CANCELLED.value


def test_delete_order(seeded_world):
    oid = seeded_world.orders[0].id
    assert seeded_world.delete_order(oid) is True
    assert seeded_world.get_order(oid) is None
    assert seeded_world.delete_order(oid) is False


def test_list_and_get_helpers(seeded_world):
    assert len(seeded_world.list_vehicles()) == 4
    assert len(seeded_world.list_orders()) == 15
    assert seeded_world.get_vehicle("v3").name == "Van 03"
    assert seeded_world.get_order("o1").label == "A"
    assert seeded_world.get_vehicle("missing") is None


def test_snapshot_returns_detached_copies(seeded_world):
    snap = seeded_world.snapshot()
    assert len(snap.vehicles) == 4 and len(snap.orders) == 15
    # mutating the snapshot's list must not change the world's list
    snap.vehicles.clear()
    assert len(seeded_world.vehicles) == 4


def test_set_vehicle_position(seeded_world):
    veh = seeded_world.set_vehicle_position("v1", 13.05, 77.60, progress=0.5)
    assert veh.location.lat == 13.05 and veh.location.lng == 77.60
    assert veh.progress == 0.5
    assert seeded_world.set_vehicle_position("missing", 1.0, 2.0) is None


def test_load_catalog_resets_live_fields(seeded_world):
    vehicles = build_seed_vehicles()
    orders = build_seed_orders()
    depot = seeded_world.depot
    target = WorldState()
    target.sim_time = 999
    target.traffic_factor = 2.4
    target.load_catalog(depot, vehicles, orders)
    assert len(target.vehicles) == 4 and len(target.orders) == 15
    assert target.sim_time == DAY_START
    assert target.traffic_factor == 1.0
    assert target.plan == {} and target.events == []


def test_max_seq_helper():
    assert _max_seq(["v1", "v-usr-3", "v-usr-7", "o2"]) == 7
    assert _max_seq(["v1", "v2"]) == 0
    assert _max_seq([]) == 0
