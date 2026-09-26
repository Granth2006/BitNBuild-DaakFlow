"""Durable persistence of the catalog (depot / vehicles / orders) to Neon
Postgres via SQLModel.

The app degrades gracefully: if the database is unreachable, ``Database.enabled``
stays False, every write becomes a no-op, and the in-memory ``WorldState`` remains
the source of truth so the API still runs fully offline.
"""

from __future__ import annotations

from typing import Optional

from sqlmodel import Session, SQLModel, create_engine, select

from .config import settings
from .models import (
    Depot,
    DepotRow,
    LatLng,
    Order,
    OrderRow,
    OrderStatus,
    Vehicle,
    VehicleRow,
    VehicleStatus,
)


# --------------------------------------------------------------------------- #
# Row <-> API model conversion
# --------------------------------------------------------------------------- #
def row_to_depot(r: DepotRow) -> Depot:
    return Depot(id=r.id, name=r.name, location=LatLng(lat=r.lat, lng=r.lng))


def depot_to_row(d: Depot) -> DepotRow:
    return DepotRow(id=d.id, name=d.name, lat=d.location.lat, lng=d.location.lng)


def row_to_vehicle(r: VehicleRow) -> Vehicle:
    # Live fields reset to fresh-start defaults on hydration.
    return Vehicle(
        id=r.id,
        name=r.name,
        type=r.type,
        color=r.color,
        location=LatLng(lat=r.home_lat, lng=r.home_lng),
        home=LatLng(lat=r.home_lat, lng=r.home_lng),
        capacity_weight=r.capacity_weight,
        capacity_volume=r.capacity_volume,
        speed_kmh=r.speed_kmh,
        status=VehicleStatus.ACTIVE,
        driver=r.driver,
        driver_available=True,
        shift_start=r.shift_start,
        shift_end=r.shift_end,
        progress=0.0,
    )


def vehicle_to_row(v: Vehicle) -> VehicleRow:
    return VehicleRow(
        id=v.id,
        name=v.name,
        type=str(v.type),
        color=v.color,
        home_lat=v.home.lat,
        home_lng=v.home.lng,
        capacity_weight=v.capacity_weight,
        capacity_volume=v.capacity_volume,
        speed_kmh=v.speed_kmh,
        driver=v.driver,
        shift_start=v.shift_start,
        shift_end=v.shift_end,
    )


def row_to_order(r: OrderRow) -> Order:
    return Order(
        id=r.id,
        label=r.label,
        location=LatLng(lat=r.lat, lng=r.lng),
        address=r.address,
        window_start=r.window_start,
        window_end=r.window_end,
        weight=r.weight,
        volume=r.volume,
        priority=r.priority,
        status=OrderStatus.PENDING,
        assigned_vehicle=None,
        seq_index=None,
        eta=None,
        created_at=r.created_at,
    )


def order_to_row(o: Order) -> OrderRow:
    return OrderRow(
        id=o.id,
        label=o.label,
        lat=o.location.lat,
        lng=o.location.lng,
        address=o.address,
        window_start=o.window_start,
        window_end=o.window_end,
        weight=o.weight,
        volume=o.volume,
        priority=o.priority,
        created_at=o.created_at,
    )


class Database:
    def __init__(self) -> None:
        self.engine = None
        self.enabled = False
        self.status = "disabled"

    def init(self) -> str:
        """Create the engine, create tables, and prove connectivity with a read.
        Returns a human-readable status; never raises."""
        url = settings.sqlalchemy_url
        if not url:
            self.status = "no DATABASE_URL configured; in-memory only"
            return self.status
        try:
            self.engine = create_engine(
                url,
                pool_pre_ping=True,
                connect_args={"connect_timeout": 10},
            )
            SQLModel.metadata.create_all(self.engine)
            # Round-trip read to confirm the connection actually works.
            with Session(self.engine) as session:
                session.exec(select(DepotRow)).first()
            self.enabled = True
            self.status = "connected"
        except Exception as exc:  # noqa: BLE001 - degrade gracefully
            self.engine = None
            self.enabled = False
            self.status = f"unreachable, in-memory only ({type(exc).__name__}: {exc})"
        return self.status

    def is_empty(self) -> bool:
        if not self.enabled:
            return True
        with Session(self.engine) as session:
            return session.exec(select(VehicleRow)).first() is None

    def load_catalog(self) -> Optional[tuple[Depot, list[Vehicle], list[Order]]]:
        if not self.enabled:
            return None
        with Session(self.engine) as session:
            depot_row = session.exec(select(DepotRow)).first()
            depot = row_to_depot(depot_row) if depot_row else None
            from .state import DEPOT  # local import avoids a cycle

            depot = depot or DEPOT
            vehicles = [row_to_vehicle(r) for r in session.exec(select(VehicleRow)).all()]
            orders = [row_to_order(r) for r in session.exec(select(OrderRow)).all()]
        return depot, vehicles, orders

    def reseed(self, depot: Depot, vehicles: list[Vehicle], orders: list[Order]) -> None:
        """Wipe and repopulate the catalog from the given world."""
        if not self.enabled:
            return
        with Session(self.engine) as session:
            for row in session.exec(select(OrderRow)).all():
                session.delete(row)
            for row in session.exec(select(VehicleRow)).all():
                session.delete(row)
            for row in session.exec(select(DepotRow)).all():
                session.delete(row)
            session.flush()
            session.add(depot_to_row(depot))
            for v in vehicles:
                session.add(vehicle_to_row(v))
            for o in orders:
                session.add(order_to_row(o))
            session.commit()

    # -- catalog mirroring of live CRUD ------------------------------------ #
    def upsert_vehicle(self, v: Vehicle) -> None:
        if not self.enabled:
            return
        with Session(self.engine) as session:
            existing = session.get(VehicleRow, v.id)
            row = vehicle_to_row(v)
            if existing:
                for field, value in row.model_dump().items():
                    setattr(existing, field, value)
                session.add(existing)
            else:
                session.add(row)
            session.commit()

    def delete_vehicle(self, vid: str) -> None:
        if not self.enabled:
            return
        with Session(self.engine) as session:
            row = session.get(VehicleRow, vid)
            if row:
                session.delete(row)
                session.commit()

    def upsert_order(self, o: Order) -> None:
        if not self.enabled:
            return
        with Session(self.engine) as session:
            existing = session.get(OrderRow, o.id)
            row = order_to_row(o)
            if existing:
                for field, value in row.model_dump().items():
                    setattr(existing, field, value)
                session.add(existing)
            else:
                session.add(row)
            session.commit()

    def delete_order(self, oid: str) -> None:
        if not self.enabled:
            return
        with Session(self.engine) as session:
            row = session.get(OrderRow, oid)
            if row:
                session.delete(row)
                session.commit()


# Module-level singleton.
db = Database()
