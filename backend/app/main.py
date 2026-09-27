"""DaakFlow backend — FastAPI application.

Phases 4-6 built the data models, CRUD, optimizer, and disruption handlers. This
module now also mounts the **Phase 7 realtime layer**: a Socket.IO server (ASGI)
that broadcasts live world state, and a background :class:`Simulator` that
advances the sim clock and streams vehicle motion. REST stays the command surface
(including the new ``/sim/*`` controls); Socket.IO is broadcast-only.

The in-memory ``WorldState`` is the live source of truth; the durable catalog is
mirrored to Neon Postgres when reachable.

NOTE: every endpoint below is UNAUTHENTICATED, and the Socket.IO server accepts
any client from the CORS allow-list — this is a local demo API. Add auth before
exposing it beyond localhost.

Serving note: ``app`` is the plain FastAPI instance (used directly by the test
suite's TestClient); ``asgi`` is that app wrapped with Socket.IO. Uvicorn must
serve the wrapped app, e.g. ``uvicorn app.main:asgi --reload``.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import Optional

import socketio
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .db import db
from .events import apply_event
from .models import (
    Depot,
    EventRequest,
    Order,
    OrderCreate,
    OrderUpdate,
    SpeedRequest,
    Vehicle,
    VehicleCreate,
    VehiclePosition,
    VehicleUpdate,
    WorldEvent,
    WorldSnapshot,
)
from .optimizer import optimize
from .reoptimize import reoptimize
from .simulation import Simulator
from .state import world

# Browser origins allowed for both the FastAPI CORS middleware and the
# Socket.IO server. Defaults to the local dev frontend; override for production
# via the CORS_ORIGINS env var (comma-separated). Because allow_credentials is
# True, "*" is not a valid entry — list explicit origins.
CORS_ORIGINS = settings.cors_origin_list

# --------------------------------------------------------------------------- #
# Realtime layer (Phase 7) — Socket.IO broadcast + background simulator
# --------------------------------------------------------------------------- #
sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins=CORS_ORIGINS)
simulator = Simulator(world, sio)

# The event loop captured at startup so the *synchronous* FastAPI route handlers
# (which Starlette runs in a threadpool) can schedule broadcasts back onto it.
_loop: Optional[asyncio.AbstractEventLoop] = None


@sio.event
async def connect(sid, environ, auth=None):
    """On connect, hand the new client the full current world state."""
    await sio.emit("state:update", world.snapshot().model_dump(by_alias=True), to=sid)


def _emit(event: str, data) -> None:
    """Fire-and-forget a Socket.IO broadcast from a sync request handler.

    Schedules the coroutine onto the running loop captured at startup; routes
    never block on delivery. A no-op if no loop is available (import time or the
    shutdown window), so it is always safe to call.
    """
    loop = _loop
    if loop is None:
        return
    try:
        asyncio.run_coroutine_threadsafe(sio.emit(event, data), loop)
    except RuntimeError:
        pass


def broadcast_state() -> None:
    """Broadcast the full ``WorldSnapshot`` to every client."""
    _emit("state:update", world.snapshot().model_dump(by_alias=True))


def broadcast_plan_changed() -> None:
    """Broadcast ``plan:changed`` (plan + metrics + baseline) after any re-solve."""
    dumped = world.snapshot().model_dump(by_alias=True)
    _emit(
        "plan:changed",
        {
            "plan": dumped["plan"],
            "metrics": dumped["metrics"],
            "baseline": dumped["baseline"],
        },
    )


def broadcast_event(evt: WorldEvent) -> None:
    """Broadcast ``event:applied`` (the recorded disruption) to every client."""
    _emit("event:applied", evt.model_dump(by_alias=True))


def _seed_everything() -> None:
    """Restore the mock scenario in memory and mirror it to the catalog."""
    world.seed()
    if db.enabled:
        db.reseed(world.depot, world.vehicles, world.orders)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _loop
    _loop = asyncio.get_running_loop()
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
    simulator.start()  # inert until world.running is set via /sim/play
    yield
    simulator.stop()
    _loop = None


app = FastAPI(title="DaakFlow API", version="0.7.0", lifespan=lifespan)

# ASGI app that serves both Socket.IO and the FastAPI routes. Uvicorn entrypoint.
asgi = socketio.ASGIApp(sio, other_asgi_app=app)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
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
    broadcast_state()
    return world.snapshot()


@app.post("/reset", response_model=WorldSnapshot)
def reset_world() -> WorldSnapshot:
    _seed_everything()
    broadcast_state()
    return world.snapshot()


# --------------------------------------------------------------------------- #
# Simulation controls (Phase 7) — commands are REST; sockets broadcast only
# --------------------------------------------------------------------------- #
@app.post("/sim/play", response_model=WorldSnapshot)
def sim_play() -> WorldSnapshot:
    """Start (or resume) the sim clock. The background loop then advances the
    world every tick and streams ``vehicle:move`` frames."""
    with world._lock:
        world.running = world.sim_time < 1080  # don't "run" a finished day
    simulator.start()  # ensure the loop exists (idempotent)
    broadcast_state()
    return world.snapshot()


@app.post("/sim/pause", response_model=WorldSnapshot)
def sim_pause() -> WorldSnapshot:
    """Pause the sim clock (the loop keeps spinning but advances nothing)."""
    with world._lock:
        world.running = False
    broadcast_state()
    return world.snapshot()


@app.post("/sim/speed", response_model=WorldSnapshot)
def sim_speed(req: SpeedRequest) -> WorldSnapshot:
    """Set how many sim-minutes each real tick advances."""
    with world._lock:
        world.speed = req.speed
    broadcast_state()
    return world.snapshot()


# --------------------------------------------------------------------------- #
# Optimization (Phase 5 — initial route solve)
# --------------------------------------------------------------------------- #
@app.post("/optimize", response_model=WorldSnapshot)
def optimize_routes() -> WorldSnapshot:
    """Run the initial OR-Tools solve, persist the plan / order assignments /
    metrics into the live world, and return the updated snapshot.

    If the solver finds no feasible plan the world is left untouched and a 422 is
    returned instead of crashing.
    """
    result = optimize(world)
    if result.status == "infeasible":
        raise HTTPException(status_code=422, detail=result.message)
    broadcast_plan_changed()
    broadcast_state()
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
    broadcast_plan_changed()
    broadcast_state()
    return world.snapshot()


@app.post("/events", response_model=WorldEvent)
def fire_event(req: EventRequest) -> WorldEvent:
    """Apply a disruption (matching the frontend's event-console types), which
    mutates the world, re-optimizes the tail, and returns the recorded
    ``WorldEvent`` (real reopt_ms / route_changes / reassignments / affected
    lists). An unknown event ``type`` yields a 400.
    """
    try:
        evt = apply_event(world, req.type, req.payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    broadcast_event(evt)
    broadcast_plan_changed()
    broadcast_state()
    return evt


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
    broadcast_state()
    return veh


@app.patch("/vehicles/{vehicle_id}", response_model=Vehicle)
@app.put("/vehicles/{vehicle_id}", response_model=Vehicle)
def update_vehicle(vehicle_id: str, patch: VehicleUpdate) -> Vehicle:
    veh = world.update_vehicle(vehicle_id, patch)
    if veh is None:
        raise HTTPException(status_code=404, detail="vehicle not found")
    db.upsert_vehicle(veh)
    broadcast_state()
    return veh


@app.delete("/vehicles/{vehicle_id}", status_code=204)
def delete_vehicle(vehicle_id: str) -> Response:
    if not world.delete_vehicle(vehicle_id):
        raise HTTPException(status_code=404, detail="vehicle not found")
    db.delete_vehicle(vehicle_id)
    broadcast_state()
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
    broadcast_state()
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
    broadcast_state()
    return order


@app.patch("/orders/{order_id}", response_model=Order)
@app.put("/orders/{order_id}", response_model=Order)
def update_order(order_id: str, patch: OrderUpdate) -> Order:
    order = world.update_order(order_id, patch)
    if order is None:
        raise HTTPException(status_code=404, detail="order not found")
    db.upsert_order(order)
    broadcast_state()
    return order


@app.delete("/orders/{order_id}", status_code=204)
def delete_order(order_id: str) -> Response:
    if not world.delete_order(order_id):
        raise HTTPException(status_code=404, detail="order not found")
    db.delete_order(order_id)
    broadcast_state()
    return Response(status_code=204)
