"""API round-trips via FastAPI TestClient (in-memory, DB neutered in conftest)."""

from __future__ import annotations


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_state_shape(client):
    r = client.get("/state")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) >= {
        "depot", "vehicles", "orders", "plan", "metrics",
        "simTime", "trafficFactor", "events",
    }
    assert body["simTime"] == 480
    assert len(body["vehicles"]) == 4
    assert len(body["orders"]) == 15
    # camelCase contract on nested entities.
    v = body["vehicles"][0]
    assert {"capacityWeight", "speedKmh", "driverAvailable", "shiftStart"} <= set(v.keys())
    o = body["orders"][0]
    assert {"windowStart", "windowEnd", "assignedVehicle", "seqIndex", "createdAt"} <= set(o.keys())
    assert o["status"] == "PENDING"


def test_order_crud_roundtrip(client):
    # create
    r = client.post("/orders", json={
        "address": "Test Stop", "lat": 12.9, "lng": 77.6, "weight": 64,
        "priority": 3, "windowStart": 500, "windowEnd": 600,
    })
    assert r.status_code == 201, r.text
    created = r.json()
    oid = created["id"]
    assert created["volume"] == 8
    assert created["status"] == "PENDING"

    # GET reflects it
    r = client.get("/state")
    assert any(o["id"] == oid for o in r.json()["orders"])
    assert client.get(f"/orders/{oid}").json()["address"] == "Test Stop"

    # update
    r = client.patch(f"/orders/{oid}", json={"weight": 80, "address": "Moved"})
    assert r.status_code == 200
    assert r.json()["weight"] == 80
    assert r.json()["volume"] == 10
    assert r.json()["address"] == "Moved"

    # delete
    assert client.delete(f"/orders/{oid}").status_code == 204
    assert client.get(f"/orders/{oid}").status_code == 404


def test_vehicle_crud_roundtrip(client):
    r = client.post("/vehicles", json={
        "name": "Bike X", "driver": "Dev", "type": "BIKE",
        "capacityWeight": 60, "speedKmh": 30,
    })
    assert r.status_code == 201, r.text
    created = r.json()
    vid = created["id"]
    assert created["capacityVolume"] == 20  # BIKE meta
    assert created["type"] == "BIKE"

    r = client.get("/state")
    assert any(v["id"] == vid for v in r.json()["vehicles"])

    r = client.patch(f"/vehicles/{vid}", json={"capacityWeight": 75, "type": "VAN"})
    assert r.status_code == 200
    assert r.json()["capacityWeight"] == 75
    assert r.json()["capacityVolume"] == 90  # VAN meta

    assert client.delete(f"/vehicles/{vid}").status_code == 204
    assert client.get(f"/vehicles/{vid}").status_code == 404


def test_reset_restores_seed(client):
    client.post("/orders", json={
        "address": "X", "lat": 12.9, "lng": 77.6, "weight": 40,
        "priority": 1, "windowStart": 500, "windowEnd": 600,
    })
    r = client.post("/reset")
    assert r.status_code == 200
    assert len(r.json()["orders"]) == 15
