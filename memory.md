# DaakFlow — Project Memory

**DaakFlow** is an Adaptive Delivery Routing System built for a hackathon ("bitnbuild"). The app name is **DaakFlow** — never "FleetView".

## 1. What the product does

DaakFlow plans and continuously re-plans last-mile delivery routes for a fleet operating out of a single Bengaluru depot. The headline capability is **Dynamic Re-Optimization**: when the world changes mid-day (new order, breakdown, traffic surge, cancellation, time-window or address change) it does NOT re-solve from scratch. It freezes what is already settled and re-solves only the open tail:

- `COMPLETED` / `CANCELLED` / `DROPPED` orders are never touched.
- `IN_PROGRESS` orders are pinned as the locked first stop on their current vehicle.
- Each vehicle re-enters the model at its live position.
- Only `PENDING` / `ASSIGNED` (unvisited) stops are free to move.

This commitment-respecting re-solve is the core differentiator versus a naive routing demo, and it drives the before/after comparison view.

## 2. Tech stack (as built)

- **Framework:** Next.js 16 (App Router, Turbopack) + React 19 + TypeScript.
- **Styling:** Tailwind CSS v4 (`@import "tailwindcss"; @theme` tokens — `ink/muted/faint`, `surface`/`surface2`/`surface3`, `line`/`line2`, `brand`/`brand2`, `live`). No shadcn/ui.
- **State:** Zustand — a single `useWorldStore`.
- **Map:** Leaflet + react-leaflet (dynamic import, `ssr: false`); CARTO Voyager light raster tiles (OSM fallback). Inline-SVG icon set. Geist Sans / Geist Mono.
- **Optimizer:** client-side TypeScript (`lib/optimizer.ts`) — greedy cheapest-insertion, soft lateness penalty (`cost = addDist + late*2`), capacity-gated, drops only on capacity exhaustion. Stands in for the planned OR-Tools backend.

### Stack drift vs implementation_plan.md §0
The plan specified Next.js **14** + **shadcn/ui** + **Recharts** + **Socket.IO** + a **Python / FastAPI / OR-Tools** backend as the source of truth. The actual build is Next.js **16** + Tailwind v4 (no shadcn) + Zustand + a **client-side TS optimizer** substituting for OR-Tools. Recharts is being removed (Task E). No backend exists yet.

## 3. Repository layout

```
frontend/src/
  app/          layout.tsx (fonts, metadata), page.tsx (renders Dashboard)
  components/   Dashboard, Sidebar, Topbar, MapView, MapOverlay,
                OverviewPanel, OrderPanel, DriverPanel, EventConsole,
                BeforeAfterPanel, icons
  lib/          types.ts, optimizer.ts, geo.ts, palette.ts
  mock/         seed.ts (depot + 4 vehicles + 15 orders A-O)
  store/        useWorldStore.ts (single Zustand store)
```

## 4. Data model (`lib/types.ts`)

- `LatLng` = `{ lat, lng }`.
- `Priority` = `1 | 2 | 3 | 4` (4 = critical).
- `OrderStatus` = `PENDING | ASSIGNED | IN_PROGRESS | COMPLETED | CANCELLED | DROPPED`.
- `Order` — id, label, location, address, windowStart, windowEnd (min from midnight), weight (kg), volume, priority, status, assignedVehicle, seqIndex, eta, createdAt.
- `VehicleStatus` = `ACTIVE | BROKEN | IDLE`; `VehicleType` = `TRUCK | VAN | BIKE`.
- `Vehicle` — id, name, type, color, location (live), home (depot), capacityWeight, capacityVolume, speedKmh, status, driver, driverAvailable, shiftStart, shiftEnd, progress (0..1 leg animation).
- `Depot` — id, name, location.
- `RouteStop` — orderId, seq, eta, locked.
- `Plan` = `Record<vehicleId, RouteStop[]>`.
- `Section` = `overview | orders | drivers | simulator | compare`.
- `Metrics` — totalDistanceKm, totalTimeMin, lateDeliveries, routeChanges, utilizationPct, reoptMs, dropped.
- `EventType` = NEW_ORDER | PRIORITY_ORDER | BREAKDOWN | TRAFFIC | CANCELLATION | TIME_CHANGE | ADDRESS_CHANGE.
- `Reassignment` — orderId, label, from (vehicle|null), to (vehicle|null); null `to` = dropped.
- `WorldEvent` — id, type, description, simTime, affectedVehicles, affectedOrders, reoptMs, routeChanges, reassignments.

<!-- __CHUNK__ -->
