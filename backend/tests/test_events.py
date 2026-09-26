"""Tests for the disruption event handlers (``app.events``).

Each handler mutates the world, re-optimizes the tail and returns a recorded
``WorldEvent``. Every event type in the frontend union is exercised.
"""

from __future__ import annotations

import pytest

from app.events import EVENT_TYPES, apply_event
from app.models import EventPayload, OrderStatus, VehicleStatus


def test_event_types_are_the_seven_frontend_strings():
    assert EVENT_TYPES == frozenset(
        {
            "NEW_ORDER",
            "PRIORITY_ORDER",
            "BREAKDOWN",
            "TRAFFIC",
            "CANCELLATION",
            "TIME_CHANGE",
            "ADDRESS_CHANGE",
        }
    )


def test_unknown_event_type_raises(seeded_world):
    with pytest.raises(ValueError):
        apply_event(seeded_world, "METEOR_STRIKE", EventPayload())


def test_new_order_adds_and_records_event(seeded_world):
    before = len(seeded_world.orders)
    evt = apply_event(seeded_world, "NEW_ORDER", EventPayload())
    assert evt.type == "NEW_ORDER"
    assert len(seeded_world.orders) == before + 1
    new = seeded_world.orders[-1]
    assert new.priority == 2  # NEW_ORDER default
    assert new.id in evt.affected_orders
    # the event was appended to the world log
    assert seeded_world.events[-1] is evt
    assert evt.id == "e1"


def test_priority_order_uses_high_priority(seeded_world):
    before = len(seeded_world.orders)
    evt = apply_event(seeded_world, "PRIORITY_ORDER", EventPayload())
    assert evt.type == "PRIORITY_ORDER"
    assert len(seeded_world.orders) == before + 1
    new = seeded_world.orders[-1]
    assert new.priority == 4  # PRIORITY_ORDER default
    # priority orders carry a tighter window than plain new orders (span 60)
    assert new.window_end - new.window_start == 60


def test_new_order_honours_explicit_payload(seeded_world):
    payload = EventPayload(
        lat=13.05, lng=77.62, weight=42.0, priority=3, window_start=520, window_end=640, label="XX"
    )
    evt = apply_event(seeded_world, "NEW_ORDER", payload)
    new = seeded_world.orders[-1]
    assert new.location.lat == 13.05 and new.location.lng == 77.62
    assert new.weight == 42.0 and new.priority == 3
    assert new.window_start == 520 and new.window_end == 640
    assert new.label == "XX"
    assert evt.type == "NEW_ORDER"


def test_breakdown_disables_a_vehicle(optimized_world):
    evt = apply_event(optimized_world, "BREAKDOWN", EventPayload())
    assert evt.type == "BREAKDOWN"
    broken = [v for v in optimized_world.vehicles if v.status == VehicleStatus.BROKEN.value]
    assert len(broken) == 1
    assert broken[0].driver_available is False
    assert broken[0].id in evt.affected_vehicles


def test_breakdown_targets_named_vehicle(optimized_world):
    evt = apply_event(optimized_world, "BREAKDOWN", EventPayload(vehicle_id="v2"))
    v2 = optimized_world.get_vehicle("v2")
    assert v2.status == VehicleStatus.BROKEN.value
    assert "v2" in evt.affected_vehicles
    assert evt.type == "BREAKDOWN"


def test_traffic_raises_congestion_factor(seeded_world):
    assert seeded_world.traffic_factor == 1.0
    evt = apply_event(seeded_world, "TRAFFIC", EventPayload())
    assert evt.type == "TRAFFIC"
    assert seeded_world.traffic_factor == 1.6  # +0.6 default step
    # active vehicles are flagged as the cause
    assert set(evt.affected_vehicles) == {"v1", "v2", "v3", "v4"}


def test_traffic_is_capped(seeded_world):
    apply_event(seeded_world, "TRAFFIC", EventPayload(factor_delta=5.0))
    assert seeded_world.traffic_factor == 2.4  # capped at _TRAFFIC_CAP


def test_cancellation_marks_order_cancelled(seeded_world):
    evt = apply_event(seeded_world, "CANCELLATION", EventPayload(order_id="o1"))
    assert evt.type == "CANCELLATION"
    o1 = seeded_world.get_order("o1")
    assert o1.status == OrderStatus.CANCELLED.value
    assert o1.assigned_vehicle is None
    assert "o1" in evt.affected_orders


def test_cancellation_defaults_to_first_eligible(seeded_world):
    evt = apply_event(seeded_world, "CANCELLATION", EventPayload())
    cancelled = [o for o in seeded_world.orders if o.status == OrderStatus.CANCELLED.value]
    assert len(cancelled) == 1
    assert cancelled[0].id in evt.affected_orders


def test_time_change_tightens_window(seeded_world):
    o1 = seeded_world.get_order("o1")
    evt = apply_event(
        seeded_world, "TIME_CHANGE", EventPayload(order_id="o1", window_start=500, window_end=540)
    )
    assert evt.type == "TIME_CHANGE"
    assert o1.window_start == 500 and o1.window_end == 540
    assert "o1" in evt.affected_orders


def test_time_change_default_shrink(seeded_world):
    o1 = seeded_world.get_order("o1")
    before_end = o1.window_end
    apply_event(seeded_world, "TIME_CHANGE", EventPayload(order_id="o1"))
    assert o1.window_end <= before_end  # window narrowed (or clamped near sim_time)


def test_address_change_relocates_order(seeded_world):
    o1 = seeded_world.get_order("o1")
    before = (o1.location.lat, o1.location.lng)
    evt = apply_event(
        seeded_world, "ADDRESS_CHANGE", EventPayload(order_id="o1", lat=12.96, lng=77.72, address="Elsewhere")
    )
    assert evt.type == "ADDRESS_CHANGE"
    assert (o1.location.lat, o1.location.lng) == (12.96, 77.72)
    assert (o1.location.lat, o1.location.lng) != before
    assert o1.address == "Elsewhere"


def test_address_change_default_relocation(seeded_world):
    o1 = seeded_world.get_order("o1")
    apply_event(seeded_world, "ADDRESS_CHANGE", EventPayload(order_id="o1"))
    # default relocation moves it east to the deterministic relocate point
    assert o1.location.lat == 12.96 and o1.location.lng == 77.72
    assert o1.address == "Relocated stop"


def test_event_log_accumulates_with_incrementing_ids(seeded_world):
    e1 = apply_event(seeded_world, "TRAFFIC", EventPayload())
    e2 = apply_event(seeded_world, "CANCELLATION", EventPayload())
    assert [e1.id, e2.id] == ["e1", "e2"]
    assert len(seeded_world.events) == 2


def test_event_carries_reopt_diff_fields(seeded_world):
    evt = apply_event(seeded_world, "TRAFFIC", EventPayload())
    # WorldEvent exposes the real re-opt metrics (camelCase over the wire).
    assert evt.reopt_ms >= 0
    assert isinstance(evt.route_changes, int)
    dumped = evt.model_dump(by_alias=True)
    for key in ("reoptMs", "routeChanges", "affectedVehicles", "affectedOrders", "reassignments"):
        assert key in dumped
