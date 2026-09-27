"""Data models for the DaakFlow backend.

Two layers live here:

* ``*Row`` classes are SQLModel tables — the durable *catalog* persisted to
  Neon Postgres (definitions of depot / vehicles / orders). Snake_case columns.
* The plain Pydantic classes are the **API schemas**. They serialize to the
  exact camelCase shape the frontend consumes (see ``frontend/src/lib/types.ts``)
  via an alias generator, while staying snake_case in Python.

The frontend contract is authoritative for JSON field naming; §5 of the plan is
the conceptual model.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Field as SQLField
from sqlmodel import SQLModel


# --------------------------------------------------------------------------- #
# Enums (values match the frontend string unions exactly)
# --------------------------------------------------------------------------- #
class OrderStatus(str, Enum):
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    DROPPED = "DROPPED"


class VehicleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    BROKEN = "BROKEN"
    IDLE = "IDLE"


class VehicleType(str, Enum):
    TRUCK = "TRUCK"
    VAN = "VAN"
    BIKE = "BIKE"


# --------------------------------------------------------------------------- #
# API base — snake_case in Python, camelCase over the wire
# --------------------------------------------------------------------------- #
def to_camel(field: str) -> str:
    head, *rest = field.split("_")
    return head + "".join(word.capitalize() for word in rest)


class ApiModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        use_enum_values=True,
    )


class LatLng(ApiModel):
    lat: float
    lng: float


# --------------------------------------------------------------------------- #
# Durable catalog tables (Neon Postgres)
# --------------------------------------------------------------------------- #
class DepotRow(SQLModel, table=True):
    __tablename__ = "depots"

    id: str = SQLField(primary_key=True)
    name: str
    lat: float
    lng: float


class VehicleRow(SQLModel, table=True):
    __tablename__ = "vehicles"

    id: str = SQLField(primary_key=True)
    name: str
    type: str
    color: str
    home_lat: float
    home_lng: float
    capacity_weight: int
    capacity_volume: int
    speed_kmh: int
    driver: str
    shift_start: int
    shift_end: int


class OrderRow(SQLModel, table=True):
    __tablename__ = "orders"

    id: str = SQLField(primary_key=True)
    label: str
    lat: float
    lng: float
    address: str
    window_start: int
    window_end: int
    weight: float
    volume: int
    priority: int
    created_at: int


# --------------------------------------------------------------------------- #
# API schemas — mirror frontend/src/lib/types.ts
# --------------------------------------------------------------------------- #
class Depot(ApiModel):
    id: str
    name: str
    location: LatLng


class Order(ApiModel):
    id: str
    label: str
    location: LatLng
    address: str
    window_start: int  # minutes from midnight
    window_end: int
    weight: float  # kg
    volume: int  # arbitrary units
    priority: int  # 1..4 (4 = critical)
    status: OrderStatus = OrderStatus.PENDING
    assigned_vehicle: Optional[str] = None
    seq_index: Optional[int] = None
    eta: Optional[float] = None  # minutes
    created_at: int


class Vehicle(ApiModel):
    id: str
    name: str
    type: VehicleType
    color: str
    location: LatLng  # live position
    home: LatLng  # depot location
    capacity_weight: int
    capacity_volume: int
    speed_kmh: int
    status: VehicleStatus = VehicleStatus.ACTIVE
    driver: str
    driver_available: bool = True
    shift_start: int  # minutes
    shift_end: int  # minutes (working-hour limit)
    progress: float = 0.0  # 0..1 along current leg


class RouteStop(ApiModel):
    order_id: str
    seq: int
    eta: float  # minutes
    locked: bool = False


class Metrics(ApiModel):
    total_distance_km: float
    total_time_min: float
    late_deliveries: int
    route_changes: int
    utilization_pct: float
    reopt_ms: float
    dropped: int


class Reassignment(ApiModel):
    order_id: str
    label: str
    # `from` is a Python keyword; expose it explicitly under that wire name.
    from_: Optional[str] = Field(default=None, alias="from")
    to: Optional[str] = None


class WorldEvent(ApiModel):
    id: str
    type: str
    description: str
    sim_time: int
    affected_vehicles: list[str] = Field(default_factory=list)
    affected_orders: list[str] = Field(default_factory=list)
    reopt_ms: float = 0.0
    route_changes: int = 0
    reassignments: list[Reassignment] = Field(default_factory=list)


class WorldSnapshot(ApiModel):
    """Full world state returned by ``GET /state`` — a superset the frontend
    store can consume directly."""

    depot: Depot
    vehicles: list[Vehicle]
    orders: list[Order]
    plan: dict[str, list[RouteStop]] = Field(default_factory=dict)
    metrics: Optional[Metrics] = None
    sim_time: int
    traffic_factor: float = 1.0
    events: list[WorldEvent] = Field(default_factory=list)
    # Phase 7 — simulation clock state (mirrors WorldState.running / .speed).
    running: bool = False
    speed: int = 3


# --------------------------------------------------------------------------- #
# CRUD payloads (mirror the frontend VehicleDraft / OrderDraft)
# --------------------------------------------------------------------------- #
class VehicleCreate(ApiModel):
    name: str = ""
    driver: str = ""
    type: VehicleType = VehicleType.VAN
    capacity_weight: int = 400
    speed_kmh: int = 40


class VehicleUpdate(ApiModel):
    name: Optional[str] = None
    driver: Optional[str] = None
    type: Optional[VehicleType] = None
    capacity_weight: Optional[int] = None
    speed_kmh: Optional[int] = None
    status: Optional[VehicleStatus] = None
    driver_available: Optional[bool] = None


class OrderCreate(ApiModel):
    address: str = ""
    lat: float
    lng: float
    weight: float
    priority: int = 2
    window_start: int
    window_end: int
    label: Optional[str] = None


class OrderUpdate(ApiModel):
    address: Optional[str] = None
    lat: Optional[float] = None
    lng: Optional[float] = None
    weight: Optional[float] = None
    priority: Optional[int] = None
    window_start: Optional[int] = None
    window_end: Optional[int] = None
    status: Optional[OrderStatus] = None


# --------------------------------------------------------------------------- #
# Phase 6 request payloads (disruptions + sim support)
# --------------------------------------------------------------------------- #
class EventPayload(ApiModel):
    """Optional details for a disruption. Every field is optional: a bare event
    (as the demo console fires) synthesises sensible, deterministic defaults;
    callers may pin a target / body for reproducible scenarios.

    * NEW_ORDER / PRIORITY_ORDER: ``lat``/``lng``/``weight``/``priority``/
      ``window_start``/``window_end``/``address``/``label`` describe the order.
    * BREAKDOWN: ``vehicle_id`` — which vehicle fails (else the busiest active).
    * TRAFFIC: ``factor_delta`` — how much to raise the congestion factor.
    * CANCELLATION / TIME_CHANGE / ADDRESS_CHANGE: ``order_id`` — the target
      order (else the first eligible one); ADDRESS_CHANGE also reads lat/lng.
    """

    # order body (NEW_ORDER / PRIORITY_ORDER, plus lat/lng for ADDRESS_CHANGE)
    lat: Optional[float] = None
    lng: Optional[float] = None
    weight: Optional[float] = None
    priority: Optional[int] = None
    window_start: Optional[int] = None
    window_end: Optional[int] = None
    address: Optional[str] = None
    label: Optional[str] = None
    # targets
    vehicle_id: Optional[str] = None
    order_id: Optional[str] = None
    # TRAFFIC
    factor_delta: Optional[float] = None


class EventRequest(ApiModel):
    """Body of ``POST /events`` — a disruption ``type`` plus optional payload."""

    type: str
    payload: EventPayload = Field(default_factory=EventPayload)


class VehiclePosition(ApiModel):
    """Body of ``POST /vehicles/{id}/position`` — sim support for moving a
    vehicle to its live location (and optional leg progress)."""

    lat: float
    lng: float
    progress: float = 0.0


class SpeedRequest(ApiModel):
    """Body of ``POST /sim/speed`` — sim-minutes advanced per real tick."""

    speed: int

