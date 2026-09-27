import { create } from "zustand";
import type {
  Depot,
  Vehicle,
  Order,
  Plan,
  Metrics,
  WorldEvent,
  EventType,
  OrderStatus,
  VehicleStatus,
  Priority,
  VehicleType,
  Section,
} from "../lib/types";
import { DEPOT, DAY_START } from "../mock/seed";
import { api, type WorldSnapshot } from "../lib/api";
import { getSocket } from "../lib/socket";

// Form payloads the management panels hand to the CRUD actions.
export interface VehicleDraft {
  name: string;
  driver: string;
  type: VehicleType;
  capacityWeight: number;
  speedKmh: number;
}

export interface OrderDraft {
  address: string;
  lat: number;
  lng: number;
  weight: number;
  priority: Priority;
  windowStart: number;
  windowEnd: number;
}

// Shape of a single vehicle inside a vehicle:move frame.
interface VehicleMovePos {
  id: string;
  location: { lat: number; lng: number };
  progress: number;
  status: VehicleStatus;
}

interface VehicleMove {
  simTime: number;
  vehicles: VehicleMovePos[];
  completed: string[];
  running: boolean;
}

interface WorldState {
  depot: Depot;
  vehicles: Vehicle[];
  orders: Order[];
  plan: Plan;
  metrics: Metrics | null;

  // Snapshot of the initial 08:00 world — the "no re-optimization" baseline
  // that projectStatic() replays for the before/after comparison. Captured once
  // from the first non-empty plan the backend broadcasts.
  initialPlan: Plan;
  initialVehicles: Vehicle[];

  simTime: number;
  running: boolean;
  speed: number; // sim minutes advanced per backend tick
  trafficFactor: number;
  events: WorldEvent[];
  selectedId: string | null;

  // Dashboard shell state.
  activeSection: Section;
  focusVehicleId: string | null; // map: show one driver's route, null = all

  init: () => void;
  reset: () => void;
  play: () => void;
  pause: () => void;
  setSpeed: (s: number) => void;
  tick: () => void; // no-op — the backend now drives the sim clock
  reoptimize: () => void;
  select: (id: string | null) => void;
  setSection: (s: Section) => void;
  setFocus: (id: string | null) => void;

  // Event simulator (disruptions — these emit a WorldEvent on the backend).
  fireEvent: (type: EventType) => void;
  cancelOrder: (id: string) => void;
  toggleBreakdown: (id: string) => void;

  // Management (CRUD — the backend mutates the catalog and broadcasts state).
  addVehicle: (draft: VehicleDraft) => void;
  updateVehicle: (id: string, patch: Partial<VehicleDraft>) => void;
  deleteVehicle: (id: string) => void;
  addOrder: (draft: OrderDraft) => void;
  updateOrder: (id: string, patch: Partial<OrderDraft>) => void;
  deleteOrder: (id: string) => void;
}

// Registered exactly once (init may run twice under React strict-mode remounts).
let socketBound = false;

function logError(label: string) {
  return (err: unknown) => console.error(`[DaakFlow] ${label} failed`, err);
}

export const useWorldStore = create<WorldState>((set, get) => {
  // Deep-copy the live vehicles so the frozen baseline never aliases live state.
  const freezeVehicles = (vehicles: Vehicle[]): Vehicle[] =>
    vehicles.map((v) => ({ ...v, location: { ...v.location }, home: { ...v.home } }));

  // Mirror a full backend snapshot into the store. The backend keeps events
  // oldest-first; the UI feed wants newest-first, so we reverse. The 08:00
  // baseline is captured from the first non-empty plan we ever see.
  const applySnapshot = (snap: WorldSnapshot) => {
    set((s) => {
      const incomingPlan = snap.plan ?? {};
      const capture =
        Object.keys(s.initialPlan).length === 0 && Object.keys(incomingPlan).length > 0;
      return {
        depot: snap.depot,
        vehicles: snap.vehicles,
        orders: snap.orders,
        plan: incomingPlan,
        metrics: snap.metrics ?? null,
        simTime: snap.simTime,
        trafficFactor: snap.trafficFactor,
        running: snap.running,
        speed: snap.speed,
        events: [...(snap.events ?? [])].reverse(),
        ...(capture
          ? { initialPlan: incomingPlan, initialVehicles: freezeVehicles(snap.vehicles) }
          : {}),
      };
    });
  };

  // Wire the socket broadcast listeners exactly once.
  const bindSocket = () => {
    if (socketBound) return;
    socketBound = true;
    const socket = getSocket();

    socket.on("state:update", (snap: WorldSnapshot) => applySnapshot(snap));

    socket.on("vehicle:move", (data: VehicleMove) => {
      set((s) => {
        const posById: Record<string, VehicleMovePos> = {};
        for (const v of data.vehicles) posById[v.id] = v;
        const completed = new Set(data.completed);
        return {
          simTime: data.simTime,
          running: data.running,
          vehicles: s.vehicles.map((v) => {
            const p = posById[v.id];
            return p
              ? {
                  ...v,
                  location: { lat: p.location.lat, lng: p.location.lng },
                  progress: p.progress,
                  status: p.status,
                }
              : v;
          }),
          orders: completed.size
            ? s.orders.map((o) =>
                completed.has(o.id)
                  ? { ...o, status: "COMPLETED" as OrderStatus, eta: data.simTime }
                  : o,
              )
            : s.orders,
        };
      });
    });

    socket.on("plan:changed", (data: { plan: Plan; metrics: Metrics | null }) => {
      set({ plan: data.plan ?? {}, metrics: data.metrics ?? null });
    });

    socket.on("event:applied", (evt: WorldEvent) => {
      // Prepend newest-first, de-duped by id (a trailing state:update also
      // carries this event, reversed to the front — this avoids a double entry).
      set((s) => (s.events.some((e) => e.id === evt.id) ? {} : { events: [evt, ...s.events] }));
    });
  };

  // Load current world over REST, cold-solving once if the backend has no plan
  // yet. state:update also arrives over the socket on connect; both are
  // idempotent, and whichever brings the first plan captures the baseline.
  const bootstrap = async () => {
    try {
      let snap = await api.getState();
      if (!snap.plan || Object.keys(snap.plan).length === 0) {
        snap = await api.optimize();
      }
      applySnapshot(snap);
    } catch (err) {
      logError("init")(err);
    }
  };

  return {
    depot: DEPOT,
    vehicles: [],
    orders: [],
    plan: {},
    metrics: null,
    initialPlan: {},
    initialVehicles: [],
    simTime: DAY_START,
    running: false,
    speed: 3,
    trafficFactor: 1,
    events: [],
    selectedId: null,
    activeSection: "overview",
    focusVehicleId: null,

    init: () => {
      bindSocket();
      void bootstrap();
    },

    reset: () => {
      // Clear the captured baseline so the fresh cold solve re-captures it.
      set({ initialPlan: {}, initialVehicles: [] });
      void (async () => {
        try {
          await api.reset();
          applySnapshot(await api.optimize());
        } catch (err) {
          logError("reset")(err);
        }
      })();
    },

    play: () => {
      set({ running: true }); // optimistic — backend confirms via broadcast
      void api.simPlay().catch(logError("play"));
    },
    pause: () => {
      set({ running: false });
      void api.simPause().catch(logError("pause"));
    },
    setSpeed: (s) => {
      set({ speed: s });
      void api.simSpeed(s).catch(logError("setSpeed"));
    },

    tick: () => {
      // No-op: the backend Simulator now owns the clock and streams vehicle:move.
    },

    reoptimize: () => {
      void api.reoptimize().catch(logError("reoptimize"));
    },

    select: (id) => set({ selectedId: id }),
    setSection: (section) => set({ activeSection: section }),
    setFocus: (id) => set({ focusVehicleId: id }),

    fireEvent: (type) => {
      void api.fireEvent(type).catch(logError("fireEvent"));
    },

    cancelOrder: (id) => {
      const target = get().orders.find((o) => o.id === id);
      if (!target || target.status === "COMPLETED" || target.status === "CANCELLED") return;
      void api.fireEvent("CANCELLATION", { orderId: id }).catch(logError("cancelOrder"));
    },

    toggleBreakdown: (id) => {
      const target = get().vehicles.find((v) => v.id === id);
      if (!target) return;
      if (target.status !== "BROKEN") {
        void api.fireEvent("BREAKDOWN", { vehicleId: id }).catch(logError("toggleBreakdown"));
      } else {
        // Restore: reactivate the vehicle, then re-optimize so freed capacity is
        // folded back in (CRUD alone does not re-solve on the backend).
        void (async () => {
          try {
            await api.updateVehicle(id, { status: "ACTIVE", driverAvailable: true });
            await api.reoptimize();
          } catch (err) {
            logError("toggleBreakdown")(err);
          }
        })();
      }
    },

    addVehicle: (draft) => {
      void api.createVehicle(draft).catch(logError("addVehicle"));
    },
    updateVehicle: (id, patch) => {
      void api.updateVehicle(id, patch).catch(logError("updateVehicle"));
    },
    deleteVehicle: (id) => {
      if (get().focusVehicleId === id) set({ focusVehicleId: null });
      void api.deleteVehicle(id).catch(logError("deleteVehicle"));
    },

    addOrder: (draft) => {
      void api.createOrder(draft).catch(logError("addOrder"));
    },
    updateOrder: (id, patch) => {
      void api.updateOrder(id, patch).catch(logError("updateOrder"));
    },
    deleteOrder: (id) => {
      if (get().selectedId === id) set({ selectedId: null });
      void api.deleteOrder(id).catch(logError("deleteOrder"));
    },
  };
});
