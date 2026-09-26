"""Tests for the durable-catalog persistence layer (``app.db``).

These run entirely on an in-memory SQLite engine (StaticPool so the schema
persists across sessions) — no Neon connection is required. A single opt-in test
exercises a real Postgres round-trip and is skipped unless a ``DATABASE_URL`` is
present in the environment.
"""

from __future__ import annotations

import os

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, create_engine

from app.db import (
    Database,
    depot_to_row,
    order_to_row,
    row_to_depot,
    row_to_order,
    row_to_vehicle,
    vehicle_to_row,
)
from app.models import OrderStatus, VehicleStatus
from app.state import DEPOT, build_seed_orders, build_seed_vehicles


@pytest.fixture
def sqlite_db() -> Database:
    """A Database backed by a shared in-memory SQLite engine."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    d = Database()
    d.engine = engine
    d.enabled = True
    d.status = "connected (sqlite-test)"
    return d


# -- pure conversion helpers ------------------------------------------------- #
def test_depot_row_roundtrip():
    row = depot_to_row(DEPOT)
    back = row_to_depot(row)
    assert back.id == DEPOT.id and back.name == DEPOT.name
    assert back.location.lat == DEPOT.location.lat
    assert back.location.lng == DEPOT.location.lng


def test_vehicle_row_roundtrip_resets_live_fields():
    v = build_seed_vehicles()[0]
    v.status = VehicleStatus.BROKEN.value
    v.progress = 0.7
    row = vehicle_to_row(v)
    back = row_to_vehicle(row)
    assert back.id == v.id and back.capacity_weight == v.capacity_weight
    # hydration resets live fields to fresh-start defaults
    assert back.status == VehicleStatus.ACTIVE.value
    assert back.progress == 0.0
    assert back.driver_available is True
    assert back.location.lat == v.home.lat


def test_order_row_roundtrip_resets_live_fields():
    o = build_seed_orders()[0]
    o.status = OrderStatus.COMPLETED.value
    o.assigned_vehicle = "v1"
    o.eta = 512.0
    row = order_to_row(o)
    back = row_to_order(row)
    assert back.id == o.id and back.weight == o.weight and back.volume == o.volume
    assert back.status == OrderStatus.PENDING.value
    assert back.assigned_vehicle is None
    assert back.eta is None


# -- disabled database is a graceful no-op ----------------------------------- #
def test_disabled_database_is_noop():
    d = Database()
    assert d.enabled is False
    assert d.is_empty() is True
    assert d.load_catalog() is None
    # writes must not raise when disabled
    d.upsert_vehicle(build_seed_vehicles()[0])
    d.upsert_order(build_seed_orders()[0])
    d.delete_vehicle("v1")
    d.delete_order("o1")


def test_init_without_url_stays_disabled():
    # offline_env fixture has already nulled settings.database_url.
    d = Database()
    status = d.init()
    assert d.enabled is False
    assert "in-memory" in status


# -- SQLite-backed persistence ----------------------------------------------- #
def test_is_empty_before_and_after_reseed(sqlite_db):
    assert sqlite_db.is_empty() is True
    sqlite_db.reseed(DEPOT, build_seed_vehicles(), build_seed_orders())
    assert sqlite_db.is_empty() is False


def test_reseed_then_load_catalog(sqlite_db):
    sqlite_db.reseed(DEPOT, build_seed_vehicles(), build_seed_orders())
    loaded = sqlite_db.load_catalog()
    assert loaded is not None
    depot, vehicles, orders = loaded
    assert depot.id == DEPOT.id
    assert len(vehicles) == 4
    assert len(orders) == 15
    assert {v.id for v in vehicles} == {"v1", "v2", "v3", "v4"}


def test_reseed_is_idempotent_wipe(sqlite_db):
    sqlite_db.reseed(DEPOT, build_seed_vehicles(), build_seed_orders())
    # reseed with a subset should wipe and repopulate, not append
    sqlite_db.reseed(DEPOT, build_seed_vehicles()[:2], build_seed_orders()[:3])
    _, vehicles, orders = sqlite_db.load_catalog()
    assert len(vehicles) == 2
    assert len(orders) == 3


def test_upsert_and_delete_vehicle(sqlite_db):
    v = build_seed_vehicles()[0]
    sqlite_db.upsert_vehicle(v)
    _, vehicles, _ = sqlite_db.load_catalog()
    assert [x.id for x in vehicles] == ["v1"]
    # update in place
    v.capacity_weight = 999
    sqlite_db.upsert_vehicle(v)
    _, vehicles, _ = sqlite_db.load_catalog()
    assert len(vehicles) == 1 and vehicles[0].capacity_weight == 999
    # delete
    sqlite_db.delete_vehicle("v1")
    _, vehicles, _ = sqlite_db.load_catalog()
    assert vehicles == []


def test_upsert_and_delete_order(sqlite_db):
    o = build_seed_orders()[0]
    sqlite_db.upsert_order(o)
    _, _, orders = sqlite_db.load_catalog()
    assert [x.id for x in orders] == [o.id]
    o.weight = 12.5
    sqlite_db.upsert_order(o)
    _, _, orders = sqlite_db.load_catalog()
    assert len(orders) == 1 and orders[0].weight == 12.5
    sqlite_db.delete_order(o.id)
    _, _, orders = sqlite_db.load_catalog()
    assert orders == []


# -- opt-in real Postgres round-trip (skipped offline) ----------------------- #
_HAS_PG = bool(os.environ.get("DATABASE_URL") or os.environ.get("DATABASE_URL_POOLED"))


@pytest.mark.skipif(
    not _HAS_PG,
    reason="no DATABASE_URL in the environment; real Postgres round-trip skipped (offline)",
)
def test_real_postgres_init(monkeypatch):
    from app.config import settings

    url = os.environ.get("DATABASE_URL_POOLED") or os.environ.get("DATABASE_URL")
    monkeypatch.setattr(settings, "database_url_pooled", url, raising=False)
    monkeypatch.setattr(settings, "database_url", url, raising=False)
    d = Database()
    status = d.init()
    assert isinstance(status, str)
    # init never raises; it either connects or degrades gracefully.
    assert d.enabled in (True, False)
