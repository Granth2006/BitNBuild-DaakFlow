"""Disruption event handlers for DaakFlow (Phase 6).

Each handler mirrors one disruption the frontend's event console can fire (see
``fireEvent`` in ``frontend/src/store/useWorldStore.ts`` and the ``EventType``
union in ``frontend/src/lib/types.ts``). A handler is the whole write path for a
disruption:

    capture pre-state  ->  mutate the world  ->  reoptimize(world)  ->
    build a WorldEvent (real reopt_ms / route_changes / reassignments /
    affected lists + a human description)  ->  append it to world.events  ->
    return it.

The seven event-type strings match the frontend union *exactly*:
``NEW_ORDER``, ``PRIORITY_ORDER``, ``BREAKDOWN``, ``TRAFFIC``,
``CANCELLATION``, ``TIME_CHANGE``, ``ADDRESS_CHANGE``. Reassignment
``from``/``to`` semantics match too: ``from`` is the previous vehicle id
(``None`` = was unassigned/dropped), ``to`` the new one (``None`` = dropped).

No broadcasting / Socket.IO here (that is Phase 7): a handler only mutates the
live :class:`~app.state.WorldState` and returns the event it appended.
"""

from __future__ import annotations

from typing import Optional

from .models import (
    EventPayload,
    OrderCreate,
    OrderStatus,
    VehicleStatus,
    WorldEvent,
)
from .reoptimize import ReoptResult, reoptimize
from .state import DAY_START, WorldState

# The seven disruption strings, matching the frontend EventType union exactly.
EVENT_TYPES: frozenset[str] = frozenset(
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

# Deterministic defaults for a synthesised order when the payload omits fields
# (a disruption from the demo console carries no explicit order body). A central
# metro point keeps a default drop reachable within the sim day.
_DEFAULT_ORDER_LAT = 12.9750
_DEFAULT_ORDER_LNG = 77.6550
_DEFAULT_ORDER_WEIGHT = 80.0

# Where ADDRESS_CHANGE relocates an order when no lat/lng is supplied (far east,
# so the move is a genuine re-route rather than a no-op).
_RELOCATE_LAT = 12.9600
_RELOCATE_LNG = 77.7200

# TRAFFIC: raise the congestion factor by this step, capped — mirrors the
# frontend's ``min(2.4, +(trafficFactor + 0.6))``.
_TRAFFIC_STEP = 0.6
_TRAFFIC_CAP = 2.4

# --------------------------------------------------------------------------- #
# Shared helpers
# --------------------------------------------------------------------------- #
def _dedup(*groups: list[str]) -> list[str]:
    """Order-preserving union of id groups (cause markers first)."""
    seen: set[str] = set()
    out: list[str] = []
    for group in groups:
        for item in group:
            if item and item not in seen:
                seen.add(item)
                out.append(item)
    return out


def _reopt_ms(result: ReoptResult) -> float:
    if result.metrics is not None:
        return result.metrics.reopt_ms
    return round(result.solve_ms, 1)


def _resolve_order(world: WorldState, order_id: Optional[str], eligible: set[str]):
    """The explicit target if given, else the first order in an eligible state."""
    if order_id is not None:
        return next((o for o in world.orders if o.id == order_id), None)
    return next((o for o in world.orders if o.status in eligible), None)


def _pick_breakdown_target(world: WorldState):
    """The active, available vehicle with the most remaining (unfinished) stops —
    the disruption bites hardest there (mirrors the frontend heuristic)."""
    active = [
        v
        for v in world.vehicles
        if v.status == VehicleStatus.ACTIVE.value and v.driver_available
    ]
    if not active:
        return None
    done = {o.id for o in world.orders if o.status == OrderStatus.COMPLETED.value}
    best = active[0]
    best_remaining = -1
    for v in active:
        remaining = len(
            [s for s in world.plan.get(v.id, []) if s.order_id not in done]
        )
        if remaining > best_remaining:
            best_remaining = remaining
            best = v
    return best


def _finish(
    world: WorldState,
    *,
    event_type: str,
    description: str,
    result: ReoptResult,
    cause_vehicles: list[str],
    cause_orders: list[str],
) -> WorldEvent:
    """Assemble the WorldEvent from a disruption's cause + the re-opt diff,
    append it to the world's event log and return it. The affected lists are the
    union of what the disruption directly touched and what the re-optimization
    then moved."""
    note = "" if result.status == "ok" else f" ({result.message})"
    evt = WorldEvent(
        id=f"e{len(world.events) + 1}",
        type=event_type,
        description=description + note,
        sim_time=world.sim_time,
        affected_vehicles=_dedup(cause_vehicles, result.affected_vehicles),
        affected_orders=_dedup(cause_orders, result.affected_orders),
        reopt_ms=_reopt_ms(result),
        route_changes=result.route_changes,
        reassignments=result.reassignments,
    )
    with world._lock:
        world.events.append(evt)
    return evt


# --------------------------------------------------------------------------- #
# Handlers (one per §6 event type)
# --------------------------------------------------------------------------- #
def _add_order(
    world: WorldState, payload: EventPayload, *, priority: bool
) -> WorldEvent:
    """NEW_ORDER / PRIORITY_ORDER — a fresh drop enters the system mid-day, then
    the tail is re-optimized to slot (or drop) it."""
    span = 60 if priority else 180  # priority orders carry a tight window
    default_start = max(world.sim_time, DAY_START) + 10
    ws = payload.window_start if payload.window_start is not None else default_start
    we = payload.window_end if payload.window_end is not None else ws + span
    draft = OrderCreate(
        address=payload.address or ("Priority drop" if priority else "New drop"),
        lat=payload.lat if payload.lat is not None else _DEFAULT_ORDER_LAT,
        lng=payload.lng if payload.lng is not None else _DEFAULT_ORDER_LNG,
        weight=payload.weight if payload.weight is not None else _DEFAULT_ORDER_WEIGHT,
        priority=payload.priority
        if payload.priority is not None
        else (4 if priority else 2),
        window_start=ws,
        window_end=we,
        label=payload.label,
    )
    order = world.add_order(draft)
    result = reoptimize(world)
    kind = "Priority order" if priority else "New order"
    return _finish(
        world,
        event_type="PRIORITY_ORDER" if priority else "NEW_ORDER",
        description=f"{kind} {order.label} arrived at {order.address}",
        result=result,
        cause_vehicles=[],
        cause_orders=[order.id],
    )


def _breakdown(world: WorldState, payload: EventPayload) -> WorldEvent:
    """BREAKDOWN — a vehicle fails: mark it BROKEN + unavailable and release its
    unfinished orders (COMPLETED legs stay done) back into the pending pool, then
    re-optimize so the survivors absorb the freed orders."""
    with world._lock:
        if payload.vehicle_id is not None:
            target = next(
                (v for v in world.vehicles if v.id == payload.vehicle_id), None
            )
        else:
            target = _pick_breakdown_target(world)
        released: list[str] = []
        if target is not None:
            target.status = VehicleStatus.BROKEN.value
            target.driver_available = False
            for o in world.orders:
                if (
                    o.assigned_vehicle == target.id
                    and o.status != OrderStatus.COMPLETED.value
                ):
                    o.status = OrderStatus.PENDING.value
                    o.assigned_vehicle = None
                    o.seq_index = None
                    o.eta = None
                    released.append(o.id)
        cause_vehicles = [target.id] if target is not None else []
        name = target.name if target is not None else None
    result = reoptimize(world)
    if name is None:
        desc = "Breakdown fired, but no active vehicle was available to disable"
    else:
        desc = f"{name} broke down; {len(released)} order(s) released for re-routing"
    return _finish(
        world,
        event_type="BREAKDOWN",
        description=desc,
        result=result,
        cause_vehicles=cause_vehicles,
        cause_orders=released,
    )


def _traffic(world: WorldState, payload: EventPayload) -> WorldEvent:
    """TRAFFIC — congestion rises: bump the traffic factor (capped) so every
    vehicle's travel time inflates, then re-optimize under the slower network."""
    step = payload.factor_delta if payload.factor_delta is not None else _TRAFFIC_STEP
    with world._lock:
        world.traffic_factor = min(_TRAFFIC_CAP, round(world.traffic_factor + step, 2))
        new_factor = world.traffic_factor
        cause_vehicles = [
            v.id for v in world.vehicles if v.status == VehicleStatus.ACTIVE.value
        ]
    result = reoptimize(world)
    return _finish(
        world,
        event_type="TRAFFIC",
        description=f"Traffic surge — congestion factor now {new_factor}x",
        result=result,
        cause_vehicles=cause_vehicles,
        cause_orders=[],
    )


def _cancellation(world: WorldState, payload: EventPayload) -> WorldEvent:
    """CANCELLATION — a customer cancels: mark the order CANCELLED and drop it
    from the plan, then re-optimize to reclaim the freed slot/capacity."""
    with world._lock:
        target = _resolve_order(
            world,
            payload.order_id,
            {OrderStatus.ASSIGNED.value, OrderStatus.PENDING.value},
        )
        label: Optional[str] = None
        cause_orders: list[str] = []
        if target is not None and target.status not in (
            OrderStatus.COMPLETED.value,
            OrderStatus.CANCELLED.value,
        ):
            target.status = OrderStatus.CANCELLED.value
            target.assigned_vehicle = None
            target.seq_index = None
            target.eta = None
            label = target.label
            cause_orders = [target.id]
    result = reoptimize(world)
    desc = (
        f"Order {label} cancelled"
        if label is not None
        else "Cancellation fired, but no eligible order was found"
    )
    return _finish(
        world,
        event_type="CANCELLATION",
        description=desc,
        result=result,
        cause_vehicles=[],
        cause_orders=cause_orders,
    )


def _time_change(world: WorldState, payload: EventPayload) -> WorldEvent:
    """TIME_CHANGE — a delivery window tightens: narrow the order's window (an
    explicit window if supplied, else the frontend's shrink), then re-optimize so
    the plan honours the tighter constraint (or drops the order)."""
    with world._lock:
        target = _resolve_order(
            world,
            payload.order_id,
            {
                OrderStatus.ASSIGNED.value,
                OrderStatus.PENDING.value,
                OrderStatus.IN_PROGRESS.value,
            },
        )
        label: Optional[str] = None
        window = ""
        cause_orders: list[str] = []
        if target is not None:
            if payload.window_start is not None or payload.window_end is not None:
                if payload.window_end is not None:
                    target.window_end = payload.window_end
                if payload.window_start is not None:
                    target.window_start = payload.window_start
            else:
                # mirror the frontend tightening
                we = max(world.sim_time + 40, target.window_end - 90)
                target.window_end = we
                target.window_start = min(target.window_start, we - 30)
            label = target.label
            window = f"{target.window_start}-{target.window_end}"
            cause_orders = [target.id]
    result = reoptimize(world)
    desc = (
        f"Delivery window for {label} tightened to {window}"
        if label is not None
        else "Time change fired, but no eligible order was found"
    )
    return _finish(
        world,
        event_type="TIME_CHANGE",
        description=desc,
        result=result,
        cause_vehicles=[],
        cause_orders=cause_orders,
    )


def _address_change(world: WorldState, payload: EventPayload) -> WorldEvent:
    """ADDRESS_CHANGE — a customer relocates: move the order's location (an
    explicit lat/lng if supplied, else a deterministic relocation), then
    re-optimize around the new geometry."""
    with world._lock:
        target = _resolve_order(
            world,
            payload.order_id,
            {OrderStatus.ASSIGNED.value, OrderStatus.PENDING.value},
        )
        label: Optional[str] = None
        cause_orders: list[str] = []
        if target is not None:
            target.location.lat = payload.lat if payload.lat is not None else _RELOCATE_LAT
            target.location.lng = payload.lng if payload.lng is not None else _RELOCATE_LNG
            target.address = payload.address or "Relocated stop"
            label = target.label
            cause_orders = [target.id]
    result = reoptimize(world)
    desc = (
        f"Delivery address for {label} changed"
        if label is not None
        else "Address change fired, but no eligible order was found"
    )
    return _finish(
        world,
        event_type="ADDRESS_CHANGE",
        description=desc,
        result=result,
        cause_vehicles=[],
        cause_orders=cause_orders,
    )


# --------------------------------------------------------------------------- #
# Dispatch
# --------------------------------------------------------------------------- #
def apply_event(
    world: WorldState, event_type: str, payload: Optional[EventPayload] = None
) -> WorldEvent:
    """Apply a disruption by type string and return the resulting WorldEvent.

    Raises :class:`ValueError` for an unknown ``event_type`` (the route maps it
    to a 400). The disruption is always recorded, even if the subsequent
    re-optimization is infeasible (the event then carries the solver's note).
    """
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event type: {event_type!r}")
    payload = payload or EventPayload()
    if event_type == "NEW_ORDER":
        return _add_order(world, payload, priority=False)
    if event_type == "PRIORITY_ORDER":
        return _add_order(world, payload, priority=True)
    if event_type == "BREAKDOWN":
        return _breakdown(world, payload)
    if event_type == "TRAFFIC":
        return _traffic(world, payload)
    if event_type == "CANCELLATION":
        return _cancellation(world, payload)
    if event_type == "TIME_CHANGE":
        return _time_change(world, payload)
    # ADDRESS_CHANGE (the only remaining member of EVENT_TYPES)
    return _address_change(world, payload)
