"""Shared pytest fixtures for the DaakFlow backend tests.

Key guarantees enforced here for every test:

* **Fully offline.** ``settings.database_url`` / ``database_url_pooled`` and the
  distance service's ``osrm_url`` are forced to ``None``, and the ``db``
  singleton is pinned disabled, so nothing ever touches Neon or OSRM.
* **Fast solves.** The OR-Tools search budgets are reduced from 2 s to 1 s.
  The first-solution strategy already serves the seed scenario fully, so the
  served/dropped results are unchanged — this only trims wall-clock time.
* **Isolated state.** Unit tests build fresh ``WorldState`` instances; the API
  ``client`` fixture re-seeds the shared singleton via the app lifespan on every
  test (and the lifespan's ``db.init()`` is a no-op offline).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.optimizer as optimizer_mod
import app.reoptimize as reoptimize_mod
from app.config import settings
from app.db import db as db_singleton
from app.distances import distances as distances_singleton
from app.state import WorldState


@pytest.fixture(autouse=True)
def offline_env(monkeypatch):
    """Pin the entire environment offline for every test."""
    monkeypatch.setattr(settings, "database_url", None, raising=False)
    monkeypatch.setattr(settings, "database_url_pooled", None, raising=False)
    monkeypatch.setattr(settings, "osrm_url", None, raising=False)
    # The DB singleton must never open a real (Neon) connection during tests.
    monkeypatch.setattr(db_singleton, "engine", None, raising=False)
    monkeypatch.setattr(db_singleton, "enabled", False, raising=False)
    monkeypatch.setattr(db_singleton, "status", "disabled (test)", raising=False)
    # The shared distance service must use only the offline haversine fallback.
    monkeypatch.setattr(distances_singleton, "osrm_url", None, raising=False)
    distances_singleton._cache.clear()
    distances_singleton.last_source = "haversine"
    yield


@pytest.fixture(autouse=True)
def fast_solver(monkeypatch):
    """Halve OR-Tools search budgets to keep the suite quick. Feasibility (and
    thus served/dropped counts) is unaffected — only the optimization time."""
    monkeypatch.setattr(optimizer_mod, "SOLVE_TIME_LIMIT_S", 1, raising=False)
    monkeypatch.setattr(reoptimize_mod, "REOPT_TIME_LIMIT_S", 1, raising=False)
    yield


@pytest.fixture
def fresh_world() -> WorldState:
    """An empty, unseeded world."""
    return WorldState()


@pytest.fixture
def seeded_world() -> WorldState:
    """A fresh world holding the default mock scenario (4 vehicles, 15 orders)."""
    w = WorldState()
    w.seed()
    return w


@pytest.fixture
def optimized_world(seeded_world) -> WorldState:
    """A seeded world after an initial cold optimize (has a plan + metrics)."""
    from app.optimizer import optimize

    optimize(seeded_world)
    return seeded_world


@pytest.fixture
def client(offline_env):
    """A FastAPI TestClient with the lifespan run (world seeded, db disabled)."""
    from app.main import app

    with TestClient(app) as c:
        yield c
