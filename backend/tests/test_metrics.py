"""Tests for the single-source-of-truth KPI scorer (``app.metrics``).

``compute_metrics`` scores a *live* plan (distances/ETAs read straight from the
solved stops); ``project_static`` replays the frozen 08:00 plan against the
current world for the Before/After comparison. Both are pure — no OR-Tools, no
``app.state`` — so they are exercised here with hand-built worlds plus the real
seed fixtures.
"""

from __future__ import annotations

from app.distances import road_km
from app.metrics import compute_metrics, project_static
from app.models import (
    Depot,
    LatLng,
    Order,
    OrderStatus,
    RouteStop,
    Vehicle,
    VehicleStatus,
    VehicleType,
)

DEPOT = Depot(id="depot", name="Depot", location=LatLng(lat=12.9716, lng=77.5946))


def _order(oid, lat, lng, *, weight=10.0, window=(480, 1080), priority=1,
           status=OrderStatus.ASSIGNED, eta=None):
    return Order(
        id=oid, label=oid, location=LatLng(lat=lat, lng=lng), address="x",
        window_start=window[0], window_end=window[1], weight=weight,
        volume=max(1, round(weight / 8)), priority=priority, status=status,
        assigned_vehicle=None, seq_index=None, eta=eta, created_at=480,
    )


def _vehicle(vid, lat, lng, *, cap=1000, status=VehicleStatus.ACTIVE,
             available=True, speed=30, home=None):
    hlat, hlng = home or (lat, lng)
    return Vehicle(
        id=vid, name=vid, type=VehicleType.VAN, color="#fff",
        location=LatLng(lat=lat, lng=lng), home=LatLng(lat=hlat, lng=hlng),
        capacity_weight=cap, capacity_volume=1000, speed_kmh=speed,
        status=status, driver="d", driver_available=available,
        shift_start=480, shift_end=1080, progress=0.0,
    )


# --------------------------------------------------------------------------- #
# compute_metrics (live plan)
# --------------------------------------------------------------------------- #
def test_compute_metrics_empty_plan_is_zeroed():
    # An active vehicle with no stops -> util 0 (no divide-by-zero), all else 0.
    m = compute_metrics({}, [_vehicle("v1", 12.9, 77.6)], [], DEPOT, 1.0)
    assert m.total_distance_km == 0.0
    assert m.total_time_min == 0.0
    assert m.late_deliveries == 0
    assert m.utilization_pct == 0.0
    assert m.route_changes == 0 and m.reopt_ms == 0.0 and m.dropped == 0


def test_compute_metrics_makespan_is_latest_eta_and_distance_from_live_pos():
    v = _vehicle("v1", 12.90, 77.60)
    o1 = _order("o1", 12.95, 77.62, eta=600.0)
    o2 = _order("o2", 12.98, 77.65, eta=650.0)
    plan = {"v1": [RouteStop(order_id="o1", seq=0, eta=600.0),
                   RouteStop(order_id="o2", seq=1, eta=650.0)]}
    m = compute_metrics(plan, [v], [o1, o2], DEPOT, 1.0)
    assert m.total_time_min == 650.0  # makespan == latest absolute-minute ETA
    expected = round(
        road_km(v.location, o1.location) + road_km(o1.location, o2.location), 3
    )
    assert m.total_distance_km == expected  # measured from the live position
    assert m.late_deliveries == 0


def test_compute_metrics_counts_late_deliveries():
    v = _vehicle("v1", 12.90, 77.60)
    o1 = _order("o1", 12.95, 77.62, window=(480, 600), eta=650.0)  # 50 min late
    plan = {"v1": [RouteStop(order_id="o1", seq=0, eta=650.0)]}
    m = compute_metrics(plan, [v], [o1], DEPOT, 1.0)
    assert m.late_deliveries == 1


def test_compute_metrics_utilization_over_active_available_fleet():
    v1 = _vehicle("v1", 12.9, 77.6, cap=100)
    v2 = _vehicle("v2", 12.9, 77.6, cap=100, available=False)  # driver off -> excluded
    v3 = _vehicle("v3", 12.9, 77.6, cap=100, status=VehicleStatus.BROKEN)  # excluded
    o1 = _order("o1", 12.95, 77.62, weight=50.0, eta=600.0)
    plan = {"v1": [RouteStop(order_id="o1", seq=0, eta=600.0)]}
    m = compute_metrics(plan, [v1, v2, v3], [o1], DEPOT, 1.0)
    assert m.utilization_pct == 50.0  # only v1 counts: 50/100


def test_compute_metrics_utilization_capped_at_100():
    v = _vehicle("v1", 12.9, 77.6, cap=10)
    o1 = _order("o1", 12.95, 77.62, weight=50.0, eta=600.0)  # 5x over capacity
    plan = {"v1": [RouteStop(order_id="o1", seq=0, eta=600.0)]}
    m = compute_metrics(plan, [v], [o1], DEPOT, 1.0)
    assert m.utilization_pct == 100.0


def test_compute_metrics_zero_capacity_with_load_is_full():
    v = _vehicle("v1", 12.9, 77.6, cap=0)
    o1 = _order("o1", 12.95, 77.62, weight=5.0, eta=600.0)
    plan = {"v1": [RouteStop(order_id="o1", seq=0, eta=600.0)]}
    m = compute_metrics(plan, [v], [o1], DEPOT, 1.0)
    assert m.utilization_pct == 100.0  # cap<=0 guard, load>0 -> 100%


def test_compute_metrics_passes_through_caller_fields():
    m = compute_metrics(
        {}, [_vehicle("v1", 12.9, 77.6)], [], DEPOT, 1.0,
        route_changes=3, reopt_ms=12.34, dropped=2,
    )
    assert m.route_changes == 3
    assert m.reopt_ms == 12.3  # rounded to 1 dp
    assert m.dropped == 2


# --------------------------------------------------------------------------- #
# project_static (frozen 08:00 plan replayed against the live world)
# --------------------------------------------------------------------------- #
def _first_loaded_vehicle(world):
    """A vehicle id whose frozen initial route carries at least one stop."""
    return next(vid for vid, stops in world.initial_plan.items() if stops)


def test_project_static_no_disruption_serves_all(optimized_world):
    w = optimized_world  # optimize() already captured the baseline
    w.capture_baseline_if_empty()  # idempotent no-op
    m = project_static(
        w.initial_plan, w.initial_vehicles, w.vehicles, w.orders, w.depot,
        w.traffic_factor,
    )
    assert m.dropped == 0  # the frozen plan covers every seed order
    assert m.total_distance_km > 0
    assert 480 <= m.total_time_min <= 1080  # makespan in absolute minutes
    assert 0 <= m.utilization_pct <= 100
    assert m.route_changes == 0 and m.reopt_ms == 0.0


def test_project_static_broken_vehicle_abandons_its_route(optimized_world):
    w = optimized_world
    vid = _first_loaded_vehicle(w)
    stranded = len(w.initial_plan[vid])
    w.get_vehicle(vid).status = VehicleStatus.BROKEN.value  # break it in the live fleet
    m = project_static(
        w.initial_plan, w.initial_vehicles, w.vehicles, w.orders, w.depot,
        w.traffic_factor,
    )
    assert m.dropped == stranded  # its stops go unserved in the static world


def test_project_static_completed_counts_served_even_if_vehicle_breaks(optimized_world):
    w = optimized_world
    vid = _first_loaded_vehicle(w)
    route = [s.order_id for s in w.initial_plan[vid]]
    done_id = route[0]
    w.get_order(done_id).status = OrderStatus.COMPLETED.value  # delivered before breakdown
    w.get_vehicle(vid).status = VehicleStatus.BROKEN.value
    m = project_static(
        w.initial_plan, w.initial_vehicles, w.vehicles, w.orders, w.depot,
        w.traffic_factor,
    )
    # The COMPLETED stop is not a miss; only the other stranded stops drop.
    assert m.dropped == len(route) - 1


def test_project_static_cancelled_excluded_from_dropped(optimized_world):
    w = optimized_world
    vid = _first_loaded_vehicle(w)
    cid = w.initial_plan[vid][0].order_id
    w.get_order(cid).status = OrderStatus.CANCELLED.value  # route still runs
    m = project_static(
        w.initial_plan, w.initial_vehicles, w.vehicles, w.orders, w.depot,
        w.traffic_factor,
    )
    assert m.dropped == 0  # a cancellation is not a deliverable miss


def test_project_static_new_order_after_0800_is_dropped(optimized_world):
    w = optimized_world
    # A brand-new order the frozen 08:00 plan never covers -> a static miss.
    w.orders.append(_order("o-new", 12.99, 77.66, status=OrderStatus.PENDING))
    m = project_static(
        w.initial_plan, w.initial_vehicles, w.vehicles, w.orders, w.depot,
        w.traffic_factor,
    )
    assert m.dropped == 1

