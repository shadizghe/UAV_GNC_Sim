"use client";

import { Copy, Crosshair, Plus, RotateCcw, Send, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import { useMemo } from "react";
import { useAppStore } from "@/lib/store";
import type { Vec3 } from "@/lib/types";
import { cn } from "@/lib/utils";

const CRUISE_SPEED_MPS = 2;

interface WaypointRow {
  id: string;
  waypoint: Vec3;
  yawDeg: number;
  leg3d: number;
  bearingDeg: number | null;
  dz: number;
  eta: number;
}

const formatNumber = (value: number, digits = 1) => value.toFixed(digits);

function buildRows(waypoints: Vec3[], yaws: number[]): WaypointRow[] {
  let eta = 0;
  return waypoints.map((waypoint, index) => {
    const previous = waypoints[index - 1];
    const diff = previous
      ? ([waypoint[0] - previous[0], waypoint[1] - previous[1], waypoint[2] - previous[2]] as Vec3)
      : ([0, 0, 0] as Vec3);
    const leg3d = previous
      ? Math.hypot(diff[0], diff[1], diff[2])
      : 0;
    eta += leg3d / CRUISE_SPEED_MPS;
    const bearingDeg = previous
      ? (Math.atan2(diff[0], diff[1]) * 180 / Math.PI + 360) % 360
      : null;

    return {
      id: `WPT-${index + 1}`,
      waypoint,
      yawDeg: yaws[index] ?? 0,
      leg3d,
      bearingDeg,
      dz: diff[2],
      eta,
    };
  });
}

export function MissionPlanPanel() {
  const {
    currentPreset,
    selectedWaypointIndex,
    missionDirty,
    simRunning,
    acceptRadius,
    selectWaypoint,
    updateWaypointAxis,
    updateYaw,
    addWaypoint,
    duplicateWaypoint,
    deleteWaypoint,
    resetMissionPlan,
    setAcceptRadius,
    setDuration,
    runSimulation,
  } = useAppStore();

  const rows = useMemo(
    () => buildRows(currentPreset?.waypoints ?? [], currentPreset?.yaws_deg ?? []),
    [currentPreset?.waypoints, currentPreset?.yaws_deg],
  );

  const summary = useMemo(() => {
    const totalPath = rows.reduce((sum, row) => sum + row.leg3d, 0);
    const altitudes = rows.map((row) => row.waypoint[2]);
    return {
      totalPath,
      minAlt: altitudes.length ? Math.min(...altitudes) : 0,
      maxAlt: altitudes.length ? Math.max(...altitudes) : 0,
      eta: rows.at(-1)?.eta ?? 0,
    };
  }, [rows]);

  if (!currentPreset) {
    return (
      <div className="px-4 py-5">
        <div className="text-xs text-muted">Load a mission scenario to edit the plan.</div>
      </div>
    );
  }

  const selectedRow = rows[selectedWaypointIndex];
  const canDelete = rows.length > 2;

  return (
      <div className="space-y-5">
        <section className="space-y-3">
          <div className="flex items-center justify-between gap-3">
            <header className="flex items-center gap-2">
              <span className="h-5 w-1 rounded-sm bg-amber" />
              <div>
                <h2 className="text-[0.74rem] font-semibold uppercase tracking-[0.18em] text-amber">
                  Mission Plan
                </h2>
                <p className="mt-0.5 text-xs text-muted">
                  {selectedRow ? `${selectedRow.id} selected` : "No waypoint selected"}
                </p>
              </div>
            </header>
            <span className={missionDirty ? "pill-amber" : "pill-green"}>
              {missionDirty ? "Plan changed" : "Synced"}
            </span>
          </div>

          <div className="grid grid-cols-4 gap-2">
            <SummaryStat label="Waypoints" value={rows.length.toString()} />
            <SummaryStat label="Path" value={`${formatNumber(summary.totalPath)} m`} />
            <SummaryStat label="Alt" value={`${formatNumber(summary.minAlt)}-${formatNumber(summary.maxAlt)} m`} />
            <SummaryStat label="ETA" value={`${formatNumber(summary.eta)} s`} />
          </div>
        </section>

        <section className="panel p-3 space-y-3">
          <div className="grid grid-cols-4 gap-2">
            <IconButton
              icon={<Plus className="h-3.5 w-3.5" />}
              label="Add"
              onClick={() => addWaypoint()}
            />
            <IconButton
              icon={<Copy className="h-3.5 w-3.5" />}
              label="Duplicate"
              onClick={() => duplicateWaypoint()}
            />
            <IconButton
              icon={<Trash2 className="h-3.5 w-3.5" />}
              label="Delete"
              onClick={() => deleteWaypoint()}
              disabled={!canDelete}
              danger
            />
            <IconButton
              icon={<RotateCcw className="h-3.5 w-3.5" />}
              label="Reset"
              onClick={resetMissionPlan}
            />
          </div>

          <div className="grid grid-cols-2 gap-3">
            <label className="space-y-1.5 text-xs text-muted">
              <span className="flex items-center justify-between">
                <span>Acceptance radius</span>
                <span className="font-mono text-cyan">{acceptRadius.toFixed(2)} m</span>
              </span>
              <input
                type="range"
                min={0.1}
                max={2}
                step={0.05}
                value={acceptRadius}
                onChange={(event) => setAcceptRadius(Number(event.target.value))}
                className="w-full accent-cyan"
              />
            </label>

            <label className="space-y-1.5 text-xs text-muted">
              <span>Duration</span>
              <input
                type="number"
                min={10}
                max={120}
                step={1}
                value={currentPreset.duration_s}
                onChange={(event) => setDuration(Number(event.target.value))}
                className="field"
              />
            </label>
          </div>

          <button
            type="button"
            onClick={() => runSimulation()}
            disabled={simRunning || rows.length < 2}
            className={cn(
              "flex w-full items-center justify-center gap-2 rounded-md border px-3 py-2 text-xs font-semibold uppercase tracking-wider transition-colors",
              simRunning
                ? "cursor-wait border-amber/40 bg-amber/10 text-amber"
                : "border-cyan/40 bg-cyan/10 text-cyan hover:bg-cyan/20",
            )}
          >
            <Send className="h-3.5 w-3.5" />
            {simRunning ? "Running simulation" : "Run edited plan"}
          </button>
        </section>

        <section className="space-y-2">
          <div className="flex items-center justify-between">
            <div className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-cyan">
              Waypoint Table
            </div>
            <div className="flex items-center gap-1.5 text-[0.68rem] uppercase tracking-wider text-muted">
              <Crosshair className="h-3.5 w-3.5 text-cyan" />
              Drag in scene or edit cells
            </div>
          </div>

          <div className="overflow-hidden rounded-lg border border-cyan/15 bg-panel">
            <div className="max-h-[44vh] overflow-auto">
              <table className="w-full min-w-[720px] table-fixed text-xs">
                <thead className="sticky top-0 z-10 bg-panel-2 text-[0.64rem] uppercase tracking-wider text-muted">
                  <tr>
                    <Th className="w-16">WPT</Th>
                    <Th>x</Th>
                    <Th>y</Th>
                    <Th>z</Th>
                    <Th>yaw</Th>
                    <Th>Leg</Th>
                    <Th>Brg</Th>
                    <Th>dz</Th>
                    <Th>ETA</Th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, index) => {
                    const selected = index === selectedWaypointIndex;
                    return (
                      <tr
                        key={row.id}
                        onClick={() => selectWaypoint(index)}
                        className={cn(
                          "border-t border-cyan/10 transition-colors",
                          selected ? "bg-cyan/10" : "hover:bg-panel-2/80",
                        )}
                      >
                        <td className="px-2 py-2 font-mono text-amber">{row.id}</td>
                        <EditableCell value={row.waypoint[0]} onChange={(value) => updateWaypointAxis(index, 0, value)} />
                        <EditableCell value={row.waypoint[1]} onChange={(value) => updateWaypointAxis(index, 1, value)} />
                        <EditableCell value={row.waypoint[2]} onChange={(value) => updateWaypointAxis(index, 2, value)} min={0} />
                        <EditableCell value={row.yawDeg} onChange={(value) => updateYaw(index, value)} step={5} />
                        <ComputedCell value={formatNumber(row.leg3d, 2)} />
                        <ComputedCell value={row.bearingDeg === null ? "--" : formatNumber(row.bearingDeg, 0)} />
                        <ComputedCell value={`${row.dz >= 0 ? "+" : ""}${formatNumber(row.dz, 2)}`} />
                        <ComputedCell value={formatNumber(row.eta, 1)} />
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>

          <div className="text-[0.7rem] leading-relaxed text-muted">
            Bearing uses nav convention: 0=N, 90=E. ETA assumes {CRUISE_SPEED_MPS} m/s cruise; closed-loop timing depends on gains, wind, and avoidance.
          </div>
        </section>
      </div>
  );
}

function SummaryStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel-soft px-3 py-2">
      <div className="text-[0.6rem] uppercase tracking-widest text-muted">{label}</div>
      <div className="mt-0.5 truncate font-mono text-sm font-semibold text-cyan">{value}</div>
    </div>
  );
}

function IconButton({
  icon,
  label,
  onClick,
  disabled,
  danger,
}: {
  icon: ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      title={label}
      className={cn(
        "flex h-9 items-center justify-center gap-2 rounded-md border text-xs font-semibold transition-colors",
        danger
          ? "border-red/30 bg-red/10 text-red hover:bg-red/15"
          : "border-cyan/20 bg-panel-2 text-text/80 hover:border-cyan/35 hover:text-cyan",
        disabled && "cursor-not-allowed opacity-40 hover:border-cyan/20 hover:text-text/80",
      )}
    >
      {icon}
      <span>{label}</span>
    </button>
  );
}

function Th({ children, className }: { children: ReactNode; className?: string }) {
  return <th className={cn("px-2 py-2 text-left font-semibold", className)}>{children}</th>;
}

function EditableCell({
  value,
  onChange,
  min,
  step = 0.1,
}: {
  value: number;
  onChange: (value: number) => void;
  min?: number;
  step?: number;
}) {
  return (
    <td className="px-1.5 py-1.5">
      <input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        min={min}
        step={step}
        onChange={(event) => onChange(Number(event.target.value))}
        className="field font-mono"
      />
    </td>
  );
}

function ComputedCell({ value }: { value: string }) {
  return <td className="px-2 py-2 font-mono text-violet">{value}</td>;
}
