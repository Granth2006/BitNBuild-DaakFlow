"""Persistence layer exercised against file-backed SQLite (offline, hermetic).

Proves the SQLModel tables, conversions, seed, hydrate, and CRUD mirroring work
without needing a live Neon connection.
"""

from __future__ import annotations

from sqlmodel import SQLModel, create_engine

from app.db import Database
from app.models import Order, OrderCreate
from app.state import WorldState


def _sqlite_db(tmp_path) -> Database:
    d = Database()
    d.engine = create_engine(f"sqlite:///{tmp_path / 'catalog.db'}")
    SQLModel.metadata.create_all(d.engine)
    d.enabled = True
    d.status = "connected (sqlite test)"
    return d


def test_reseed_and_load(tmp_path):
    d = _sqlite_db(tmp_path)
    w = WorldState()
    w.seed()
    d.reseed(w.depot, w.vehicles, w.orders)

    loaded = d.load_catalog()
    assert loaded is not None
    depot, vehicles, orders = loaded
    assert depot.id == "depot"
    assert len(vehicles) == 4
    assert len(orders) == 15
    v1 = next(v for v in vehicles if v.id == "v1")
    assert v1.capacity_weight == 600
    # Live fields hydrate to defaults.
    assert v1.status == "ACTIVE"
    assert v1.location.lat == v1.home.lat


def test_is_empty(tmp_path):
    d = _sqlite_db(tmp_path)
    assert d.is_empty() is True
    w = WorldState()
    w.seed()
    d.reseed(w.depot, w.vehicles, w.orders)
    assert d.is_empty() is False


def test_upsert_and_delete_order(tmp_path):
    d = _sqlite_db(tmp_path)
    w = WorldState()
    w.seed()
    d.reseed(w.depot, w.vehicles, w.orders)

    new = w.add_order(OrderCreate(address="X", lat=12.9, lng=77.6, weight=80,
                                  priority=2, window_start=500, window_end=600))
    d.upsert_order(new)
    _, _, orders = d.load_catalog()
    assert any(o.id == new.id for o in orders)

    # update mirrors
    new.address = "Updated"
    d.upsert_order(new)
    _, _, orders = d.load_catalog()
    assert next(o.id == new.id for o in orders if o.id == new.id)
    assert next(o.address for o in orders if o.id == new.id) == "Updated"

    d.delete_order(new.id)
    _, _, orders = d.load_catalog()
    assert not any(o.id == new.id for o in orders)
