"""Tests for the initial OR-Tools optimizer (``app.optimizer``)."""

from __future__ import annotations

from app.models import OrderStatus, VehicleStatus
from app.optimizer import _active_orders, _usable_vehicles, optimize


def test_optimize_seed_serves_all_fifteen(seeded_world):
    result = optimize(seeded_world)
    assert result.status == "ok"
    assert result.served == 15
    assert result.dropped == 0
    assert seeded_world.metrics.dropped == 0


def test_optimize_assigns_orders_and_writes_plan(seeded_world):
    optimize(seeded_world)
    assigned = [o for o in seeded_world.orders if o.status == OrderStatus.ASSIGNED.value]
    assert len(assigned) == 15
    for o in assigned:
        assert o.assigned_vehicle is not None
        assert o.seq_index is not None
        assert o.eta is not None
    # Every order in the plan maps back to a real order id.
    all_order_ids = {o.id for o in seeded_world.orders}
    planned_ids = {s.order_id for stops in seeded_world.plan.values() for s in stops}
    assert planned_ids <= all_order_ids
    assert len(planned_ids) == 15


def test_optimize_plan_sequences_are_contiguous(seeded_world):
    optimize(seeded_world)
    for stops in seeded_world.plan.values():
        seqs = sorted(s.seq for s in stops)
        assert seqs == list(range(len(stops)))


def test_optimize_metrics_are_populated(seeded_world):
    result = optimize(seeded_world)
    m = result.metrics
    assert m.total_distance_km > 0
    assert m.total_time_min > 0
    assert 0 <= m.utilization_pct <= 100
    assert m.reopt_ms >= 0
    assert m.route_changes == 0  # initial solve has nothing to diff against


def test_optimize_empty_world_is_empty_status(fresh_world):
    result = optimize(fresh_world)
    assert result.status == "empty"
    assert fresh_world.plan == {}
    assert fresh_world.metrics.dropped == 0


def test_optimize_no_usable_vehicles_is_infeasible(seeded_world):
    for v in seeded_world.vehicles:
        v.status = VehicleStatus.BROKEN.value
        v.driver_available = False
    result = optimize(seeded_world)
    assert result.status == "infeasible"


def test_optimize_infeasible_leaves_world_untouched(seeded_world):
    for v in seeded_world.vehicles:
        v.driver_available = False
    before = [o.status for o in seeded_world.orders]
    result = optimize(seeded_world)
    assert result.status == "infeasible"
    after = [o.status for o in seeded_world.orders]
    assert before == after  # nothing reassigned or dropped


def test_optimize_capacity_forces_drops(seeded_world):
    # Keep a single, tiny-capacity van; most heavy orders can no longer fit.
    only = seeded_world.get_vehicle("v3")
    only.capacity_weight = 100
    seeded_world.vehicles = [only]
    result = optimize(seeded_world)
    assert result.status == "ok"
    assert result.dropped > 0
    assert result.served + result.dropped == 15
    dropped = [o for o in seeded_world.orders if o.status == OrderStatus.DROPPED.value]
    assert len(dropped) == result.dropped


def test_optimize_respects_time_windows(seeded_world):
    optimize(seeded_world)
    # Every served order's ETA must fall inside its delivery window (hard windows).
    for o in seeded_world.orders:
        if o.status == OrderStatus.ASSIGNED.value:
            assert o.window_start <= o.eta <= o.window_end + 1e-6


def test_active_and_usable_helpers(seeded_world):
    assert len(_active_orders(seeded_world)) == 15
    assert len(_usable_vehicles(seeded_world)) == 4
    seeded_world.orders[0].status = OrderStatus.COMPLETED.value
    seeded_world.vehicles[0].status = VehicleStatus.BROKEN.value
    assert len(_active_orders(seeded_world)) == 14
    assert len(_usable_vehicles(seeded_world)) == 3
