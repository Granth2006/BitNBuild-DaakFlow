"""DaakFlow backend — FastAPI application (Phase 4: data models + CRUD).

No optimization/simulation here (that is Phase 5). The in-memory ``WorldState``
is the live source of truth; the durable catalog is mirrored to Neon Postgres
when reachable.

NOTE: every endpoint below is UNAUTHENTICATED — this is a local demo API. Add
auth before exposing it beyond localhost.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from .db import db
from .events import apply_event
from .models import (
    Depot,
    EventRequest,
    Order,
    OrderCreate,
    OrderUpdate,
    Vehicle,
    VehicleCreate,
    VehiclePosition,
    VehicleUpdate,
    WorldEvent,
    WorldSnapshot,
)
from .optimizer import optimize
from .reoptimize import reoptimize
from .state import world


def _seed_everything() -> None:
    """Restore the mock scenario in memory and mirror it to the catalog."""
    world.seed()
    if db.enabled:
        db.reseed(world.depot, world.vehicles, world.orders)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init()
    world.seed()
    if db.enabled:
        if db.is_empty():
            db.reseed(world.depot, world.vehicles, world.orders)
        else:
            loaded = db.load_catalog()
            if loaded:
                depot, vehicles, orders = loaded
                world.load_catalog(depot, vehicles, orders)
    app.state.db_status = db.status
    yield


app = FastAPI(title="DaakFlow API", version="0.4.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------------------------------- #
# Health / world
# --------------------------------------------------------------------------- #
@app.get("/health")
def health() -> dict:
    return {"status": "ok", "db": db.status}


@app.get("/state", response_model=WorldSnapshot)
def get_state() -> WorldSnapshot:
    return world.snapshot()


@app.get("/depot", response_model=Depot)
def get_depot() -> Depot:
    return world.depot


@app.post("/seed", response_model=WorldSnapshot)
def seed_world() -> WorldSnapshot:
    _seed_everything()
    return world.snapshot()


@app.post("/reset", response_model=WorldSnapshot)
def reset_world() -> WorldSnapshot:
    _seed_everything()
    return world.snapshot()


# --------------------------------------------------------------------------- #
# Optimization (Phase 5 — initial route solve)
# --------------------------------------------------------------------------- #
@app.post("/optimize", response_model=WorldSnapshot)
def optimize_routes() -> WorldSnapshot:
    """Run the initial OR-Tools solve, persist the plan / order assignments /
    metrics into the live world, and return the updated snapshot.

    The plan is written only into the in-memory ``WorldState`` (broadcasting is
    Phase 7). If the solver finds no feasible plan the world is left untouched
    and a 422 is returned instead of crashing.
    """
    result = optimize(world)
    if result.status == "infeasible":
        raise HTTPException(status_code=422, detail=result.message)
    return world.snapshot()


# --------------------------------------------------------------------------- #
# Dynamic re-optimization (Phase 6)
# --------------------------------------------------------------------------- #
@app.post("/reoptimize", response_model=WorldSnapshot)
def reoptimize_routes() -> WorldSnapshot:
    """Warm-started, commitment-respecting re-solve of the tail of the current
    plan (freeze COMPLETED, pin IN_PROGRESS, re-enter at live positions). Persists
    the new plan / order fields / metrics and returns the updated snapshot. On an
    infeasible solve the world is left untouched and a 422 is returned.
    """
    result = reoptimize(world)
    if result.status == "infeasible":
        raise HTTPException(status_code=422, detail=result.message)
    return world.snapshot()


@app.post("/events", response_model=WorldEvent)
def fire_event(req: EventRequest) -> WorldEvent:
    """Apply a disruption (matching the frontend's event-console types), which
    mutates the world, re-optimizes the tail, and returns the recorded
    ``WorldEvent`` (real reopt_ms / route_changes / reassignments / affected
    lists). An unknown event ``type`` yields a 400.
    """
    try:
        return apply_event(world, req.type, req.payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


# --------------------------------------------------------------------------- #
# Vehicles CRUD
# --------------------------------------------------------------------------- #
@app.get("/vehicles", response_model=list[Vehicle])
def list_vehicles() -> list[Vehicle]:
    return world.list_vehicles()


@app.get("/vehicles/{vehicle_id}", response_model=Vehicle)
def get_vehicle(vehicle_id: str) -> Vehicle:
    veh = world.get_vehicle(vehicle_id)
    if veh is None:
        raise HTTPException(status_code=404, detail="vehicle not found")
    return veh


@app.post("/vehicles", response_model=Vehicle, status_code=201)
def create_vehicle(draft: VehicleCreate) -> Vehicle:
    veh = world.add_vehicle(draft)
    db.upsert_vehicle(veh)
    return veh


@app.patch("/vehicles/{vehicle_id}", response_model=Vehicle)
@app.put("/vehicles/{vehicle_id}", response_model=Vehicle)
def update_vehicle(vehicle_id: str, patch: VehicleUpdate) -> Vehicle:
    veh = world.update_vehicle(vehicle_id, patch)
    if veh is None:
        raise HTTPException(status_code=404, detail="vehicle not found")
    db.upsert_vehicle(veh)
    return veh


@app.delete("/vehicles/{vehicle_id}", status_code=204)
def delete_vehicle(vehicle_id: str) -> Response:
    if not world.delete_vehicle(vehicle_id):
        raise HTTPException(status_code=404, detail="vehicle not found")
    db.delete_vehicle(vehicle_id)
    return Response(status_code=204)


@app.post("/vehicles/{vehicle_id}/position", response_model=Vehicle)
def set_vehicle_position(vehicle_id: str, pos: VehiclePosition) -> Vehicle:
    """Sim support: move a vehicle to its live position (and optional leg
    progress) so the next re-optimization re-enters it there, not at the depot.
    This is live in-memory state only — it is not mirrored to the catalog.
    """
    veh = world.set_vehicle_position(vehicle_id, pos.lat, pos.lng, pos.progress)
    if veh is None:
        raise HTTPException(status_code=404, detail="vehicle not found")
    return veh


# --------------------------------------------------------------------------- #
# Orders CRUD
# --------------------------------------------------------------------------- #
@app.get("/orders", response_model=list[Order])
def list_orders() -> list[Order]:
    return world.list_orders()


@app.get("/orders/{order_id}", response_model=Order)
def get_order(order_id: str) -> Order:
    order = world.get_order(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    return order


@app.post("/orders", response_model=Order, status_code=201)
def create_order(draft: OrderCreate) -> Order:
    order = world.add_order(draft)
    db.upsert_order(order)
    return order


@app.patch("/orders/{order_id}", response_model=Order)
@app.put("/orders/{order_id}", response_model=Order)
def update_order(order_id: str, patch: OrderUpdate) -> Order:
    order = world.update_order(order_id, patch)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    db.upsert_order(order)
    return order


@app.delete("/orders/{order_id}", status_code=204)
def delete_order(order_id: str) -> Response:
    if not world.delete_order(order_id):
        raise HTTPException(status_code=404, detail="order not found")
    db.delete_order(order_id)
    return Response(status_code=204)
