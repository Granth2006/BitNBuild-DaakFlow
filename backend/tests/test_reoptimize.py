"""Tests for the dynamic re-optimization engine (``app.reoptimize``)."""

from __future__ import annotations

from app.models import OrderStatus, VehicleStatus
from app.reoptimize import _prior_positions, _servable_orders, reoptimize


def _vehicle_with_stops(world, minimum=2):
    """Return (vehicle_id, sorted stops) for a vehicle carrying >= ``minimum``."""
    for vid, stops in world.plan.items():
        if len(stops) >= minimum:
            return vid, sorted(stops, key=lambda s: s.seq)
    raise AssertionError("no vehicle in the plan has enough stops")


def test_reoptimize_empty_world_is_empty(fresh_world):
    result = reoptimize(fresh_world)
    assert result.status == "empty"
    assert fresh_world.plan == {}


def test_reoptimize_cold_serves_all_without_prior_plan(seeded_world):
    # No prior optimize => no warm routes => cold fallback solve.
    result = reoptimize(seeded_world)
    assert result.status == "ok"
    assert result.served == 15
    assert result.used_fallback is True
    assert result.warm_started is False


def test_reoptimize_warm_starts_from_prior_plan(optimized_world):
    result = reoptimize(optimized_world)
    assert result.status == "ok"
    assert result.warm_started is True
    assert result.used_fallback is False


def test_reoptimize_reopt_ms_under_budget(optimized_world):
    result = reoptimize(optimized_world)
    assert result.metrics.reopt_ms < 5000
    assert result.solve_ms < 5000


def test_reoptimize_no_disruption_keeps_plan_stable(optimized_world):
    # A re-solve with nothing changed should not churn the routes.
    result = reoptimize(optimized_world)
    assert result.route_changes == 0
    assert result.reassignments == []


def test_reoptimize_freezes_completed_orders(optimized_world):
    vid, stops = _vehicle_with_stops(optimized_world)
    done_id = stops[0].order_id
    done = optimized_world.get_order(done_id)
    done.status = OrderStatus.COMPLETED.value

    result = reoptimize(optimized_world)
    assert result.status == "ok"
    # A COMPLETED order is frozen: never re-added to the model or the plan.
    assert done.status == OrderStatus.COMPLETED.value
    planned_ids = {s.order_id for route in optimized_world.plan.values() for s in route}
    assert done_id not in planned_ids
    assert done_id not in {o.id for o in _servable_orders(optimized_world)}


def test_reoptimize_pins_in_progress_first_and_locked(optimized_world):
    vid, stops = _vehicle_with_stops(optimized_world)
    prog_id = stops[1].order_id if len(stops) > 1 else stops[0].order_id
    prog = optimized_world.get_order(prog_id)
    prog.status = OrderStatus.IN_PROGRESS.value
    assert prog.assigned_vehicle == vid

    result = reoptimize(optimized_world)
    assert result.status == "ok"
    # The committed leg stays IN_PROGRESS, on the same vehicle, visited first.
    assert prog.status == OrderStatus.IN_PROGRESS.value
    assert prog.assigned_vehicle == vid
    first_stop = sorted(optimized_world.plan[vid], key=lambda s: s.seq)[0]
    assert first_stop.order_id == prog_id
    assert first_stop.locked is True


def test_reoptimize_freeze_and_pin_together(optimized_world):
    vid, stops = _vehicle_with_stops(optimized_world, minimum=2)
    done_id, prog_id = stops[0].order_id, stops[1].order_id
    optimized_world.get_order(done_id).status = OrderStatus.COMPLETED.value
    optimized_world.get_order(prog_id).status = OrderStatus.IN_PROGRESS.value

    result = reoptimize(optimized_world)
    assert result.status == "ok"
    assert result.metrics.reopt_ms < 5000
    planned_ids = {s.order_id for route in optimized_world.plan.values() for s in route}
    assert done_id not in planned_ids  # frozen
    first_stop = sorted(optimized_world.plan[vid], key=lambda s: s.seq)[0]
    assert first_stop.order_id == prog_id and first_stop.locked  # pinned first


def test_reoptimize_reassigns_orders_off_a_broken_vehicle(optimized_world):
    vid, stops = _vehicle_with_stops(optimized_world)
    stranded = [s.order_id for s in stops]
    broken = optimized_world.get_vehicle(vid)
    broken.status = VehicleStatus.BROKEN.value
    broken.driver_available = False

    result = reoptimize(optimized_world)
    assert result.status == "ok"
    # The broken vehicle can no longer appear in the new plan.
    assert vid not in optimized_world.plan
    # Its previously-assigned orders moved elsewhere (or dropped) -> reassignments.
    assert result.route_changes > 0
    moved_ids = {r.order_id for r in result.reassignments}
    assert moved_ids & set(stranded)  # stranded orders were re-routed
    # at least one reassignment leaves the broken vehicle
    assert any(r.from_ == vid for r in result.reassignments)
    # every reassignment is a genuine vehicle move with the wire alias shape
    for r in result.reassignments:
        assert r.from_ != r.to
        dumped = r.model_dump(by_alias=True)
        assert "from" in dumped and "to" in dumped


def test_reoptimize_drops_when_capacity_insufficient(seeded_world):
    only = seeded_world.get_vehicle("v3")
    only.capacity_weight = 100
    seeded_world.vehicles = [only]
    result = reoptimize(seeded_world)
    assert result.status == "ok"
    assert result.dropped > 0
    assert result.metrics.dropped == result.dropped


def test_reoptimize_infeasible_when_no_usable_vehicles(seeded_world):
    for v in seeded_world.vehicles:
        v.driver_available = False
    result = reoptimize(seeded_world)
    assert result.status == "infeasible"


def test_prior_positions_uses_relative_sequence(optimized_world):
    vid, stops = _vehicle_with_stops(optimized_world, minimum=2)
    # Freeze the first stop: the second stop should become relative index 0.
    done_id = stops[0].order_id
    optimized_world.get_order(done_id).status = OrderStatus.COMPLETED.value
    servable_ids = {o.id for o in _servable_orders(optimized_world)}
    prior_vehicle, prior_seq = _prior_positions(optimized_world, servable_ids)
    second_id = stops[1].order_id
    assert done_id not in prior_seq  # frozen out
    assert prior_vehicle[second_id] == vid
    assert prior_seq[second_id] == 0  # no longer looks re-routed
