"""Initial route optimizer for DaakFlow (Phase 5).

Builds and solves a Google OR-Tools vehicle-routing model over the live
``WorldState`` and writes the resulting plan / order fields / metrics back
into it. This is the *initial* solve only: every vehicle departs from the
depot and there is no warm-start / locking / re-optimization (that is Phase 6).

Model summary (see §7 of the implementation plan):

* Nodes     depot (index 0) + one node per active order.
* Vehicles  the available fleet, all starting and ending at the depot.
* Arc cost  road distance in integer metres (minimise total travel distance).
* Capacity  two dimensions — weight and volume — with per-vehicle capacities.
* Time      per-vehicle transit callbacks (travel time depends on each
            vehicle's ``speed_kmh``), carrying ETAs; waiting (slack) allowed.
* Windows   each order node's time cumul is bounded to its delivery window.
* Hours     each vehicle starts at >= max(sim_time, shift_start) and must be
            back by shift_end.
* Priority  every order is a disjunction with a drop penalty scaled by
            priority, so low-value / over-constrained orders can drop.

Integer scaling — the classic OR-Tools gotcha, every callback must return an
``int``:

* distances -> integer metres, ``round(km * 1000)`` (``DIST_SCALE``).
* time & windows -> hundredths of a minute, ``round(minutes * 100)``
  (``TIME_SCALE``). Windows are scaled by the *same* factor, giving 0.6 s
  precision so window rounding can never spuriously break a tight window.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from .distances import distances
from .models import Metrics, OrderStatus, RouteStop, VehicleStatus
from .state import WorldState

# Integer-scaling factors (every OR-Tools callback must return an int).
DIST_SCALE = 1000  # km -> integer metres for arc cost.
TIME_SCALE = 100  # minutes -> hundredths of a minute (0.6 s precision).

# Search budget for the initial solve (§7 allows 2-5 s).
SOLVE_TIME_LIMIT_S = 2


@dataclass
class OptimizeResult:
    """Outcome of an :func:`optimize` call.

    ``status`` is one of:

    * ``"ok"``          solved; the plan/order fields/metrics were written.
    * ``"empty"``       no active orders — nothing to route (state cleared).
    * ``"infeasible"``  the solver found no assignment — prior state untouched.
    """

    status: str
    message: str = ""
    served: int = 0
    dropped: int = 0
    solve_ms: float = 0.0
    plan: dict[str, list[RouteStop]] = field(default_factory=dict)
    metrics: Optional[Metrics] = None


def _active_orders(world: WorldState) -> list:
    """Orders eligible for this solve: PENDING or ASSIGNED. COMPLETED /
    CANCELLED / DROPPED are excluded. (Statuses are plain strings on the
    in-memory models because ``ApiModel`` uses ``use_enum_values=True``.)"""
    active_values = {OrderStatus.PENDING.value, OrderStatus.ASSIGNED.value}
    return [o for o in world.orders if o.status in active_values]


def _usable_vehicles(world: WorldState) -> list:
    """Vehicles that may receive orders: an available driver and not BROKEN."""
    return [
        v
        for v in world.vehicles
        if v.driver_available and v.status != VehicleStatus.BROKEN.value
    ]


def _zero_metrics() -> Metrics:
    return Metrics(
        total_distance_km=0.0,
        total_time_min=0.0,
        late_deliveries=0,
        route_changes=0,
        utilization_pct=0.0,
        reopt_ms=0.0,
        dropped=0,
    )


def optimize(world: WorldState) -> OptimizeResult:
    """Build and solve the initial routing model over ``world`` and persist the
    plan, per-order assignment fields and metrics back into it.

    On an infeasible solve the world is left exactly as it was.
    """
    started = time.perf_counter()

    with world._lock:
        active = _active_orders(world)
        vehicles = _usable_vehicles(world)
        depot_pt = world.depot.location
        traffic = world.traffic_factor
        sim_time = world.sim_time
        order_pts = [o.location for o in active]

    # No active orders -> trivially solved with an empty plan.
    if not active:
        with world._lock:
            world.plan = {}
            world.metrics = _zero_metrics()
        return OptimizeResult(
            status="empty",
            message="no active orders to route",
            solve_ms=(time.perf_counter() - started) * 1000.0,
            metrics=_zero_metrics(),
        )

    if not vehicles:
        return OptimizeResult(
            status="infeasible",
            message="no available vehicles to serve active orders",
        )

    # -- geometry / matrices ------------------------------------------------ #
    points = [depot_pt] + order_pts
    dist_km = distances.matrix(points)
    n_nodes = len(points)
    dist_m = [
        [int(round(dist_km[i][j] * DIST_SCALE)) for j in range(n_nodes)]
        for i in range(n_nodes)
    ]
    depot_node = 0

    manager = pywrapcp.RoutingIndexManager(n_nodes, len(vehicles), depot_node)
    routing = pywrapcp.RoutingModel(manager)

    # -- arc cost: total travel distance (integer metres) ------------------- #
    def distance_cb(from_index: int, to_index: int) -> int:
        return dist_m[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

    dist_cb_idx = routing.RegisterTransitCallback(distance_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(dist_cb_idx)

    # -- capacity: two dimensions (weight + volume) ------------------------- #
    weight_demand = [0] + [int(round(o.weight)) for o in active]
    volume_demand = [0] + [int(o.volume) for o in active]

    def weight_cb(from_index: int) -> int:
        return weight_demand[manager.IndexToNode(from_index)]

    def volume_cb(from_index: int) -> int:
        return volume_demand[manager.IndexToNode(from_index)]

    w_cb_idx = routing.RegisterUnaryTransitCallback(weight_cb)
    routing.AddDimensionWithVehicleCapacity(
        w_cb_idx, 0, [int(v.capacity_weight) for v in vehicles], True, "Weight"
    )
    v_cb_idx = routing.RegisterUnaryTransitCallback(volume_cb)
    routing.AddDimensionWithVehicleCapacity(
        v_cb_idx, 0, [int(v.capacity_volume) for v in vehicles], True, "Volume"
    )

    # -- time: per-vehicle transit (travel time depends on speed) ----------- #
    # Derive time from the same distance matrix used for arc cost so ETAs and
    # distances stay consistent: minutes = km / speed * 60 * traffic_factor.
    def make_time_cb(speed_kmh: float):
        def time_cb(from_index: int, to_index: int) -> int:
            km = dist_km[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]
            minutes = (km / speed_kmh) * 60.0 * traffic if speed_kmh > 0 else 0.0
            return int(round(minutes * TIME_SCALE))

        return time_cb

    time_cb_indices = [
        routing.RegisterTransitCallback(make_time_cb(v.speed_kmh)) for v in vehicles
    ]
    horizon = int(round(max(v.shift_end for v in vehicles) * TIME_SCALE))
    routing.AddDimensionWithVehicleTransits(
        time_cb_indices, horizon, horizon, False, "Time"
    )
    time_dim = routing.GetDimensionOrDie("Time")

    # -- delivery windows on order nodes ------------------------------------ #
    for i, order in enumerate(active):
        index = manager.NodeToIndex(i + 1)
        time_dim.CumulVar(index).SetRange(
            int(round(order.window_start * TIME_SCALE)),
            int(round(order.window_end * TIME_SCALE)),
        )

    # -- working hours: start >= max(sim_time, shift_start); end <= shift_end #
    for vi, v in enumerate(vehicles):
        start_scaled = int(round(max(sim_time, v.shift_start) * TIME_SCALE))
        end_scaled = int(round(v.shift_end * TIME_SCALE))
        time_dim.CumulVar(routing.Start(vi)).SetRange(start_scaled, end_scaled)
        time_dim.CumulVar(routing.End(vi)).SetRange(start_scaled, end_scaled)
        routing.AddVariableMinimizedByFinalizer(time_dim.CumulVar(routing.Start(vi)))
        routing.AddVariableMinimizedByFinalizer(time_dim.CumulVar(routing.End(vi)))

    # -- priority disjunction: allow drops, penalty scaled by priority ------ #
    # Base penalty exceeds the total distance of serving every leg, so serving
    # an order always beats dropping it whenever a feasible slot exists; an
    # over-constrained order can still drop. priority 1..4 (4 = hardest to drop).
    drop_base = sum(sum(row) for row in dist_m) + 1
    for i, order in enumerate(active):
        index = manager.NodeToIndex(i + 1)
        routing.AddDisjunction([index], drop_base * max(1, int(order.priority)))

    # -- search parameters -------------------------------------------------- #
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.time_limit.FromSeconds(SOLVE_TIME_LIMIT_S)
    params.log_search = False

    solve_start = time.perf_counter()
    solution = routing.SolveWithParameters(params)
    solve_ms = (time.perf_counter() - solve_start) * 1000.0

    if solution is None:
        return OptimizeResult(
            status="infeasible",
            message="solver found no feasible plan; world state left unchanged",
            solve_ms=solve_ms,
        )

    # -- extract routes ----------------------------------------------------- #
    plan: dict[str, list[RouteStop]] = {}
    served_updates: list[tuple] = []  # (order, vehicle_id, seq, eta_min)
    total_distance_m = 0
    total_time_scaled = 0
    assigned_weight = 0.0

    for vi, v in enumerate(vehicles):
        index = routing.Start(vi)
        stops: list[RouteStop] = []
        seq = 0
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if node != depot_node:
                order = active[node - 1]
                eta_min = solution.Min(time_dim.CumulVar(index)) / TIME_SCALE
                stops.append(
                    RouteStop(order_id=order.id, seq=seq, eta=eta_min, locked=False)
                )
                served_updates.append((order, v.id, seq, eta_min))
                assigned_weight += order.weight
                seq += 1
            nxt = solution.Value(routing.NextVar(index))
            total_distance_m += routing.GetArcCostForVehicle(index, nxt, vi)
            index = nxt
        if stops:
            plan[v.id] = stops
            start_t = solution.Min(time_dim.CumulVar(routing.Start(vi)))
            end_t = solution.Min(time_dim.CumulVar(routing.End(vi)))
            total_time_scaled += end_t - start_t

    # -- metrics ------------------------------------------------------------ #
    served_ids = {upd[0].id for upd in served_updates}
    dropped_orders = [o for o in active if o.id not in served_ids]

    total_capacity = sum(v.capacity_weight for v in vehicles)
    utilization = (assigned_weight / total_capacity * 100.0) if total_capacity else 0.0

    metrics = Metrics(
        total_distance_km=round(total_distance_m / DIST_SCALE, 3),
        total_time_min=round(total_time_scaled / TIME_SCALE, 2),
        late_deliveries=0,  # initial solve: no prior plan to diff against
        route_changes=0,  # initial solve: nothing to compare against
        utilization_pct=round(utilization, 1),
        reopt_ms=round(solve_ms, 1),
        dropped=len(dropped_orders),
    )

    # -- persist under the world lock --------------------------------------- #
    with world._lock:
        world.plan = plan
        for order, vid, seq, eta_min in served_updates:
            order.status = OrderStatus.ASSIGNED.value
            order.assigned_vehicle = vid
            order.seq_index = seq
            order.eta = eta_min
        for order in dropped_orders:
            order.status = OrderStatus.DROPPED.value
            order.assigned_vehicle = None
            order.seq_index = None
            order.eta = None
        world.metrics = metrics

    return OptimizeResult(
        status="ok",
        message=(
            f"served {len(served_ids)}/{len(active)} orders "
            f"across {len(plan)} vehicle(s), {len(dropped_orders)} dropped"
        ),
        served=len(served_ids),
        dropped=len(dropped_orders),
        solve_ms=solve_ms,
        plan=plan,
        metrics=metrics,
    )


