"use client";

import {
  Camera,
  CloudSun,
  Crosshair,
  Eye,
  Gauge,
  Layers,
  MapPin,
  Plane,
  Play,
  Plus,
  Radar,
  RotateCcw,
  ScanLine,
  ShieldAlert,
  Sparkles,
  Sun,
  Trash2,
  Volume2,
} from "lucide-react";
import type { ReactNode } from "react";
import { useAppStore } from "@/lib/store";
import type { EnemyPayload, FriendlyDronePayload, InterceptorBatteryPayload, Vec3, ZonePayload } from "@/lib/types";
import { cn } from "@/lib/utils";

const enemyBehaviors: EnemyPayload["behavior"][] = ["patrol", "loiter", "pursue"];
const sceneModes = [
  { id: "range", label: "Range" },
  { id: "night", label: "Night" },
  { id: "analysis", label: "Analysis" },
] as const;
const cameraPresets = [
  { id: "orbit", label: "Orbit" },
  { id: "top", label: "Top" },
  { id: "chase", label: "Chase" },
] as const;
const defensiveModes = [
  { id: "corridor", label: "Corridor" },
  { id: "beam", label: "Beam" },
] as const;

const round = (value: number, digits = 2) => value.toFixed(digits);
const formatMissDistance = (value?: number) => {
  if (value === undefined || !Number.isFinite(value)) return "--";
  return `${value.toFixed(value < 1 ? 2 : 1)} m`;
};

export function SimulationRoomPanel() {
  const {
    currentPreset,
    initialPosition,
    friendlyDrones,
    droneDynamics,
    antiAirConfig,
    defensiveEvasionConfig,
    sceneRoomMode,
    sceneCameraPreset,
    sceneEditTarget,
    simRunning,
    simResult,
    showTerrain,
    showParticles,
    showPostFX,
    showSky,
    showRadarSweep,
    soundEnabled,
    updateInitialPositionAxis,
    resetInitialPosition,
    addFriendlyDrone,
    updateFriendlyDrone,
    deleteFriendlyDrone,
    resetFriendlyDrones,
    setDroneDynamics,
    setAntiAirConfig,
    updateBattery,
    addBattery,
    deleteBattery,
    resetAntiAirConfig,
    setDefensiveEvasionConfig,
    resetDroneDynamics,
    runSimulation,
    setSceneRoomMode,
    setSceneCameraPreset,
    setShowTerrain,
    setShowParticles,
    setShowPostFX,
    setShowSky,
    setShowRadarSweep,
    setSoundEnabled,
    selectSceneEditTarget,
    updateEnemy,
    deleteEnemy,
    updateZone,
    deleteZone,
    deleteWaypoint,
  } = useAppStore();

  if (!currentPreset) return null;

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <header className="flex items-center gap-2">
          <span className="h-5 w-1 rounded-sm bg-cyan" />
          <div>
            <h2 className="text-[0.74rem] font-semibold uppercase tracking-[0.18em] text-cyan">
              Simulation Room
            </h2>
            <p className="mt-0.5 text-xs text-muted">
              Scene modes, camera presets, and direct 3D entity dragging
            </p>
          </div>
        </header>
        <Radar className="h-4 w-4 text-cyan" />
      </div>

      <section className="panel p-3 space-y-3">
        <div className="flex items-center justify-between">
          <div className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-cyan">
            Room View
          </div>
          <Eye className="h-3.5 w-3.5 text-cyan" />
        </div>
        <Segmented
          label="Lighting"
          items={sceneModes}
          value={sceneRoomMode}
          onChange={setSceneRoomMode}
        />
        <Segmented
          label="Camera"
          items={cameraPresets}
          value={sceneCameraPreset}
          onChange={setSceneCameraPreset}
          icon={<Camera className="h-3.5 w-3.5" />}
        />

        <div className="space-y-1.5">
          <div className="text-[0.66rem] font-semibold uppercase tracking-[0.18em] text-muted">
            Visual Layers
          </div>
          <div className="grid grid-cols-1 gap-1.5">
            <ToggleRow
              icon={<Layers className="h-3.5 w-3.5" />}
              label="Terrain"
              hint="Rolling hills under the grid"
              value={showTerrain}
              onChange={setShowTerrain}
            />
            <ToggleRow
              icon={<Sparkles className="h-3.5 w-3.5" />}
              label="Particle FX"
              hint="Rotor wash, contrail, intercept burst"
              value={showParticles}
              onChange={setShowParticles}
            />
            <ToggleRow
              icon={<CloudSun className="h-3.5 w-3.5" />}
              label="Sky environment"
              hint="HDRi skybox + realistic reflections"
              value={showSky}
              onChange={setShowSky}
            />
            <ToggleRow
              icon={<Sun className="h-3.5 w-3.5" />}
              label="Post-processing"
              hint="Bloom · SSAO · vignette"
              value={showPostFX}
              onChange={setShowPostFX}
            />
            <ToggleRow
              icon={<ScanLine className="h-3.5 w-3.5" />}
              label="Radar sweep"
              hint="Rotating cyan detection wedge"
              value={showRadarSweep}
              onChange={setShowRadarSweep}
            />
            <ToggleRow
              icon={<Volume2 className="h-3.5 w-3.5" />}
              label="Audio"
              hint="Rotor whirr · waypoint chime · intercept klaxon"
              value={soundEnabled}
              onChange={setSoundEnabled}
            />
          </div>
        </div>
      </section>

      <section className="panel p-3 space-y-3">
        <div className="flex items-center justify-between">
          <div className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-cyan">
            Launch Drone
          </div>
          <Plane className="h-3.5 w-3.5 text-cyan" />
        </div>
        <div className="grid grid-cols-3 gap-2">
          <NumberField label="x" value={initialPosition[0]} onChange={(value) => updateInitialPositionAxis(0, value)} />
          <NumberField label="y" value={initialPosition[1]} onChange={(value) => updateInitialPositionAxis(1, value)} />
          <NumberField label="z" value={initialPosition[2]} min={0} onChange={(value) => updateInitialPositionAxis(2, value)} />
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={resetInitialPosition}
            className="flex h-9 items-center justify-center gap-2 rounded-md border border-cyan/20 bg-bg/60 px-3 text-xs font-semibold text-cyan transition-colors hover:bg-cyan/10"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Reset
          </button>
          <button
            type="button"
            onClick={runSimulation}
            disabled={simRunning}
            className="flex h-9 flex-1 items-center justify-center gap-2 rounded-md border border-green/35 bg-green/10 px-3 text-xs font-semibold uppercase tracking-wider text-green transition-colors hover:bg-green/15 disabled:cursor-not-allowed disabled:opacity-50"
          >
            <Play className="h-3.5 w-3.5" />
            {simRunning ? "Running" : "Run Room"}
          </button>
        </div>
      </section>

      <section className="panel p-3 space-y-3">
        <div className="flex items-center justify-between">
          <div className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-green">
            Multi-UAV Flight
          </div>
          <Plane className="h-3.5 w-3.5 text-green" />
        </div>
        <div className="grid grid-cols-3 gap-2 text-xs">
          <MetricTile label="wingmen" value={String(friendlyDrones.length)} tone="text-green" />
          <MetricTile
            label="survivors"
            value={String((simResult?.friendly_tracks ?? []).filter((track) => !track.interceptor_killed).length)}
            tone="text-cyan"
          />
          <MetricTile
            label="down"
            value={String((simResult?.friendly_tracks ?? []).filter((track) => track.interceptor_killed).length)}
            tone="text-red"
          />
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => addFriendlyDrone()}
            className="flex h-8 flex-1 items-center justify-center gap-2 rounded-md border border-green/30 bg-green/10 px-3 text-xs font-semibold uppercase tracking-wider text-green transition-colors hover:bg-green/15"
          >
            <Plus className="h-3.5 w-3.5" />
            Add UAV
          </button>
          <button
            type="button"
            onClick={resetFriendlyDrones}
            disabled={friendlyDrones.length === 0}
            className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-green/25 bg-green/10 text-green transition-colors hover:bg-green/15 disabled:cursor-not-allowed disabled:opacity-40"
            title="Clear wingmen"
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </button>
        </div>
        <div className="grid gap-2">
          {friendlyDrones.length === 0 && (
            <div className="rounded-md border border-green/15 bg-green/5 px-3 py-2 text-xs text-muted">
              Add UAVs here or place them directly on the tactical map.
            </div>
          )}
          {friendlyDrones.map((drone, index) => (
            <FriendlyDroneRow
              key={`${drone.name}-${index}`}
              drone={drone}
              selected={sceneEditTarget?.kind === "friendly" && sceneEditTarget.index === index}
              onSelect={() => selectSceneEditTarget({ kind: "friendly", index })}
              onChange={(patch) => updateFriendlyDrone(index, patch)}
              onDelete={() => deleteFriendlyDrone(index)}
            />
          ))}
        </div>
      </section>

      <section className="panel p-3 space-y-3">
        <div className="flex items-center justify-between">
          <div className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-green">
            Drone Dynamics
          </div>
          <Gauge className="h-3.5 w-3.5 text-green" />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <NumberField
            label="speed cap"
            value={droneDynamics.maxSpeedXY}
            min={0.2}
            step={0.2}
            onChange={(maxSpeedXY) => setDroneDynamics({ maxSpeedXY })}
          />
          <NumberField
            label="xy accel"
            value={droneDynamics.maxAccelXY}
            min={0.2}
            step={0.2}
            onChange={(maxAccelXY) => setDroneDynamics({ maxAccelXY })}
          />
          <NumberField
            label="max tilt"
            value={droneDynamics.maxTiltDeg}
            min={1}
            step={1}
            onChange={(maxTiltDeg) => setDroneDynamics({ maxTiltDeg })}
          />
          <NumberField
            label="mass"
            value={droneDynamics.mass}
            min={0.2}
            step={0.1}
            onChange={(mass) => setDroneDynamics({ mass })}
          />
        </div>
        <div className="flex items-center justify-between gap-3 rounded-md border border-green/15 bg-green/5 px-3 py-2 text-xs text-muted">
          <span>
            Speed cap limits horizontal acceleration once the drone reaches the selected XY speed.
          </span>
          <button
            type="button"
            onClick={resetDroneDynamics}
            className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-green/25 bg-green/10 text-green transition-colors hover:bg-green/15"
            title="Reset drone dynamics"
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </button>
        </div>
      </section>

      <section className="panel p-3 space-y-3">
        <div className="flex items-center justify-between">
          <div className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-red">
            PN Interceptor
          </div>
          <Crosshair className="h-3.5 w-3.5 text-red" />
        </div>
        <ToggleRow
          icon={<Radar className="h-3.5 w-3.5" />}
          label="Anti-air batteries"
          hint="Ground SAM launchers with proportional navigation"
          value={antiAirConfig.enabled}
          onChange={(enabled) => setAntiAirConfig({ enabled })}
        />
        <div className="grid grid-cols-4 gap-2 text-xs">
          <MetricTile
            label="launches"
            value={String(simResult?.interceptor_summary?.n_launches ?? 0)}
            tone="text-cyan"
          />
          <MetricTile
            label="hits"
            value={String(simResult?.interceptor_summary?.n_hits ?? 0)}
            tone="text-red"
          />
          <MetricTile
            label="locks"
            value={String(simResult?.interceptor_summary?.n_seeker_locks ?? 0)}
            tone="text-green"
          />
          <MetricTile
            label="min miss"
            value={formatMissDistance(simResult?.interceptor_summary?.min_miss_distance)}
            tone="text-amber"
          />
        </div>
        <div className="space-y-1.5">
          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={addBattery}
              className="flex h-8 flex-1 items-center justify-center gap-2 rounded-md border border-red/30 bg-red/10 px-3 text-xs font-semibold uppercase tracking-wider text-red transition-colors hover:bg-red/15"
            >
              <Plus className="h-3.5 w-3.5" />
              Add Battery
            </button>
            <button
              type="button"
              onClick={resetAntiAirConfig}
              className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-red/25 bg-red/10 text-red transition-colors hover:bg-red/15"
              title="Reset interceptor batteries"
            >
              <RotateCcw className="h-3.5 w-3.5" />
            </button>
          </div>
          {antiAirConfig.batteries.length === 0 && (
            <div className="rounded-md border border-red/15 bg-red/5 px-3 py-2 text-xs text-muted">
              No interceptor batteries configured.
            </div>
          )}
          {antiAirConfig.batteries.map((battery, index) => (
            <BatteryRow
              key={`${battery.name}-${index}`}
              battery={battery}
              selected={sceneEditTarget?.kind === "battery" && sceneEditTarget.index === index}
              onSelect={() => selectSceneEditTarget({ kind: "battery", index })}
              onChange={(patch) => updateBattery(index, patch)}
              onDelete={() => deleteBattery(index)}
            />
          ))}
        </div>
      </section>

      <section className="panel p-3 space-y-3">
        <div className="flex items-center justify-between">
          <div className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-amber">
            Defensive Evasion
          </div>
          <ShieldAlert className="h-3.5 w-3.5 text-amber" />
        </div>
        <ToggleRow
          icon={<ShieldAlert className="h-3.5 w-3.5" />}
          label="Missile warning"
          hint="Autonomous beam/corridor break when PN closes"
          value={defensiveEvasionConfig.enabled}
          onChange={(enabled) => setDefensiveEvasionConfig({ enabled })}
        />
        <Segmented
          label="Escape law"
          items={defensiveModes}
          value={defensiveEvasionConfig.mode}
          onChange={(mode) => setDefensiveEvasionConfig({ mode })}
          icon={<Radar className="h-3.5 w-3.5" />}
        />
        <div className="grid grid-cols-3 gap-2 text-xs">
          <MetricTile
            label="evasions"
            value={String(simResult?.defensive_summary?.n_evasions ?? 0)}
            tone="text-amber"
          />
          <MetricTile
            label="evade time"
            value={`${(simResult?.defensive_summary?.time_evasive ?? 0).toFixed(1)}s`}
            tone="text-cyan"
          />
          <MetricTile
            label="escaped"
            value={simResult?.defensive_summary?.escaped ? "YES" : "NO"}
            tone={simResult?.defensive_summary?.escaped ? "text-green" : "text-red"}
          />
        </div>
        <div className="grid grid-cols-2 gap-2">
          <NumberField
            label="detect r"
            value={defensiveEvasionConfig.detect_range}
            min={1}
            step={0.5}
            onChange={(detect_range) => setDefensiveEvasionConfig({ detect_range })}
          />
          <NumberField
            label="trigger tgo"
            value={defensiveEvasionConfig.trigger_tgo}
            min={0.2}
            step={0.1}
            onChange={(trigger_tgo) => setDefensiveEvasionConfig({ trigger_tgo })}
          />
          <NumberField
            label="hold time"
            value={defensiveEvasionConfig.hold_time}
            min={0.2}
            step={0.1}
            onChange={(hold_time) => setDefensiveEvasionConfig({ hold_time })}
          />
          <NumberField
            label="escape dist"
            value={defensiveEvasionConfig.escape_distance}
            min={0.5}
            step={0.25}
            onChange={(escape_distance) => setDefensiveEvasionConfig({ escape_distance })}
          />
          <NumberField
            label="alt step"
            value={defensiveEvasionConfig.altitude_delta}
            step={0.1}
            onChange={(altitude_delta) => setDefensiveEvasionConfig({ altitude_delta })}
          />
          <NumberField
            label="evade tilt"
            value={defensiveEvasionConfig.emergency_max_tilt_deg}
            min={1}
            step={1}
            onChange={(emergency_max_tilt_deg) => setDefensiveEvasionConfig({ emergency_max_tilt_deg })}
          />
          <NumberField
            label="evade accel"
            value={defensiveEvasionConfig.emergency_max_accel_xy}
            min={0.2}
            step={0.2}
            onChange={(emergency_max_accel_xy) => setDefensiveEvasionConfig({ emergency_max_accel_xy })}
          />
          <NumberField
            label="evade speed"
            value={defensiveEvasionConfig.emergency_max_speed_xy}
            min={0.2}
            step={0.2}
            onChange={(emergency_max_speed_xy) => setDefensiveEvasionConfig({ emergency_max_speed_xy })}
          />
        </div>
      </section>

      <section className="space-y-2">
        <SectionTitle icon={<Plane className="h-3.5 w-3.5" />} label="Waypoints" count={currentPreset.waypoints.length} />
        <div className="grid gap-2">
          {currentPreset.waypoints.map((waypoint, index) => (
            <WaypointRow
              key={index}
              index={index}
              waypoint={waypoint}
              canDelete={currentPreset.waypoints.length > 2}
              onDelete={() => deleteWaypoint(index)}
            />
          ))}
        </div>
      </section>

      <section className="space-y-2">
        <SectionTitle icon={<Crosshair className="h-3.5 w-3.5" />} label="Bandits" count={currentPreset.enemies.length} />
        <p className="px-1 text-xs text-muted">
          Click a bandit in the 3D room or this roster, then drag the transform handle.
        </p>
        <div className="grid gap-2">
          {currentPreset.enemies.length === 0 && (
            <div className="panel p-3 text-xs text-muted">No bandits in this scenario.</div>
          )}
          {currentPreset.enemies.map((enemy, index) => (
            <EnemyRow
              key={`${enemy.name}-${index}`}
              enemy={enemy}
              selected={sceneEditTarget?.kind === "enemy" && sceneEditTarget.index === index}
              onSelect={() => selectSceneEditTarget({ kind: "enemy", index })}
              onChange={(patch) => updateEnemy(index, patch)}
              onDelete={() => deleteEnemy(index)}
            />
          ))}
        </div>
      </section>

      <section className="space-y-2">
        <SectionTitle icon={<MapPin className="h-3.5 w-3.5" />} label="Zones" count={currentPreset.zones.length} />
        <p className="px-1 text-xs text-muted">
          Click a zone volume in the 3D room or this roster, then drag to reposition it.
        </p>
        <div className="grid gap-2">
          {currentPreset.zones.length === 0 && (
            <div className="panel p-3 text-xs text-muted">No zones in this scenario.</div>
          )}
          {currentPreset.zones.map((zone, index) => (
            <ZoneRow
              key={`${zone.name}-${index}`}
              zone={zone}
              selected={sceneEditTarget?.kind === "zone" && sceneEditTarget.index === index}
              onSelect={() => selectSceneEditTarget({ kind: "zone", index })}
              onChange={(patch) => updateZone(index, patch)}
              onDelete={() => deleteZone(index)}
            />
          ))}
        </div>
      </section>
    </section>
  );
}

function Segmented<T extends string>({
  label,
  items,
  value,
  onChange,
  icon,
}: {
  label: string;
  items: readonly { id: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  icon?: ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-1.5 text-[0.62rem] uppercase tracking-widest text-muted">
        {icon}
        {label}
      </div>
      <div
        className="grid gap-1 rounded-lg border border-cyan/15 bg-bg/50 p-1"
        style={{ gridTemplateColumns: `repeat(${items.length}, minmax(0, 1fr))` }}
      >
        {items.map((item) => (
          <button
            key={item.id}
            type="button"
            onClick={() => onChange(item.id)}
            className={cn(
              "h-8 rounded-md text-[0.68rem] font-semibold uppercase tracking-wider transition-colors",
              value === item.id ? "bg-cyan/15 text-cyan" : "text-muted hover:bg-panel-2 hover:text-text",
            )}
          >
            {item.label}
          </button>
        ))}
      </div>
    </div>
  );
}

function SectionTitle({
  icon,
  label,
  count,
}: {
  icon: ReactNode;
  label: string;
  count: number;
}) {
  return (
    <div className="flex items-center justify-between px-1">
      <div className="flex items-center gap-2 text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted">
        <span className="text-cyan">{icon}</span>
        {label}
      </div>
      <span className="font-mono text-xs text-cyan">{count}</span>
    </div>
  );
}

function MetricTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: string;
}) {
  return (
    <div className="rounded-md border border-cyan/10 bg-bg/50 px-2.5 py-2">
      <div className="text-[0.6rem] uppercase tracking-widest text-muted">{label}</div>
      <div className={`mt-1 font-mono text-sm font-semibold ${tone}`}>{value}</div>
    </div>
  );
}

function FriendlyDroneRow({
  drone,
  selected,
  onSelect,
  onChange,
  onDelete,
}: {
  drone: FriendlyDronePayload;
  selected: boolean;
  onSelect: () => void;
  onChange: (patch: Partial<FriendlyDronePayload>) => void;
  onDelete: () => void;
}) {
  return (
    <div
      onClick={onSelect}
      className={cn(
        "rounded-md border bg-green/5 px-3 py-3 text-xs transition-colors",
        selected ? "border-green/45 bg-green/10" : "border-green/15",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <label className="min-w-0 flex-1 space-y-1 text-muted">
          <span>name</span>
          <input
            value={drone.name}
            onChange={(event) => onChange({ name: event.target.value })}
            className="field font-mono"
          />
        </label>
        <DeleteButton onClick={onDelete} title="Delete UAV" />
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2">
        <NumberField label="x" value={drone.x} step={0.1} onChange={(x) => onChange({ x })} />
        <NumberField label="y" value={drone.y} step={0.1} onChange={(y) => onChange({ y })} />
        <NumberField label="z" value={drone.z} min={0} step={0.1} onChange={(z) => onChange({ z })} />
      </div>
      <div className="mt-3 grid grid-cols-2 gap-1 rounded-lg border border-green/15 bg-bg/45 p-1">
        {(["formation", "same"] as const).map((mode) => (
          <button
            key={mode}
            type="button"
            onClick={() => onChange({ route_mode: mode })}
            className={cn(
              "h-8 rounded-md text-[0.66rem] font-semibold uppercase tracking-wider transition-colors",
              drone.route_mode === mode ? "bg-green/15 text-green" : "text-muted hover:bg-panel hover:text-text",
            )}
          >
            {mode}
          </button>
        ))}
      </div>
      <ToggleRow
        icon={<Plane className="h-3.5 w-3.5" />}
        label="Enabled"
        hint="Include this UAV in the next simulation run"
        value={drone.enabled}
        onChange={(enabled) => onChange({ enabled })}
      />
    </div>
  );
}

function BatteryRow({
  battery,
  selected,
  onSelect,
  onChange,
  onDelete,
}: {
  battery: InterceptorBatteryPayload;
  selected: boolean;
  onSelect: () => void;
  onChange: (patch: Partial<InterceptorBatteryPayload>) => void;
  onDelete: () => void;
}) {
  return (
    <div
      onClick={onSelect}
      className={cn(
        "rounded-md border bg-red/5 px-3 py-3 text-xs transition-colors",
        selected ? "border-red/45 bg-red/10" : "border-red/15",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <label className="min-w-0 flex-1 space-y-1 text-muted">
          <span>name</span>
          <input
            value={battery.name}
            onChange={(event) => onChange({ name: event.target.value })}
            className="field font-mono"
          />
        </label>
        <DeleteButton onClick={onDelete} title="Delete interceptor battery" />
      </div>
      <div className="mt-3 grid grid-cols-3 gap-2">
        <NumberField label="x" value={battery.x} step={0.1} onChange={(x) => onChange({ x })} />
        <NumberField label="y" value={battery.y} step={0.1} onChange={(y) => onChange({ y })} />
        <NumberField label="z" value={battery.z} min={0} step={0.1} onChange={(z) => onChange({ z })} />
        <NumberField label="range" value={battery.launch_range} min={0.5} step={0.5} onChange={(launch_range) => onChange({ launch_range })} />
        <NumberField label="min alt" value={battery.min_engage_alt} min={0} step={0.1} onChange={(min_engage_alt) => onChange({ min_engage_alt })} />
        <NumberField label="cooldown" value={battery.cooldown} min={0} step={0.1} onChange={(cooldown) => onChange({ cooldown })} />
        <NumberField label="N gain" value={battery.nav_constant} min={0.5} step={0.25} onChange={(nav_constant) => onChange({ nav_constant })} />
        <NumberField label="lat accel" value={battery.max_lateral_accel} min={1} step={1} onChange={(max_lateral_accel) => onChange({ max_lateral_accel })} />
        <NumberField label="lethal r" value={battery.lethal_radius} min={0.05} step={0.05} onChange={(lethal_radius) => onChange({ lethal_radius })} />
        <NumberField label="arm time" value={battery.arming_time} min={0} step={0.05} onChange={(arming_time) => onChange({ arming_time })} />
        <NumberField label="init speed" value={battery.initial_speed} min={0.1} step={0.5} onChange={(initial_speed) => onChange({ initial_speed })} />
        <NumberField label="boost" value={battery.boost_accel} min={0} step={1} onChange={(boost_accel) => onChange({ boost_accel })} />
        <NumberField label="boost t" value={battery.boost_time} min={0} step={0.05} onChange={(boost_time) => onChange({ boost_time })} />
        <NumberField label="drag" value={battery.coast_drag} min={0} step={0.005} onChange={(coast_drag) => onChange({ coast_drag })} />
        <NumberField label="active" value={battery.max_active} min={1} step={1} onChange={(max_active) => onChange({ max_active })} />
        <NumberField label="shots" value={battery.max_total_shots} min={1} step={1} onChange={(max_total_shots) => onChange({ max_total_shots })} />
        <NumberField label="max time" value={battery.max_time} min={0.1} step={0.1} onChange={(max_time) => onChange({ max_time })} />
      </div>
      <div className="mt-3 space-y-2 rounded-md border border-red/10 bg-bg/35 p-2">
        <ToggleRow
          icon={<Eye className="h-3.5 w-3.5" />}
          label="Seeker model"
          hint="FOV/range-gated lock instead of perfect truth PN"
          value={battery.seeker_enabled}
          onChange={(seeker_enabled) => onChange({ seeker_enabled })}
        />
        <div className="grid grid-cols-2 gap-2">
          <NumberField label="seeker r" value={battery.seeker_range} min={0.5} step={0.5} onChange={(seeker_range) => onChange({ seeker_range })} />
          <NumberField label="FOV deg" value={battery.seeker_fov_deg} min={1} step={1} onChange={(seeker_fov_deg) => onChange({ seeker_fov_deg })} />
          <NumberField label="LOS noise" value={battery.seeker_noise_std_deg} min={0} step={0.05} onChange={(seeker_noise_std_deg) => onChange({ seeker_noise_std_deg })} />
          <NumberField label="memory" value={battery.seeker_memory_time} min={0} step={0.05} onChange={(seeker_memory_time) => onChange({ seeker_memory_time })} />
        </div>
      </div>
    </div>
  );
}

function WaypointRow({
  index,
  waypoint,
  canDelete,
  onDelete,
}: {
  index: number;
  waypoint: Vec3;
  canDelete: boolean;
  onDelete: () => void;
}) {
  return (
    <div className="panel-soft flex items-center justify-between gap-3 px-3 py-2 text-xs">
      <div>
        <div className="font-semibold text-text">WPT-{index + 1}</div>
        <div className="mt-0.5 font-mono text-[0.68rem] text-muted">
          x {round(waypoint[0])} | y {round(waypoint[1])} | z {round(waypoint[2])}
        </div>
      </div>
      <DeleteButton disabled={!canDelete} onClick={onDelete} title="Delete waypoint" />
    </div>
  );
}

function EnemyRow({
  enemy,
  selected,
  onSelect,
  onChange,
  onDelete,
}: {
  enemy: EnemyPayload;
  selected: boolean;
  onSelect: () => void;
  onChange: (patch: Partial<EnemyPayload>) => void;
  onDelete: () => void;
}) {
  return (
    <div
      onClick={onSelect}
      className={cn(
        "panel-soft space-y-3 px-3 py-3 transition-colors",
        selected && "border-red/45 bg-red/10",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="font-semibold text-text">{enemy.name}</div>
          <div className="mt-0.5 font-mono text-[0.68rem] text-muted">
            x {round(enemy.x)} | y {round(enemy.y)} | z {round(enemy.z)}
          </div>
        </div>
        <DeleteButton onClick={onDelete} title="Delete bandit" />
      </div>
      <div className="grid grid-cols-3 gap-1 rounded-lg border border-red/15 bg-bg/45 p-1">
        {enemyBehaviors.map((behavior) => (
          <button
            key={behavior}
            type="button"
            onClick={() => onChange({ behavior })}
            className={cn(
              "h-8 rounded-md text-[0.66rem] font-semibold uppercase tracking-wider transition-colors",
              enemy.behavior === behavior ? "bg-red/15 text-red" : "text-muted hover:bg-panel hover:text-text",
            )}
          >
            {behavior}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-3 gap-2">
        <NumberField label="speed" value={enemy.speed} min={0} onChange={(speed) => onChange({ speed })} />
        <NumberField label="det r" value={enemy.det_r} min={0.1} onChange={(det_r) => onChange({ det_r })} />
        <NumberField label="leth r" value={enemy.leth_r} min={0.05} onChange={(leth_r) => onChange({ leth_r })} />
      </div>
    </div>
  );
}

function ZoneRow({
  zone,
  selected,
  onSelect,
  onChange,
  onDelete,
}: {
  zone: ZonePayload;
  selected: boolean;
  onSelect: () => void;
  onChange: (patch: Partial<ZonePayload>) => void;
  onDelete: () => void;
}) {
  return (
    <div
      onClick={onSelect}
      className={cn(
        "panel-soft space-y-3 px-3 py-3 transition-colors",
        selected && "border-amber/45 bg-amber/10",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="font-semibold text-text">{zone.name}</div>
          <div className="mt-0.5 font-mono text-[0.68rem] text-muted">
            x {round(zone.cx)} | y {round(zone.cy)} | r {round(zone.r)}
          </div>
        </div>
        <DeleteButton onClick={onDelete} title="Delete zone" />
      </div>
      <div className="grid grid-cols-2 gap-1 rounded-lg border border-amber/15 bg-bg/45 p-1">
        {(["no_fly", "threat"] as const).map((kind) => (
          <button
            key={kind}
            type="button"
            onClick={() => onChange({ kind })}
            className={cn(
              "h-8 rounded-md text-[0.66rem] font-semibold uppercase tracking-wider transition-colors",
              zone.kind === kind ? "bg-amber/15 text-amber" : "text-muted hover:bg-panel hover:text-text",
            )}
          >
            {kind === "no_fly" ? "No-fly" : "Threat"}
          </button>
        ))}
      </div>
      <div className="grid grid-cols-3 gap-2">
        <NumberField label="r" value={zone.r} min={0.1} onChange={(r) => onChange({ r })} />
        <NumberField label="z min" value={zone.z_min} min={0} onChange={(z_min) => onChange({ z_min })} />
        <NumberField label="z max" value={zone.z_max} min={0.1} onChange={(z_max) => onChange({ z_max })} />
      </div>
    </div>
  );
}

function ToggleRow({
  icon,
  label,
  hint,
  value,
  onChange,
}: {
  icon: ReactNode;
  label: string;
  hint: string;
  value: boolean;
  onChange: (value: boolean) => void;
}) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={value}
      onClick={() => onChange(!value)}
      className={cn(
        "flex items-center gap-2.5 rounded-md border bg-bg/55 px-2.5 py-1.5 text-left transition-colors",
        value
          ? "border-cyan/35 hover:border-cyan/55"
          : "border-cyan/10 hover:border-cyan/25",
      )}
    >
      <span
        className={cn(
          "grid h-7 w-7 place-items-center rounded-md border transition-colors",
          value
            ? "border-cyan/40 bg-cyan/10 text-cyan"
            : "border-cyan/10 bg-bg/40 text-muted",
        )}
      >
        {icon}
      </span>
      <span className="flex-1 min-w-0">
        <span className={cn(
          "block text-[0.72rem] font-semibold",
          value ? "text-cyan" : "text-text/80",
        )}>
          {label}
        </span>
        <span className="block truncate text-[0.62rem] text-muted">
          {hint}
        </span>
      </span>
      <span
        aria-hidden="true"
        className={cn(
          "relative inline-flex h-4 w-8 shrink-0 rounded-full transition-colors",
          value ? "bg-cyan/60" : "bg-panel-2",
        )}
      >
        <span
          className={cn(
            "absolute top-0.5 h-3 w-3 rounded-full bg-bg shadow transition-transform",
            value ? "translate-x-[17px]" : "translate-x-0.5",
          )}
        />
      </span>
    </button>
  );
}

function NumberField({
  label,
  value,
  onChange,
  min,
  step = 0.1,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  step?: number;
}) {
  return (
    <label className="space-y-1 text-xs text-muted">
      <span>{label}</span>
      <input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        min={min}
        step={step}
        onChange={(event) => onChange(Number(event.target.value))}
        className="field font-mono"
      />
    </label>
  );
}

function DeleteButton({
  onClick,
  disabled,
  title,
}: {
  onClick: () => void;
  disabled?: boolean;
  title: string;
}) {
  return (
    <button
      type="button"
      title={title}
      onClick={onClick}
      disabled={disabled}
      className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-red/25 bg-red/10 text-red transition-colors hover:bg-red/15 disabled:cursor-not-allowed disabled:opacity-40"
    >
      <Trash2 className="h-3.5 w-3.5" />
    </button>
  );
}
