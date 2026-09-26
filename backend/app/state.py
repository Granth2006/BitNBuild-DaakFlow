"""In-memory ``WorldState`` — the authoritative live source of truth.

Durable *definitions* are mirrored to Postgres by the persistence layer, but the
live world (vehicle positions, plan, sim_time, order status) is held here in
memory, per the plan's key design principle.
"""

from __future__ import annotations

import threading
from typing import Optional

from .models import (
    Depot,
    LatLng,
    Metrics,
    Order,
    OrderCreate,
    OrderStatus,
    OrderUpdate,
    RouteStop,
    Vehicle,
    VehicleCreate,
    VehicleStatus,
    VehicleType,
    VehicleUpdate,
    WorldEvent,
    WorldSnapshot,
)

# Sim day runs 08:00 (480) to 18:00 (1080), minutes from midnight.
DAY_START = 480
DAY_END = 1080

# Mirror of frontend/src/mock/seed.ts ------------------------------------------
DEPOT = Depot(id="depot", name="Central Hub", location=LatLng(lat=12.9716, lng=77.5946))

VEHICLE_HUES = ["#38bdf8", "#a78bfa", "#4ade80", "#fb7185", "#fbbf24", "#22d3ee", "#f472b6"]

# Prefill specs per vehicle type (matches VEHICLE_TYPE_META in seed.ts).
VEHICLE_TYPE_META = {
    "TRUCK": {"label": "Truck", "capacity_volume": 120, "speed_kmh": 34},
    "VAN": {"label": "Van", "capacity_volume": 90, "speed_kmh": 42},
    "BIKE": {"label": "Bike", "capacity_volume": 20, "speed_kmh": 30},
}

# (id, name, type, capacity_weight, speed_kmh, driver) — capacity_volume is 100
# for every seed vehicle (the seed's shared base overrides the type meta).
_SEED_VEHICLES = [
    ("v1", "Truck 01", "TRUCK", 600, 34, "Arjun"),
    ("v2", "Truck 02", "TRUCK", 550, 38, "Meera"),
    ("v3", "Van 03", "VAN", 400, 42, "Rahul"),
    ("v4", "Van 04", "VAN", 400, 40, "Sofia"),
]

# (label, lat, lng, address, window_start, window_end, weight, priority)
_SEED_ORDERS = [
    ("A", 13.0298, 77.5709, "Hebbal", 500, 620, 80, 2),
    ("B", 12.9345, 77.6100, "Koramangala", 510, 600, 120, 3),
    ("C", 12.9784, 77.6408, "Indiranagar", 520, 660, 60, 2),
    ("D", 12.9141, 77.6412, "HSR Layout", 540, 700, 150, 4),
    ("E", 12.9698, 77.7500, "Whitefield", 560, 780, 90, 1),
    ("F", 12.9250, 77.5938, "Jayanagar", 500, 640, 110, 3),
    ("G", 13.0067, 77.5573, "Malleshwaram", 530, 680, 70, 2),
    ("H", 12.9081, 77.5679, "JP Nagar", 520, 660, 130, 2),
    ("I", 12.9855, 77.6060, "MG Road", 505, 590, 50, 3),
    ("J", 13.0358, 77.5970, "Yelahanka Rd", 570, 760, 100, 1),
    ("K", 12.9569, 77.7011, "Marathahalli", 550, 720, 140, 3),
    ("L", 12.9121, 77.6446, "BTM Layout", 515, 650, 65, 2),
    ("M", 12.9992, 77.6607, "CV Raman Nagar", 560, 740, 95, 1),
    ("N", 12.9438, 77.5738, "Banashankari", 510, 630, 115, 4),
    ("O", 12.9855, 77.5354, "Rajajinagar", 525, 690, 75, 2),
]


def build_seed_vehicles() -> list[Vehicle]:
    home = DEPOT.location
    out: list[Vehicle] = []
    for i, (vid, name, vtype, cap_w, speed, driver) in enumerate(_SEED_VEHICLES):
        out.append(
            Vehicle(
                id=vid,
                name=name,
                type=vtype,
                color=VEHICLE_HUES[i % len(VEHICLE_HUES)],
                location=LatLng(lat=home.lat, lng=home.lng),
                home=LatLng(lat=home.lat, lng=home.lng),
                capacity_weight=cap_w,
                capacity_volume=100,
                speed_kmh=speed,
                status=VehicleStatus.ACTIVE,
                driver=driver,
                driver_available=True,
                shift_start=DAY_START,
                shift_end=DAY_END,
                progress=0.0,
            )
        )
    return out


def build_seed_orders() -> list[Order]:
    out: list[Order] = []
    for i, (label, lat, lng, addr, ws, we, weight, prio) in enumerate(_SEED_ORDERS):
        out.append(
            Order(
                id=f"o{i + 1}",
                label=label,
                location=LatLng(lat=lat, lng=lng),
                address=addr,
                window_start=ws,
                window_end=we,
                weight=weight,
                volume=round(weight / 8),
                priority=prio,
                status=OrderStatus.PENDING,
                assigned_vehicle=None,
                seq_index=None,
                eta=None,
                created_at=DAY_START,
            )
        )
    return out


class WorldState:
    """Thread-safe in-memory world. All mutations return the affected API model
    so callers (routes) can mirror the change to durable storage."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.depot: Depot = DEPOT
        self.vehicles: list[Vehicle] = []
        self.orders: list[Order] = []
        self.plan: dict[str, list[RouteStop]] = {}
        self.metrics: Optional[Metrics] = None
        self.sim_time: int = DAY_START
        self.traffic_factor: float = 1.0
        self.events: list[WorldEvent] = []
        self._veh_seq = 0
        self._ord_seq = 0

    # -- lifecycle ---------------------------------------------------------- #
    def seed(self) -> None:
        """Rebuild the default mock scenario in memory."""
        with self._lock:
            self.depot = DEPOT
            self.vehicles = build_seed_vehicles()
            self.orders = build_seed_orders()
            self.plan = {}
            self.metrics = None
            self.sim_time = DAY_START
            self.traffic_factor = 1.0
            self.events = []
            self._veh_seq = 0
            self._ord_seq = 0

    reset = seed  # reset == restore the seed scenario (demo semantics)

    def load_catalog(
        self, depot: Depot, vehicles: list[Vehicle], orders: list[Order]
    ) -> None:
        """Hydrate the live world from durable catalog rows. Live fields are set
        to their fresh-start defaults (already baked into the passed models)."""
        with self._lock:
            self.depot = depot
            self.vehicles = list(vehicles)
            self.orders = list(orders)
            self.plan = {}
            self.metrics = None
            self.sim_time = DAY_START
            self.traffic_factor = 1.0
            self.events = []
            # Keep id generators ahead of any hydrated user ids.
            self._veh_seq = _max_seq(v.id for v in vehicles)
            self._ord_seq = _max_seq(o.id for o in orders)

    def snapshot(self) -> WorldSnapshot:
        with self._lock:
            return WorldSnapshot(
                depot=self.depot,
                vehicles=list(self.vehicles),
                orders=list(self.orders),
                plan=dict(self.plan),
                metrics=self.metrics,
                sim_time=self.sim_time,
                traffic_factor=self.traffic_factor,
                events=list(self.events),
            )

    # -- vehicle CRUD ------------------------------------------------------- #
    def list_vehicles(self) -> list[Vehicle]:
        with self._lock:
            return list(self.vehicles)

    def get_vehicle(self, vid: str) -> Optional[Vehicle]:
        with self._lock:
            return next((v for v in self.vehicles if v.id == vid), None)

    def add_vehicle(self, draft: VehicleCreate) -> Vehicle:
        with self._lock:
            self._veh_seq += 1
            meta = VEHICLE_TYPE_META[str(draft.type)]
            veh = Vehicle(
                id=f"v-usr-{self._veh_seq}",
                name=(draft.name or "").strip() or f"{meta['label']} {len(self.vehicles) + 1}",
                type=draft.type,
                color=VEHICLE_HUES[len(self.vehicles) % len(VEHICLE_HUES)],
                location=LatLng(lat=self.depot.location.lat, lng=self.depot.location.lng),
                home=LatLng(lat=self.depot.location.lat, lng=self.depot.location.lng),
                capacity_weight=draft.capacity_weight,
                capacity_volume=meta["capacity_volume"],
                speed_kmh=draft.speed_kmh,
                status=VehicleStatus.ACTIVE,
                driver=(draft.driver or "").strip() or "Unassigned",
                driver_available=True,
                shift_start=DAY_START,
                shift_end=DAY_END,
                progress=0.0,
            )
            self.vehicles.append(veh)
            return veh

    def update_vehicle(self, vid: str, patch: VehicleUpdate) -> Optional[Vehicle]:
        with self._lock:
            veh = next((v for v in self.vehicles if v.id == vid), None)
            if veh is None:
                return None
            if patch.name is not None:
                veh.name = patch.name.strip() or veh.name
            if patch.driver is not None:
                veh.driver = patch.driver.strip() or veh.driver
            if patch.capacity_weight is not None:
                veh.capacity_weight = patch.capacity_weight
            if patch.speed_kmh is not None:
                veh.speed_kmh = patch.speed_kmh
            if patch.type is not None and patch.type != veh.type:
                veh.type = patch.type
                veh.capacity_volume = VEHICLE_TYPE_META[str(patch.type)]["capacity_volume"]
            if patch.status is not None:
                veh.status = patch.status
            if patch.driver_available is not None:
                veh.driver_available = patch.driver_available
            return veh

    def delete_vehicle(self, vid: str) -> bool:
        with self._lock:
            before = len(self.vehicles)
            self.vehicles = [v for v in self.vehicles if v.id != vid]
            if len(self.vehicles) == before:
                return False
            # Free that vehicle's unfinished orders back into the pool.
            for o in self.orders:
                if o.assigned_vehicle == vid and o.status not in (
                    OrderStatus.COMPLETED.value,
                    OrderStatus.CANCELLED.value,
                ):
                    o.status = OrderStatus.PENDING.value
                    o.assigned_vehicle = None
                    o.seq_index = None
                    o.eta = None
            return True

    # -- order CRUD --------------------------------------------------------- #
    def list_orders(self) -> list[Order]:
        with self._lock:
            return list(self.orders)

    def get_order(self, oid: str) -> Optional[Order]:
        with self._lock:
            return next((o for o in self.orders if o.id == oid), None)

    def add_order(self, draft: OrderCreate) -> Order:
        with self._lock:
            self._ord_seq += 1
            order = Order(
                id=f"o-usr-{self._ord_seq}",
                label=(draft.label or "").strip() or f"U{self._ord_seq}",
                location=LatLng(lat=draft.lat, lng=draft.lng),
                address=(draft.address or "").strip() or "Custom stop",
                window_start=draft.window_start,
                window_end=draft.window_end,
                weight=draft.weight,
                volume=max(1, round(draft.weight / 8)),
                priority=draft.priority,
                status=OrderStatus.PENDING,
                assigned_vehicle=None,
                seq_index=None,
                eta=None,
                created_at=self.sim_time,
            )
            self.orders.append(order)
            return order

    def update_order(self, oid: str, patch: OrderUpdate) -> Optional[Order]:
        with self._lock:
            order = next((o for o in self.orders if o.id == oid), None)
            if order is None:
                return None
            if patch.address is not None:
                order.address = patch.address.strip() or order.address
            if patch.lat is not None:
                order.location.lat = patch.lat
            if patch.lng is not None:
                order.location.lng = patch.lng
            if patch.weight is not None:
                order.weight = patch.weight
                order.volume = max(1, round(patch.weight / 8))
            if patch.priority is not None:
                order.priority = patch.priority
            if patch.window_start is not None:
                order.window_start = patch.window_start
            if patch.window_end is not None:
                order.window_end = patch.window_end
            if patch.status is not None:
                order.status = patch.status
            return order

    def delete_order(self, oid: str) -> bool:
        with self._lock:
            before = len(self.orders)
            self.orders = [o for o in self.orders if o.id != oid]
            return len(self.orders) != before


def _max_seq(ids) -> int:
    """Highest ``-usr-N`` suffix among ids, so generated ids never collide."""
    best = 0
    for _id in ids:
        if "-usr-" in _id:
            try:
                best = max(best, int(_id.rsplit("-", 1)[1]))
            except ValueError:
                pass
    return best


# Module-level singleton used by the app.
world = WorldState()


