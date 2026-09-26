"""Dynamic re-optimization engine for DaakFlow (Phase 6).

The heart of the project: on every disruption we do **not** re-solve the whole
VRP from scratch. Instead we *freeze the past, respect commitment, move the
start, re-solve only the tail, warm-start from the current plan, and allow
drops* — so the plan barely moves and the solve is fast (see §1 / §7 of the
implementation plan). The six mechanics, and where each lives below:

1. Freeze the past     COMPLETED orders are never added to the model.
2. Respect commitment  an IN_PROGRESS order is pinned as its vehicle's mandatory
                       first visit and can never be dropped.
3. Move the start      each usable vehicle re-enters at its live position via a
                       per-vehicle start node (not the depot).
4. Re-solve the tail   only PENDING / ASSIGNED / IN_PROGRESS orders form the pool.
5. Warm-start          the previous routes (minus completed) seed the solver via
                       ``ReadAssignmentFromRoutes``; a short time-boxed GUIDED
                       LOCAL SEARCH improves from there. Falls back to a cold
                       PATH_CHEAPEST_ARC solve if the warm assignment does not
                       map cleanly (no prior plan, or a pin conflict).
6. Allow drops         priority-scaled disjunctions let over-constrained
                       situations drop low-priority orders instead of failing.

The model differs from the Phase 5 cold solve (:mod:`app.optimizer`) only in the
node layout (per-vehicle live-position starts + a single shared depot end node)
and the locking / warm-start; the integer scaling, capacity/time dimensions,
delivery windows, working hours and disjunctions are identical, so ETAs stay
consistent between the initial solve and every re-optimization.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Optional

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from .distances import distances
from .models import Metrics, OrderStatus, Reassignment, RouteStop, VehicleStatus
from .optimizer import DIST_SCALE, TIME_SCALE
from .state import WorldState

# §7 allows 2-5 s; the warm-start converges fast, so a 2 s box keeps a single
# re-opt (and even the rare cold fallback) comfortably under the 5 s budget.
REOPT_TIME_LIMIT_S = 2

# Orders eligible for (re)assignment. COMPLETED is frozen out of the model;
# CANCELLED / DROPPED are gone. (Statuses are plain strings because ApiModel
# uses ``use_enum_values=True`` — compare against ``OrderStatus.X.value``.)
_SERVABLE = {
    OrderStatus.PENDING.value,
    OrderStatus.ASSIGNED.value,
    OrderStatus.IN_PROGRESS.value,
}

@dataclass
class ReoptResult:
    """Outcome of a :func:`reoptimize` call.

    ``status`` mirrors :class:`app.optimizer.OptimizeResult`:

    * ``"ok"``          re-solved; plan / order fields / metrics were written.
    * ``"empty"``       nothing servable — the plan was cleared.
    * ``"infeasible"``  no assignment found — the world is left untouched.
    """

    status: str
    message: str = ""
    served: int = 0
    dropped: int = 0
    solve_ms: float = 0.0
    plan: dict[str, list[RouteStop]] = field(default_factory=dict)
    metrics: Optional[Metrics] = None
    # -- diff against the previous plan ------------------------------------- #
    route_changes: int = 0
    reassignments: list[Reassignment] = field(default_factory=list)
    affected_vehicles: list[str] = field(default_factory=list)
    affected_orders: list[str] = field(default_factory=list)
    # -- provenance (handy for tests / reporting) --------------------------- #
    warm_started: bool = False
    used_fallback: bool = False


def _servable_orders(world: WorldState) -> list:
    """Orders in the free/committed pool: PENDING, ASSIGNED or IN_PROGRESS."""
    return [o for o in world.orders if o.status in _SERVABLE]


def _usable_vehicles(world: WorldState) -> list:
    """Vehicles that may carry orders: an available driver and not BROKEN."""
    return [
        v
        for v in world.vehicles
        if v.driver_available and v.status != VehicleStatus.BROKEN.value
    ]


def _zero_metrics(reopt_ms: float = 0.0) -> Metrics:
    return Metrics(
        total_distance_km=0.0,
        total_time_min=0.0,
        late_deliveries=0,
        route_changes=0,
        utilization_pct=0.0,
        reopt_ms=round(reopt_ms, 1),
        dropped=0,
    )


def _prior_positions(
    world: WorldState, servable_ids: set[str]
) -> tuple[dict[str, str], dict[str, int]]:
    """Capture each order's prior vehicle and its *relative* sequence among the
    orders that survive into this solve.

    Sequence is measured relative to surviving orders so that removing the
    frozen COMPLETED prefix does not, by itself, look like a re-route: an
    IN_PROGRESS stop that sat 3rd behind two COMPLETED stops is relative-index 0
    both before and after — correctly reported as *unchanged*.
    """
    prior_vehicle: dict[str, str] = {}
    prior_seq: dict[str, int] = {}
    for vid, stops in world.plan.items():
        surviving = [
            s for s in sorted(stops, key=lambda st: st.seq) if s.order_id in servable_ids
        ]
        for rel, stop in enumerate(surviving):
            prior_vehicle[stop.order_id] = vid
            prior_seq[stop.order_id] = rel
    return prior_vehicle, prior_seq


def reoptimize(world: WorldState) -> ReoptResult:
    """Warm-started, commitment-respecting re-solve of the *tail* of the plan.

    Persists the new plan / per-order assignment fields / metrics into ``world``
    under its lock, and returns a diff (route changes + reassignments) against
    the previous plan. On an infeasible solve the world is left untouched.
    """
    started = time.perf_counter()

    with world._lock:
        servable = _servable_orders(world)
        vehicles = _usable_vehicles(world)
        depot_pt = world.depot.location
        traffic = world.traffic_factor
        sim_time = world.sim_time
        # Snapshot geometry + commitment + prior plan while holding the lock.
        veh_pts = [v.location for v in vehicles]
        order_pts = [o.location for o in servable]
        veh_index = {v.id: i for i, v in enumerate(vehicles)}
        servable_ids = {o.id for o in servable}
        prior_vehicle, prior_seq = _prior_positions(world, servable_ids)
        prior_plan = {vid: list(stops) for vid, stops in world.plan.items()}
        # IN_PROGRESS orders whose vehicle is still usable -> pin them; an
        # IN_PROGRESS order on a now-unusable vehicle degrades to a free order.
        in_progress: dict[str, str] = {
            o.id: o.assigned_vehicle
            for o in servable
            if o.status == OrderStatus.IN_PROGRESS.value
            and o.assigned_vehicle in veh_index
        }

    # Nothing servable -> trivially solved with an empty plan.
    if not servable:
        elapsed = (time.perf_counter() - started) * 1000.0
        with world._lock:
            world.plan = {}
            world.metrics = _zero_metrics(elapsed)
        return ReoptResult(
            status="empty",
            message="no servable orders to route",
            solve_ms=elapsed,
            metrics=_zero_metrics(elapsed),
        )

    if not vehicles:
        return ReoptResult(
            status="infeasible",
            message="no usable vehicles to serve the servable pool",
        )

    # -- node layout -------------------------------------------------------- #
    # [0 .. V-1]      per-vehicle live-position start nodes
    # [V .. V+O-1]    one node per servable order
    # [V+O]           single shared depot end node (open-ended return)
    V = len(vehicles)
    O = len(servable)
    points = veh_pts + order_pts + [depot_pt]
    depot_end = V + O
    n_nodes = len(points)  # == V + O + 1

    dist_km = distances.matrix(points)
    dist_m = [
        [int(round(dist_km[i][j] * DIST_SCALE)) for j in range(n_nodes)]
        for i in range(n_nodes)
    ]

    starts = list(range(V))
    ends = [depot_end] * V  # all vehicles finish at the one depot end node
    manager = pywrapcp.RoutingIndexManager(n_nodes, V, starts, ends)
    routing = pywrapcp.RoutingModel(manager)

    def order_node(j: int) -> int:
        return V + j

    # -- arc cost: total travel distance (integer metres) ------------------- #
    def distance_cb(from_index: int, to_index: int) -> int:
        return dist_m[manager.IndexToNode(from_index)][manager.IndexToNode(to_index)]

    dist_cb_idx = routing.RegisterTransitCallback(distance_cb)
    routing.SetArcCostEvaluatorOfAllVehicles(dist_cb_idx)

    # -- capacity: two dimensions (weight + volume); starts/end carry none --- #
    weight_demand = [0] * n_nodes
    volume_demand = [0] * n_nodes
    for j, o in enumerate(servable):
        weight_demand[order_node(j)] = int(round(o.weight))
        volume_demand[order_node(j)] = int(o.volume)

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

    # -- time: per-vehicle transit (travel time depends on speed x traffic) -- #
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
    for j, o in enumerate(servable):
        idx = manager.NodeToIndex(order_node(j))
        time_dim.CumulVar(idx).SetRange(
            int(round(o.window_start * TIME_SCALE)),
            int(round(o.window_end * TIME_SCALE)),
        )

    # -- working hours: start >= max(sim_time, shift_start); end <= shift_end #
    # The re-opt happens "now": each vehicle's start cumul is bounded below by
    # the current sim_time, so ETAs run forward from the present.
    for vi, v in enumerate(vehicles):
        lo = int(round(max(sim_time, v.shift_start) * TIME_SCALE))
        hi = int(round(v.shift_end * TIME_SCALE))
        time_dim.CumulVar(routing.Start(vi)).SetRange(lo, hi)
        time_dim.CumulVar(routing.End(vi)).SetRange(lo, hi)
        routing.AddVariableMinimizedByFinalizer(time_dim.CumulVar(routing.Start(vi)))
        routing.AddVariableMinimizedByFinalizer(time_dim.CumulVar(routing.End(vi)))

    # -- disjunctions (drops) + IN_PROGRESS pinning ------------------------- #
    # Base penalty exceeds the whole distance matrix, so serving always beats
    # dropping when a feasible slot exists; priority 1..4 scales it (4 hardest
    # to drop). An IN_PROGRESS order is pinned instead: locked to its vehicle
    # (VehicleVar) and forced first (NextVar of that vehicle's Start), with NO
    # disjunction so it is mandatory and can never be dropped.
    #
    # (VehicleVar.SetValue is used rather than SetAllowedVehiclesForIndex, whose
    # absl::Span<int> binding is broken in the ortools 9.15 Python wheel.)
    drop_base = sum(sum(row) for row in dist_m) + 1
    pinned_first: set[int] = set()
    for j, o in enumerate(servable):
        idx = manager.NodeToIndex(order_node(j))
        vid = in_progress.get(o.id)
        if vid is not None:
            vi = veh_index[vid]
            routing.VehicleVar(idx).SetValue(vi)  # lock to its vehicle
            if vi not in pinned_first:
                # mandatory *first* visit for that vehicle
                routing.solver().Add(routing.NextVar(routing.Start(vi)) == idx)
                pinned_first.add(vi)
        else:
            routing.AddDisjunction([idx], drop_base * max(1, int(o.priority)))

    # -- search parameters -------------------------------------------------- #
    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    )
    params.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    params.time_limit.FromSeconds(REOPT_TIME_LIMIT_S)
    params.log_search = False

    # -- warm-start routes: previous plan minus frozen/gone orders ---------- #
    # Each vehicle's route is [pinned IN_PROGRESS (if any), then its surviving
    # prior stops in order]. Node indices (not internal indices), start/end
    # excluded — exactly what ReadAssignmentFromRoutes expects.
    id_to_node = {o.id: order_node(j) for j, o in enumerate(servable)}
    warm_routes: list[list[int]] = []
    for v in vehicles:
        pinned = [oid for oid, wv in in_progress.items() if wv == v.id]
        route_nodes = [id_to_node[oid] for oid in pinned]
        for stop in sorted(prior_plan.get(v.id, []), key=lambda s: s.seq):
            if stop.order_id in id_to_node and stop.order_id not in pinned:
                route_nodes.append(id_to_node[stop.order_id])
        warm_routes.append(route_nodes)

    routing.CloseModelWithParameters(params)

    # -- solve: warm-start first, cold fallback if it doesn't map ----------- #
    solve_start = time.perf_counter()
    solution = None
    warm_started = False
    if any(warm_routes):
        initial = routing.ReadAssignmentFromRoutes(warm_routes, True)
        if initial is not None:
            solution = routing.SolveFromAssignmentWithParameters(initial, params)
            warm_started = solution is not None
    used_fallback = False
    if solution is None:
        # No prior plan, or the warm assignment did not map cleanly (e.g. a pin
        # conflict). Cold solve from PATH_CHEAPEST_ARC, same constraints.
        solution = routing.SolveWithParameters(params)
        used_fallback = True
    solve_ms = (time.perf_counter() - solve_start) * 1000.0

    if solution is None:
        return ReoptResult(
            status="infeasible",
            message="solver found no feasible plan; world state left unchanged",
            solve_ms=solve_ms,
            warm_started=warm_started,
            used_fallback=used_fallback,
        )

    # -- extract routes ----------------------------------------------------- #
    plan: dict[str, list[RouteStop]] = {}
    served_updates: list[tuple] = []  # (order, vehicle_id, seq, eta_min)
    new_vehicle: dict[str, str] = {}
    new_seq: dict[str, int] = {}
    total_distance_m = 0
    total_time_scaled = 0
    assigned_weight = 0.0

    for vi, v in enumerate(vehicles):
        index = routing.Start(vi)
        stops: list[RouteStop] = []
        seq = 0
        while not routing.IsEnd(index):
            node = manager.IndexToNode(index)
            if V <= node < V + O:  # an order node (skip starts and depot end)
                o = servable[node - V]
                eta_min = solution.Min(time_dim.CumulVar(index)) / TIME_SCALE
                stops.append(
                    RouteStop(
                        order_id=o.id,
                        seq=seq,
                        eta=eta_min,
                        locked=o.id in in_progress,  # the pinned commitment
                    )
                )
                served_updates.append((o, v.id, seq, eta_min))
                new_vehicle[o.id] = v.id
                new_seq[o.id] = seq
                assigned_weight += o.weight
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
    served_ids = {u[0].id for u in served_updates}
    dropped_orders = [o for o in servable if o.id not in served_ids]

    total_capacity = sum(v.capacity_weight for v in vehicles)
    utilization = (assigned_weight / total_capacity * 100.0) if total_capacity else 0.0

    # Late deliveries: served orders whose ETA slips past their window end.
    # Zero under the hard windows used here, but computed for the soft-window
    # future (and so the metric is real, not hard-coded).
    late = sum(
        1
        for o, _vid, _seq, eta in served_updates
        if eta is not None and eta > o.window_end + 1e-6
    )

    # -- diff vs the previous plan ------------------------------------------ #
    # ``reassignments`` is the frontend's "moved between vehicles" feed: only
    # orders whose vehicle changed (incl. entering/leaving the plan), matching
    # ``diffReassignments`` in the store. ``route_changes`` is the broader churn
    # metric — any order that moved vehicle OR shifted relative to the other
    # surviving orders. Removing the frozen COMPLETED prefix never counts
    # (relative sequence — see _prior_positions).
    label_of = {o.id: o.label for o in servable}
    reassignments: list[Reassignment] = []  # vehicle moves only (UI feed)
    changed_orders: list[str] = []  # any churn: moved vehicle or resequenced
    touched_vehicles: set[str] = set()
    for oid in servable_ids:
        pv = prior_vehicle.get(oid)  # None -> was unrouted (new/pending)
        nv = new_vehicle.get(oid)  # None -> dropped now
        ps = prior_seq.get(oid)
        ns = new_seq.get(oid)
        moved_vehicle = pv != nv
        resequenced = pv is not None and pv == nv and ps != ns
        if moved_vehicle:
            reassignments.append(
                Reassignment(order_id=oid, label=label_of.get(oid, oid), from_=pv, to=nv)
            )
        if moved_vehicle or resequenced:
            changed_orders.append(oid)
            if pv:
                touched_vehicles.add(pv)
            if nv:
                touched_vehicles.add(nv)
    route_changes = len(changed_orders)
    affected_orders = changed_orders
    affected_vehicles = sorted(touched_vehicles)

    metrics = Metrics(
        total_distance_km=round(total_distance_m / DIST_SCALE, 3),
        total_time_min=round(total_time_scaled / TIME_SCALE, 2),
        late_deliveries=late,
        route_changes=route_changes,
        utilization_pct=round(utilization, 1),
        reopt_ms=round(solve_ms, 1),
        dropped=len(dropped_orders),
    )

    # -- persist under the world lock --------------------------------------- #
    # COMPLETED / CANCELLED orders are not in ``servable`` and are left frozen.
    # IN_PROGRESS orders keep their status (a committed leg stays IN_PROGRESS);
    # everything else served becomes ASSIGNED. Unserved servable orders drop.
    with world._lock:
        world.plan = plan
        for o, vid, seq, eta_min in served_updates:
            if o.status != OrderStatus.IN_PROGRESS.value:
                o.status = OrderStatus.ASSIGNED.value
            o.assigned_vehicle = vid
            o.seq_index = seq
            o.eta = eta_min
        for o in dropped_orders:
            o.status = OrderStatus.DROPPED.value
            o.assigned_vehicle = None
            o.seq_index = None
            o.eta = None
        world.metrics = metrics

    return ReoptResult(
        status="ok",
        message=(
            f"re-optimized: served {len(served_ids)}/{len(servable)} across "
            f"{len(plan)} vehicle(s), {len(dropped_orders)} dropped, "
            f"{route_changes} route change(s)"
        ),
        served=len(served_ids),
        dropped=len(dropped_orders),
        solve_ms=solve_ms,
        plan=plan,
        metrics=metrics,
        route_changes=route_changes,
        reassignments=reassignments,
        affected_vehicles=affected_vehicles,
        affected_orders=affected_orders,
        warm_started=warm_started,
        used_fallback=used_fallback,
    )






