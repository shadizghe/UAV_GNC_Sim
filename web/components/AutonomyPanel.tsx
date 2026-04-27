"use client";

import {
  Activity,
  Cpu,
  Play,
  Power,
  Radar,
  Route,
  ShieldAlert,
  Target,
} from "lucide-react";
import type { ReactNode } from "react";
import { useMemo } from "react";
import { useAppStore } from "@/lib/store";
import type { RerouteEvent, Vec3 } from "@/lib/types";
import { cn } from "@/lib/utils";

const fmt = (value: number, digits = 2) => value.toFixed(digits);

function fmtVec(point: Vec3 | undefined) {
  if (!point) return "--";
  return `${fmt(point[0], 1)}, ${fmt(point[1], 1)}, ${fmt(point[2], 1)}`;
}

export function AutonomyPanel() {
  const currentPreset = useAppStore((state) => state.currentPreset);
  const simResult = useAppStore((state) => state.simResult);
  const simRunning = useAppStore((state) => state.simRunning);
  const enableReplanning = useAppStore((state) => state.enableReplanning);
  const setEnableReplanning = useAppStore((state) => state.setEnableReplanning);
  const runSimulation = useAppStore((state) => state.runSimulation);

  const events = simResult?.reroute_events ?? [];
  const latest = events[events.length - 1];
  const threatSourceCount = (currentPreset?.enemies.length ?? 0)
    + (currentPreset?.zones.filter((zone) => zone.kind === "threat" || zone.kind === "no_fly").length ?? 0);
  const dt = simResult?.t.length && simResult.t.length > 1
    ? simResult.t[1] - simResult.t[0]
    : 0;
  const rerouteTime = (simResult?.reroute_active ?? []).filter(Boolean).length * dt;
  const bestClearance = useMemo(() => {
    if (events.length === 0) return null;
    return Math.min(...events.map((event) => event.clearance_score));
  }, [events]);
  const status = !enableReplanning
    ? "Standby"
    : simRunning
      ? "Computing"
      : events.length > 0
        ? "Contact logged"
        : "Armed";

  if (!currentPreset) return null;

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <header className="flex items-center gap-2">
          <span className="h-5 w-1 rounded-sm bg-green" />
          <div>
            <h2 className="text-[0.74rem] font-semibold uppercase tracking-[0.18em] text-green">
              Autonomy
            </h2>
            <p className="mt-0.5 text-xs text-muted">
              Threat-aware replanning state
            </p>
          </div>
        </header>
        <Cpu className="h-4 w-4 text-green" />
      </div>

      <section className="panel p-3 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div>
            <div className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-green">
              Replanning
            </div>
            <div className="mt-1 flex flex-wrap gap-1.5">
              <span className={enableReplanning ? "pill-green" : "pill-amber"}>
                {status}
              </span>
              <span className="pill-cyan">{threatSourceCount} sources</span>
            </div>
          </div>
          <button
            type="button"
            role="switch"
            aria-checked={enableReplanning}
            onClick={() => setEnableReplanning(!enableReplanning)}
            className={cn(
              "grid h-10 w-10 shrink-0 place-items-center rounded-md border transition-colors",
              enableReplanning
                ? "border-green/40 bg-green/15 text-green hover:bg-green/20"
                : "border-amber/35 bg-amber/10 text-amber hover:bg-amber/15",
            )}
            title={enableReplanning ? "Disable replanning" : "Enable replanning"}
          >
            <Power className="h-4 w-4" />
          </button>
        </div>

        <div className="grid grid-cols-2 gap-2">
          <StatCard icon={<Radar />} label="Events" value={events.length.toString()} tone="green" />
          <StatCard icon={<Activity />} label="Active time" value={`${fmt(rerouteTime, 2)} s`} tone="cyan" />
          <StatCard icon={<ShieldAlert />} label="Latest threat" value={latest?.threat_name ?? "--"} tone="amber" />
          <StatCard
            icon={<Target />}
            label="Clearance"
            value={bestClearance === null ? "--" : `${fmt(bestClearance, 2)} m`}
            tone={bestClearance !== null && bestClearance < 0 ? "red" : "green"}
          />
        </div>

        <div className="panel-soft px-3 py-2 text-xs">
          <div className="mb-1 flex items-center gap-2 text-[0.66rem] font-semibold uppercase tracking-[0.18em] text-muted">
            <Route className="h-3.5 w-3.5 text-green" />
            Current Route
          </div>
          <div className="grid grid-cols-2 gap-2 font-mono text-[0.68rem]">
            <Readout label="Original target" value={fmtVec(latest?.original_target)} />
            <Readout label="Inserted waypoint" value={fmtVec(latest?.inserted_waypoint)} />
            <Readout
              label="Planner cost"
              value={latest?.planner_cost === undefined ? "--" : fmt(latest.planner_cost, 1)}
            />
            <Readout
              label="Route legs"
              value={latest?.inserted_waypoints?.length ? latest.inserted_waypoints.length.toString() : "--"}
            />
          </div>
        </div>

        <button
          type="button"
          onClick={runSimulation}
          disabled={simRunning}
          className="flex h-9 w-full items-center justify-center gap-2 rounded-md border border-green/35 bg-green/10 px-3 text-xs font-semibold uppercase tracking-wider text-green transition-colors hover:bg-green/15 disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Play className="h-3.5 w-3.5" />
          {simRunning ? "Running" : "Run Autonomy"}
        </button>
      </section>

      <section className="space-y-2">
        <div className="flex items-center justify-between px-1">
          <div className="flex items-center gap-2 text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted">
            <ShieldAlert className="h-3.5 w-3.5 text-amber" />
            Contact Log
          </div>
          <span className="font-mono text-xs text-green">{events.length}</span>
        </div>
        <div className="grid gap-2">
          {events.length === 0 ? (
            <div className="panel-soft px-3 py-3 text-xs text-muted">
              No reroute events in the latest run.
            </div>
          ) : (
            events.slice(-5).reverse().map((event, index) => (
              <EventRow key={`${event.frame}-${event.threat_name}-${index}`} event={event} />
            ))
          )}
        </div>
      </section>
    </section>
  );
}

function StatCard({
  icon,
  label,
  value,
  tone,
}: {
  icon: ReactNode;
  label: string;
  value: string;
  tone: "cyan" | "green" | "amber" | "red";
}) {
  const toneClass = {
    cyan: "text-cyan border-cyan/15 bg-cyan/[0.04]",
    green: "text-green border-green/15 bg-green/[0.04]",
    amber: "text-amber border-amber/15 bg-amber/[0.04]",
    red: "text-red border-red/15 bg-red/[0.04]",
  }[tone];

  return (
    <div className={cn("rounded-md border px-3 py-2", toneClass)}>
      <div className="flex items-center gap-1.5 text-[0.62rem] uppercase tracking-widest opacity-80">
        <span className="[&_svg]:h-3.5 [&_svg]:w-3.5">{icon}</span>
        {label}
      </div>
      <div className="mt-1 truncate font-mono text-sm text-text">{value}</div>
    </div>
  );
}

function Readout({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[0.6rem] uppercase tracking-widest text-muted">{label}</div>
      <div className="mt-0.5 truncate text-text">{value}</div>
    </div>
  );
}

function EventRow({ event }: { event: RerouteEvent }) {
  return (
    <div className="panel-soft space-y-2 px-3 py-3 text-xs">
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="font-semibold text-amber">{event.message}</div>
          <div className="mt-0.5 font-mono text-[0.68rem] text-muted">
            t {fmt(event.t, 2)} s | frame {event.frame}
          </div>
        </div>
        <span className="pill-red">{event.threat_kind}</span>
      </div>
      <div className="grid grid-cols-2 gap-2 font-mono text-[0.68rem]">
        <Readout label="Threat" value={event.threat_name} />
        <Readout label="Waypoint" value={`WPT-${event.waypoint_index + 1}`} />
        <Readout label="Envelope" value={`${fmt(event.envelope_radius, 2)} m`} />
        <Readout label="Inserted" value={fmtVec(event.inserted_waypoint)} />
        <Readout
          label="Nodes"
          value={event.nodes_expanded === undefined ? "--" : event.nodes_expanded.toString()}
        />
        <Readout
          label="Cost"
          value={event.planner_cost === undefined ? "--" : fmt(event.planner_cost, 1)}
        />
      </div>
    </div>
  );
}
