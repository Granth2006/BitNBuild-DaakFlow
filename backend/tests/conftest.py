"""Shared test fixtures.

Tests run fully offline: the real Neon connection is skipped so the suite is
hermetic and fast. The persistence code path is exercised separately against a
file-backed SQLite database (see test_db.py).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.db import db
from app.main import app


@pytest.fixture(scope="session", autouse=True)
def _offline_db():
    """Neuter the live DB so lifespan seeds in-memory only."""
    db.enabled = False
    db.status = "disabled (test)"
    db.init = lambda: "disabled (test)"  # type: ignore[assignment]
    yield


@pytest.fixture()
def client():
    with TestClient(app) as c:
        yield c
