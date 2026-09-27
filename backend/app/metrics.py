"""Single source of truth for the six KPIs (Phase 8).

Both the *live adaptive* plan and the *static "no re-optimization"* projection
are scored here, by the same code, so the Before/After panel compares
like-for-like. This module is pure: it imports only the domain models and the
offline-capable distance helpers — never OR-Tools and never ``app.state`` (so it
can be imported from anywhere without a circular import).

KPI definitions (identical shape to :class:`app.models.Metrics`):

* ``total_distance_km``  Σ road_km between consecutive points per vehicle,
  starting from the vehicle's live ``location``. Rounded to 3 dp.
* ``total_time_min``     the plan **makespan** — the latest stop ETA across the
  whole plan, in absolute minutes-from-midnight (0.0 for an empty plan). Rounded
  to 2 dp. This replaces the old per-vehicle Σ(end-start) *duration*, so the live
  plan and the static projection are finally on the same clock.
* ``late_deliveries``    served stops whose ETA slips past the order window end.
* ``route_changes``      caller-supplied churn count (not recomputed here).
* ``utilization_pct``    mean of ``min(1, load / capacity_weight)`` over the
  ACTIVE, driver-available fleet, ×100. Rounded to 1 dp; 0 with no such vehicle.
* ``reopt_ms``           caller-supplied solve time. Rounded to 1 dp.
* ``dropped``            caller-supplied count of unserved deliverable orders.
"""

from __future__ import annotations

from .distances import road_km, travel_min
from .models import (
    Depot,
    Metrics,
    Order,
    OrderStatus,
    RouteStop,
    Vehicle,
    VehicleStatus,
)

# Mirror of frontend/src/lib/optimizer.ts.
SERVICE_MIN = 5  # minutes spent servicing each delivery
LATE_SLACK = 0  # grace minutes before a stop counts as late


def _utilization_pct(
    plan: dict[str, list[RouteStop]],
    vehicles: list[Vehicle],
    order_by_id: dict[str, Order],
) -> float:
    """Mean per-vehicle load ratio (capped at 1) over the ACTIVE, available fleet.

    Matches ``computeMetrics`` in optimizer.ts: an active vehicle with no stops
    contributes 0, and the denominator is the count of active vehicles (not just
    those carrying work). Returns 0.0 when no vehicle is active/available.
    """
    active = [
        v
        for v in vehicles
        if v.status == VehicleStatus.ACTIVE.value and v.driver_available
    ]
    if not active:
        return 0.0
    total = 0.0
    for v in active:
        load = sum(
            order_by_id[s.order_id].weight
            for s in plan.get(v.id, [])
            if s.order_id in order_by_id
        )
        if v.capacity_weight > 0:
            total += min(1.0, load / v.capacity_weight)
        elif load > 0:
            total += 1.0
    return round(total / len(active) * 100.0, 1)


def compute_metrics(
    plan: dict[str, list[RouteStop]],
    vehicles: list[Vehicle],
    orders: list[Order],
    depot: Depot,
    traffic: float,
    *,
    route_changes: int = 0,
    reopt_ms: float = 0.0,
    dropped: int = 0,
) -> Metrics:
    """Score a *live* plan. Distances/ETAs come straight from the solved plan
    (each stop already carries the solver's absolute-minute ETA), so this never
    re-solves and never needs OR-Tools.

    ``depot`` and ``traffic`` are accepted for signature symmetry with
    :func:`project_static`; the live KPIs are read from the plan itself and do
    not use them.
    """
    order_by_id = {o.id: o for o in orders}
    vehicle_by_id = {v.id: v for v in vehicles}

    dist = 0.0
    late = 0
    makespan = 0.0
    for vid, stops in plan.items():
        v = vehicle_by_id.get(vid)
        if v is None:
            continue
        cur = v.location
        for s in sorted(stops, key=lambda st: st.seq):
            o = order_by_id.get(s.order_id)
            if o is None:
                continue
            dist += road_km(cur, o.location)
            cur = o.location
            if s.eta is not None:
                if s.eta > o.window_end + 1e-6:
                    late += 1
                if s.eta > makespan:
                    makespan = s.eta

    return Metrics(
        total_distance_km=round(dist, 3),
        total_time_min=round(makespan, 2),
        late_deliveries=late,
        route_changes=route_changes,
        utilization_pct=_utilization_pct(plan, vehicles, order_by_id),
        reopt_ms=round(reopt_ms, 1),
        dropped=dropped,
    )


def project_static(
    initial_plan: dict[str, list[RouteStop]],
    initial_vehicles: list[Vehicle],
    current_vehicles: list[Vehicle],
    orders: list[Order],
    depot: Depot,
    traffic: float,
) -> Metrics:
    """Score the day as it *would* have gone WITHOUT dynamic re-optimization: the
    initial 08:00 plan is executed exactly as committed against the world as it
    now stands. Faithful port of ``projectStatic`` in
    ``frontend/src/lib/optimizer.ts`` — except ``total_time_min`` is the makespan
    (latest arrival) in absolute minutes, matching :func:`compute_metrics`.

    Rules:

    * distances start at each initial vehicle's ``home`` (the 08:00 depot start),
      the clock starts at ``shift_start``, service is 5 min/stop, and a vehicle
      waits idle when it beats an order's ``window_start``;
    * a vehicle BROKEN now (or removed from ``current_vehicles``) abandons its
      remaining route;
    * COMPLETED orders count as served (a later breakdown never un-delivers a
      completed stop); CANCELLED orders are excluded from both sides;
    * ``dropped`` = deliverable orders (not CANCELLED / COMPLETED) the frozen plan
      never covers — orders that arrived after 08:00, or stops stranded on a
      broken/removed vehicle.

    ``depot`` is accepted for signature symmetry with :func:`compute_metrics`;
    the static projection starts each route from the vehicle's ``home``.
    """
    order_by_id = {o.id: o for o in orders}
    vehicle_by_id = {v.id: v for v in initial_vehicles}
    usable = {
        v.id for v in current_vehicles if v.status != VehicleStatus.BROKEN.value
    }

    dist = 0.0
    late = 0
    makespan = 0.0
    util_sum = 0.0
    util_count = 0
    served: set[str] = set()

    # Orders physically delivered in reality are served in the static world too:
    # seed them first so a completed order on a since-broken vehicle isn't
    # miscounted as unserved.
    for o in orders:
        if o.status == OrderStatus.COMPLETED.value:
            served.add(o.id)

    for vid, stops in initial_plan.items():
        v = vehicle_by_id.get(vid)
        if v is None or vid not in usable:
            continue  # broken or removed -> remaining route abandoned
        cur = v.home
        t = float(v.shift_start)
        load = 0.0
        for s in sorted(stops, key=lambda st: st.seq):
            o = order_by_id.get(s.order_id)
            if o is None or o.status == OrderStatus.CANCELLED.value:
                continue  # gone from the world
            dist += road_km(cur, o.location)
            t += travel_min(cur, o.location, v.speed_kmh, traffic)
            if t < o.window_start:
                t = float(o.window_start)  # wait for the window to open
            if t - o.window_end > LATE_SLACK:
                late += 1
            if t > makespan:
                makespan = t
            t += SERVICE_MIN
            cur = o.location
            load += o.weight
            served.add(o.id)
        if v.capacity_weight > 0:
            util_sum += min(1.0, load / v.capacity_weight)
        elif load > 0:
            util_sum += 1.0
        util_count += 1

    dropped = 0
    for o in orders:
        if o.status in (OrderStatus.CANCELLED.value, OrderStatus.COMPLETED.value):
            continue
        if o.id not in served:
            dropped += 1

    return Metrics(
        total_distance_km=round(dist, 3),
        total_time_min=round(makespan, 2),
        late_deliveries=late,
        route_changes=0,
        utilization_pct=round(util_sum / util_count * 100.0, 1) if util_count else 0.0,
        reopt_ms=0.0,
        dropped=dropped,
    )
