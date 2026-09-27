"""Simulation clock + live position broadcast (Phase 7).

A single :class:`Simulator` owns an asyncio loop that, while the world is
``running``, advances ``sim_time`` and interpolates every active vehicle toward
its next stop, marking orders delivered on arrival and emitting a ``vehicle:move``
frame each tick over Socket.IO. The per-tick advance mirrors the frontend's old
client-side ``useWorldStore.tick()`` *exactly* (same budget formula, same stop
walk, same lerp) so the cutover is behaviour-preserving — only now the backend is
the single source of truth and the browser just renders what it broadcasts.

The loop is inert until ``world.running`` is set (via ``POST /sim/play``), so it
is safe to start unconditionally at app startup (and during tests).
"""

from __future__ import annotations

import asyncio
from typing import Optional

import socketio

from .distances import road_km
from .models import LatLng, OrderStatus, VehicleStatus
from .state import DAY_END, WorldState

# Real milliseconds between simulation ticks. Each tick advances the sim clock by
# ``world.speed`` sim-minutes, so wall-clock pacing is TICK_MS and sim pacing is
# world.speed — exactly the cadence the frontend used to drive locally.
TICK_MS = 500

# Terminal order states a tick must never touch (mirror of the frontend guard).
_TERMINAL = frozenset(
    {
        OrderStatus.COMPLETED.value,
        OrderStatus.CANCELLED.value,
        OrderStatus.DROPPED.value,
    }
)


def lerp(a: LatLng, b: LatLng, t: float) -> LatLng:
    """Linear interpolation between two points, ``t`` in [0, 1] (mirror of the
    frontend ``geo.ts`` ``lerp``)."""
    return LatLng(lat=a.lat + (b.lat - a.lat) * t, lng=a.lng + (b.lng - a.lng) * t)


class Simulator:
    """Drives the sim clock and broadcasts live vehicle motion over Socket.IO."""

    def __init__(self, world: WorldState, sio: socketio.AsyncServer) -> None:
        self.world = world
        self.sio = sio
        self._task: Optional[asyncio.Task] = None

    # -- lifecycle ---------------------------------------------------------- #
    def start(self) -> None:
        """Create the background tick task (idempotent)."""
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self.run())

    def stop(self) -> None:
        """Cancel the background tick task if running."""
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def run(self) -> None:
        """Tick forever: every ``TICK_MS`` advance the world (only while it is
        ``running``) and broadcast the resulting positions."""
        try:
            while True:
                await asyncio.sleep(TICK_MS / 1000)
                if not self.world.running:
                    continue
                payload, reached_end = self._advance()
                await self.sio.emit("vehicle:move", payload)
                if reached_end:
                    # Day is over: push one authoritative full snapshot so every
                    # client settles on the final state (running now False).
                    await self.sio.emit(
                        "state:update", self.world.snapshot().model_dump(by_alias=True)
                    )
        except asyncio.CancelledError:  # graceful shutdown
            pass

    # -- one tick ----------------------------------------------------------- #
    def _advance(self) -> tuple[dict, bool]:
        """Advance the world by one tick under the world lock and build the
        ``vehicle:move`` payload. Returns ``(payload, reached_day_end)``.

        Mirrors ``useWorldStore.tick()``: for each ACTIVE + available vehicle,
        ``budget_km = speed * (speedKmh / max(1, traffic)) / 60``; walk the
        vehicle's plan stops in seq order, skipping terminal orders; flip
        ASSIGNED -> IN_PROGRESS; consume budget along each leg, snapping to the
        stop (and marking it COMPLETED with ``eta = sim_time``) when the budget
        covers it, otherwise lerp partway and stop.
        """
        world = self.world
        completed: list[str] = []
        with world._lock:
            speed = world.speed
            traffic = world.traffic_factor
            new_sim_time = min(DAY_END, world.sim_time + speed)
            by_id = {o.id: o for o in world.orders}

            for v in world.vehicles:
                if v.status != VehicleStatus.ACTIVE.value or not v.driver_available:
                    continue
                # km this vehicle can cover this tick (traffic slows it down).
                budget = speed * (v.speed_kmh / max(1, traffic)) / 60.0
                v.progress = 0.0
                for stop in sorted(world.plan.get(v.id, []), key=lambda s: s.seq):
                    o = by_id.get(stop.order_id)
                    if o is None or o.status in _TERMINAL:
                        continue
                    if o.status == OrderStatus.ASSIGNED.value:
                        o.status = OrderStatus.IN_PROGRESS.value
                    o.assigned_vehicle = v.id
                    d = road_km(v.location, o.location)
                    if budget >= d:
                        budget -= d
                        v.location = LatLng(lat=o.location.lat, lng=o.location.lng)
                        o.status = OrderStatus.COMPLETED.value
                        o.eta = new_sim_time
                        v.progress = 0.0
                        completed.append(o.id)
                    else:
                        frac = budget / d if d > 0 else 1.0
                        v.location = lerp(v.location, o.location, frac)
                        v.progress = frac
                        break

            world.sim_time = new_sim_time
            world.running = new_sim_time < DAY_END
            payload = {
                "simTime": world.sim_time,
                "vehicles": [
                    {
                        "id": v.id,
                        "location": {"lat": v.location.lat, "lng": v.location.lng},
                        "progress": v.progress,
                        "status": v.status,
                    }
                    for v in world.vehicles
                ],
                "completed": completed,
                "running": world.running,
            }
            reached_end = not world.running
        return payload, reached_end
