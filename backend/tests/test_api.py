"""Tests for the FastAPI routes (``app.main``) via the TestClient.

The ``client`` fixture runs the app lifespan (seeding the world) with the DB
forced disabled, so these round-trips need no network and no Neon.
"""

from __future__ import annotations


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "db" in body


def test_get_state_is_camelcase_and_seeded(client):
    resp = client.get("/state")
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["vehicles"]) == 4
    assert len(body["orders"]) == 15
    assert body["simTime"] == 480
    assert body["trafficFactor"] == 1.0
    assert "plan" in body and "events" in body
    # The static baseline is exposed but null until the first plan is captured.
    assert "baseline" in body and body["baseline"] is None
    # vehicle objects use the camelCase wire contract
    v = body["vehicles"][0]
    for key in ("capacityWeight", "capacityVolume", "speedKmh", "driverAvailable", "shiftStart"):
        assert key in v
    # order objects too
    o = body["orders"][0]
    for key in ("windowStart", "windowEnd", "assignedVehicle", "seqIndex", "createdAt"):
        assert key in o


def test_get_depot(client):
    resp = client.get("/depot")
    assert resp.status_code == 200
    body = resp.json()
    assert body["id"] == "depot"
    assert "location" in body and "lat" in body["location"]


def test_seed_and_reset_roundtrip(client):
    # mutate, then reseed
    client.delete("/orders/o1")
    seeded = client.post("/seed")
    assert seeded.status_code == 200
    assert len(seeded.json()["orders"]) == 15
    client.delete("/orders/o1")
    reset = client.post("/reset")
    assert reset.status_code == 200
    assert len(reset.json()["orders"]) == 15


def test_list_vehicles_and_orders(client):
    assert len(client.get("/vehicles").json()) == 4
    assert len(client.get("/orders").json()) == 15


def test_get_vehicle_and_404(client):
    ok = client.get("/vehicles/v1")
    assert ok.status_code == 200 and ok.json()["name"] == "Truck 01"
    assert client.get("/vehicles/nope").status_code == 404


def test_get_order_and_404(client):
    ok = client.get("/orders/o1")
    assert ok.status_code == 200 and ok.json()["label"] == "A"
    assert client.get("/orders/nope").status_code == 404


def test_create_vehicle(client):
    resp = client.post(
        "/vehicles",
        json={"name": "Zippy", "driver": "Sam", "type": "BIKE", "capacityWeight": 50, "speedKmh": 25},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Zippy"
    assert body["type"] == "BIKE"
    assert body["capacityVolume"] == 20  # BIKE meta
    # it is now retrievable
    assert client.get(f"/vehicles/{body['id']}").status_code == 200
    assert len(client.get("/vehicles").json()) == 5


def test_update_vehicle_and_404(client):
    resp = client.patch("/vehicles/v1", json={"driver": "Neo", "speedKmh": 55})
    assert resp.status_code == 200
    body = resp.json()
    assert body["driver"] == "Neo" and body["speedKmh"] == 55
    assert client.patch("/vehicles/nope", json={"driver": "x"}).status_code == 404


def test_delete_vehicle_and_404(client):
    assert client.delete("/vehicles/v4").status_code == 204
    assert client.get("/vehicles/v4").status_code == 404
    assert len(client.get("/vehicles").json()) == 3
    assert client.delete("/vehicles/v4").status_code == 404


def test_create_order(client):
    resp = client.post(
        "/orders",
        json={
            "address": "Custom",
            "lat": 12.95,
            "lng": 77.62,
            "weight": 40.0,
            "priority": 3,
            "windowStart": 520,
            "windowEnd": 640,
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["address"] == "Custom" and body["priority"] == 3
    assert body["status"] == "PENDING"
    assert len(client.get("/orders").json()) == 16


def test_update_order_and_404(client):
    resp = client.patch("/orders/o1", json={"weight": 160.0, "priority": 4})
    assert resp.status_code == 200
    body = resp.json()
    assert body["weight"] == 160.0 and body["priority"] == 4
    assert client.patch("/orders/nope", json={"weight": 1.0}).status_code == 404


def test_delete_order_and_404(client):
    assert client.delete("/orders/o1").status_code == 204
    assert client.get("/orders/o1").status_code == 404
    assert client.delete("/orders/o1").status_code == 404


def test_set_vehicle_position(client):
    resp = client.post("/vehicles/v1/position", json={"lat": 13.05, "lng": 77.6, "progress": 0.5})
    assert resp.status_code == 200
    body = resp.json()
    assert body["location"]["lat"] == 13.05 and body["location"]["lng"] == 77.6
    assert body["progress"] == 0.5
    assert client.post("/vehicles/nope/position", json={"lat": 1.0, "lng": 2.0}).status_code == 404


def test_optimize_endpoint_serves_all(client):
    resp = client.post("/optimize")
    assert resp.status_code == 200
    body = resp.json()
    assert body["metrics"]["dropped"] == 0
    assigned = [o for o in body["orders"] if o["status"] == "ASSIGNED"]
    assert len(assigned) == 15
    assert body["plan"]  # non-empty


def test_reoptimize_endpoint(client):
    client.post("/optimize")
    resp = client.post("/reoptimize")
    assert resp.status_code == 200
    body = resp.json()
    assert body["metrics"]["reoptMs"] < 5000


def test_state_exposes_baseline_after_optimize(client):
    # Null before the first solve; the frozen 08:00 baseline appears after it.
    assert client.get("/state").json()["baseline"] is None
    client.post("/optimize")
    baseline = client.get("/state").json()["baseline"]
    assert baseline is not None
    # Full camelCase Metrics shape (scored by the same code as live metrics).
    for key in (
        "totalDistanceKm",
        "totalTimeMin",
        "lateDeliveries",
        "routeChanges",
        "utilizationPct",
        "reoptMs",
        "dropped",
    ):
        assert key in baseline
    # A real projection, not zeros: distance covered and makespan inside the day.
    assert baseline["totalDistanceKm"] > 0
    assert 480 <= baseline["totalTimeMin"] <= 1080
    # The static projection never re-optimizes, so these are fixed at zero.
    assert baseline["routeChanges"] == 0
    assert baseline["reoptMs"] == 0.0


def test_events_endpoint_traffic(client):
    resp = client.post("/events", json={"type": "TRAFFIC"})
    assert resp.status_code == 200
    evt = resp.json()
    assert evt["type"] == "TRAFFIC"
    for key in ("reoptMs", "routeChanges", "affectedVehicles", "reassignments"):
        assert key in evt
    # the world reflects the congestion bump
    assert client.get("/state").json()["trafficFactor"] == 1.6


def test_events_endpoint_unknown_type_is_400(client):
    resp = client.post("/events", json={"type": "NOPE"})
    assert resp.status_code == 400


def test_events_endpoint_new_order_appears_in_state(client):
    before = len(client.get("/state").json()["orders"])
    resp = client.post("/events", json={"type": "NEW_ORDER", "payload": {"weight": 30.0}})
    assert resp.status_code == 200
    assert resp.json()["type"] == "NEW_ORDER"
    after = len(client.get("/state").json()["orders"])
    assert after == before + 1
