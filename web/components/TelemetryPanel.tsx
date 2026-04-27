"use client";

import { Pause, Play, RotateCcw, ShieldAlert, SlidersHorizontal } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { PlotlyChart } from "./PlotlyChart";
import { useAppStore } from "@/lib/store";
import type { SimResponse } from "@/lib/types";
import { cn } from "@/lib/utils";

type TelemetryTab = "overview" | "position" | "attitude" | "control" | "ekf" | "threats";

const telemetryTabs: Array<{ id: TelemetryTab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "position", label: "Position" },
  { id: "attitude", label: "Attitude" },
  { id: "control", label: "Control" },
  { id: "ekf", label: "EKF" },
  { id: "threats", label: "Threats" },
];

const colors = {
  cyan: "#00d4ff",
  amber: "#ffc107",
  green: "#2ecc71",
  violet: "#b388ff",
  pink: "#ff4081",
  red: "#ff5252",
  muted: "#8aa0b8",
  text: "#e1e8f0",
};

const deg = (rad: number) => rad * 180 / Math.PI;
const norm3 = (v: number[]) => Math.hypot(v[0] ?? 0, v[1] ?? 0, v[2] ?? 0);
const round = (value: number, digits = 2) => value.toFixed(digits);

function sampleIndices(length: number, target = 1400) {
  const stride = Math.max(1, Math.floor(length / target));
  const indices: number[] = [];
  for (let i = 0; i < length; i += stride) indices.push(i);
  if (length > 0 && indices[indices.length - 1] !== length - 1) indices.push(length - 1);
  return indices;
}

function sampled<T>(values: T[], indices: number[]) {
  return indices.map((index) => values[index]);
}

function baseLayout(title: string, yTitle: string, extra: Record<string, unknown> = {}) {
  return {
    title: { text: title, font: { size: 13, color: colors.text } },
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "#060912",
    font: { color: colors.text, family: "Inter, Segoe UI, sans-serif", size: 11 },
    margin: { l: 46, r: 18, t: 42, b: 38 },
    xaxis: {
      title: "time [s]",
      gridcolor: "rgba(0, 212, 255, 0.08)",
      zerolinecolor: "rgba(0, 212, 255, 0.18)",
    },
    yaxis: {
      title: yTitle,
      gridcolor: "rgba(0, 212, 255, 0.08)",
      zerolinecolor: "rgba(0, 212, 255, 0.18)",
    },
    legend: { orientation: "h", y: 1.12, x: 0, font: { size: 10 } },
    hovermode: "x unified",
    ...extra,
  };
}

function makeLine(x: number[], y: number[], name: string, color: string, dash?: string) {
  return {
    type: "scatter",
    mode: "lines",
    x,
    y,
    name,
    line: { color, width: 2, dash },
  };
}

function buildTelemetry(simResult: SimResponse | null, enemyNames: string[]) {
  if (!simResult || simResult.t.length === 0) return null;
  const indices = sampleIndices(simResult.t.length);
  const t = sampled(simResult.t, indices);
  const pos = sampled(simResult.pos, indices);
  const vel = sampled(simResult.vel, indices);
  const euler = sampled(simResult.euler, indices);
  const activeWp = sampled(simResult.waypoint_active, indices);
  const meas = sampled(simResult.meas_pos, indices);
  const est = sampled(simResult.state_est, indices);
  const thrust = sampled(simResult.thrust, indices);
  const speed = vel.map(norm3);
  const trackingError = pos.map((p, index) => Math.hypot(
    p[0] - activeWp[index][0],
    p[1] - activeWp[index][1],
    p[2] - activeWp[index][2],
  ));

  const threatSeries = enemyNames.map((name, enemyIndex) => {
    const distances = simResult.enemy_hist.map((frame, index) => {
      const enemy = frame[enemyIndex];
      const ownship = simResult.pos[index];
      return enemy ? Math.hypot(ownship[0] - enemy[0], ownship[1] - enemy[1], ownship[2] - enemy[2]) : null;
    });
    const finite = distances.filter((value): value is number => typeof value === "number" && Number.isFinite(value));
    const minRange = finite.length ? Math.min(...finite) : null;
    const minIndex = minRange === null ? -1 : distances.findIndex((value) => value === minRange);
    return {
      name,
      distances,
      sampledDistances: sampled(distances, indices).map((value) => value ?? null),
      minRange,
      minTime: minIndex >= 0 ? simResult.t[minIndex] : null,
    };
  });

  const closestThreat = threatSeries
    .filter((series) => series.minRange !== null)
    .sort((a, b) => (a.minRange ?? Infinity) - (b.minRange ?? Infinity))[0];

  return {
    indices,
    t,
    pos,
    vel,
    euler,
    activeWp,
    meas,
    est,
    thrust,
    speed,
    trackingError,
    threatSeries,
    closestThreat,
    maxSpeed: Math.max(...speed),
    maxAltitude: Math.max(...simResult.pos.map((p) => p[2])),
    maxTrackingError: Math.max(...trackingError),
  };
}

export function TelemetryPanel() {
  const {
    currentPreset,
    simResult,
    replayIndex,
    replayPlaying,
    replaySpeed,
    setReplayIndex,
    setReplayPlaying,
    setReplaySpeed,
  } = useAppStore();
  const [activeTab, setActiveTab] = useState<TelemetryTab>("overview");
  const lastFrameRef = useRef<number | null>(null);
  const replayIndexRef = useRef(0);

  const enemyNames = useMemo(
    () => currentPreset?.enemies.map((enemy) => enemy.name) ?? [],
    [currentPreset?.enemies],
  );
  const telemetry = useMemo(
    () => buildTelemetry(simResult, enemyNames),
    [enemyNames, simResult],
  );

  const maxReplayIndex = Math.max(0, (simResult?.t.length ?? 1) - 1);
  const replayTime = simResult?.t[Math.min(replayIndex, maxReplayIndex)] ?? 0;

  useEffect(() => {
    replayIndexRef.current = replayIndex;
  }, [replayIndex]);

  useEffect(() => {
    if (!replayPlaying || !simResult || simResult.t.length < 2) return;
    let frame = 0;
    const tick = (now: number) => {
      const last = lastFrameRef.current ?? now;
      const dt = Math.min(0.08, (now - last) / 1000);
      const duration = simResult.t[simResult.t.length - 1] - simResult.t[0] || 1;
      const next = replayIndexRef.current + (dt * replaySpeed * maxReplayIndex) / duration;
      if (next >= maxReplayIndex) {
        setReplayIndex(maxReplayIndex);
        setReplayPlaying(false);
        lastFrameRef.current = null;
        return;
      }
      setReplayIndex(next);
      replayIndexRef.current = next;
      lastFrameRef.current = now;
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [maxReplayIndex, replayPlaying, replaySpeed, setReplayIndex, setReplayPlaying, simResult]);

  if (!simResult || !telemetry) {
    return (
      <section className="space-y-3">
        <Header />
        <div className="panel p-4 text-sm text-muted">
          Run a simulation to populate telemetry plots and replay controls.
        </div>
      </section>
    );
  }

  const chart = useMemo(
    () => buildChart(activeTab, telemetry),
    [activeTab, telemetry],
  );

  return (
    <section className="space-y-4">
      <Header />

      <div className="grid grid-cols-4 gap-2">
        <Stat label="Sim time" value={`${round(simResult.t[simResult.t.length - 1], 1)} s`} />
        <Stat label="Max speed" value={`${round(telemetry.maxSpeed)} m/s`} />
        <Stat label="Max alt" value={`${round(telemetry.maxAltitude)} m`} />
        <Stat label="Max err" value={`${round(telemetry.maxTrackingError)} m`} />
      </div>

      <section className="panel p-3 space-y-3">
        <div className="flex items-center justify-between">
          <div className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-cyan">
            Flight Replay
          </div>
          <span className="font-mono text-xs text-cyan">{replayTime.toFixed(2)} s</span>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            title={replayPlaying ? "Pause replay" : "Play replay"}
            onClick={() => {
              if (!replayPlaying && replayIndex >= maxReplayIndex) setReplayIndex(0);
              lastFrameRef.current = null;
              setReplayPlaying(!replayPlaying);
            }}
            className="icon-map-button"
          >
            {replayPlaying ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
          </button>
          <button
            type="button"
            title="Restart replay"
            onClick={() => {
              setReplayPlaying(false);
              setReplayIndex(0);
            }}
            className="icon-map-button"
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </button>
          <button
            type="button"
            title="Replay speed"
            onClick={() => setReplaySpeed(replaySpeed >= 4 ? 0.5 : replaySpeed * 2)}
            className="h-8 rounded-md border border-cyan/20 bg-bg/60 px-2 font-mono text-xs text-cyan"
          >
            {replaySpeed}x
          </button>
          <input
            type="range"
            min={0}
            max={maxReplayIndex}
            value={replayIndex}
            onChange={(event) => {
              setReplayPlaying(false);
              setReplayIndex(Number(event.target.value));
            }}
            className="min-w-0 flex-1 accent-cyan"
          />
        </div>
      </section>

      <div className="grid grid-cols-3 gap-1.5 rounded-lg border border-cyan/15 bg-panel p-1">
        {telemetryTabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            className={cn(
              "h-8 rounded-md text-[0.68rem] font-semibold uppercase tracking-wider transition-colors",
              activeTab === tab.id ? "bg-cyan/15 text-cyan" : "text-muted hover:bg-panel-2 hover:text-text",
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className="overflow-hidden rounded-lg border border-cyan/15 bg-panel">
        <PlotlyChart data={chart.data} layout={chart.layout} className="h-[390px] w-full" />
      </div>

      {activeTab === "threats" && (
        <ThreatSummary telemetry={telemetry} enemies={currentPreset?.enemies ?? []} />
      )}
    </section>
  );
}

function Header() {
  return (
    <div className="flex items-center justify-between gap-3">
      <header className="flex items-center gap-2">
        <span className="h-5 w-1 rounded-sm bg-violet" />
        <div>
          <h2 className="text-[0.74rem] font-semibold uppercase tracking-[0.18em] text-violet">
            Telemetry
          </h2>
          <p className="mt-0.5 text-xs text-muted">Time-series, estimator overlays, and threat ranges</p>
        </div>
      </header>
      <SlidersHorizontal className="h-4 w-4 text-violet" />
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel-soft px-3 py-2">
      <div className="text-[0.6rem] uppercase tracking-widest text-muted">{label}</div>
      <div className="mt-0.5 truncate font-mono text-sm font-semibold text-cyan">{value}</div>
    </div>
  );
}

function buildChart(
  tab: TelemetryTab,
  telemetry: NonNullable<ReturnType<typeof buildTelemetry>>,
) {
  const x = telemetry.t;
  if (tab === "overview") {
    return {
      data: [
        makeLine(x, telemetry.pos.map((p) => p[2]), "altitude", colors.cyan),
        makeLine(x, telemetry.trackingError, "tracking error", colors.amber),
        makeLine(x, telemetry.speed, "speed", colors.green),
      ],
      layout: baseLayout("Flight overview", "m / m-s"),
    };
  }

  if (tab === "position") {
    return {
      data: [
        makeLine(x, telemetry.pos.map((p) => p[0]), "x true", colors.cyan),
        makeLine(x, telemetry.activeWp.map((p) => p[0]), "x command", colors.cyan, "dash"),
        makeLine(x, telemetry.pos.map((p) => p[1]), "y true", colors.amber),
        makeLine(x, telemetry.activeWp.map((p) => p[1]), "y command", colors.amber, "dash"),
        makeLine(x, telemetry.pos.map((p) => p[2]), "z true", colors.green),
        makeLine(x, telemetry.activeWp.map((p) => p[2]), "z command", colors.green, "dash"),
      ],
      layout: baseLayout("Position tracking", "position [m]"),
    };
  }

  if (tab === "attitude") {
    return {
      data: [
        makeLine(x, telemetry.euler.map((p) => deg(p[0])), "roll", colors.cyan),
        makeLine(x, telemetry.euler.map((p) => deg(p[1])), "pitch", colors.amber),
        makeLine(x, telemetry.euler.map((p) => deg(p[2])), "yaw", colors.pink),
      ],
      layout: baseLayout("Attitude response", "angle [deg]"),
    };
  }

  if (tab === "control") {
    return {
      data: [
        makeLine(x, telemetry.thrust, "thrust", colors.amber),
        makeLine(x, telemetry.speed, "speed", colors.cyan),
        makeLine(x, telemetry.vel.map((p) => p[2]), "vertical velocity", colors.violet),
      ],
      layout: baseLayout("Control and speed", "N / m-s"),
    };
  }

  if (tab === "ekf") {
    return {
      data: [
        makeLine(x, telemetry.pos.map((p) => p[0]), "true x", colors.cyan),
        makeLine(x, telemetry.meas.map((p) => p[0]), "measured x", colors.red, "dot"),
        makeLine(x, telemetry.est.map((p) => p[0] ?? 0), "EKF x", colors.violet),
        makeLine(x, telemetry.pos.map((p) => p[1]), "true y", colors.amber),
        makeLine(x, telemetry.meas.map((p) => p[1]), "measured y", colors.pink, "dot"),
        makeLine(x, telemetry.est.map((p) => p[1] ?? 0), "EKF y", colors.green),
      ],
      layout: baseLayout("EKF true / measured / estimated overlay", "position [m]"),
    };
  }

  return {
    data: telemetry.threatSeries.map((series, index) => makeLine(
      x,
      series.sampledDistances.map((value) => value ?? Number.NaN),
      series.name,
      [colors.red, colors.amber, colors.violet, colors.pink][index % 4],
    )),
    layout: baseLayout("Threat range to ownship", "range [m]"),
  };
}

function ThreatSummary({
  telemetry,
  enemies,
}: {
  telemetry: NonNullable<ReturnType<typeof buildTelemetry>>;
  enemies: Array<{ name: string; det_r: number; leth_r: number }>;
}) {
  return (
    <div className="grid gap-2">
      {telemetry.threatSeries.length === 0 && (
        <div className="panel p-3 text-xs text-muted">No bandit tracks in this run.</div>
      )}
      {telemetry.threatSeries.map((series, index) => {
        const enemy = enemies[index];
        const detectionBreaches = series.distances.filter((range) => typeof range === "number" && enemy && range < enemy.det_r).length;
        const lethalBreaches = series.distances.filter((range) => typeof range === "number" && enemy && range < enemy.leth_r).length;
        return (
          <div key={series.name} className="panel-soft flex items-center justify-between gap-3 px-3 py-2 text-xs">
            <div className="flex items-center gap-2">
              <ShieldAlert className="h-3.5 w-3.5 text-red" />
              <span className="font-semibold text-text">{series.name}</span>
            </div>
            <div className="flex flex-wrap justify-end gap-3 font-mono">
              <span className="text-cyan">min {series.minRange === null ? "--" : `${round(series.minRange)} m`}</span>
              <span className="text-muted">t {series.minTime === null ? "--" : `${round(series.minTime, 1)} s`}</span>
              <span className={detectionBreaches ? "text-amber" : "text-green"}>det {detectionBreaches}</span>
              <span className={lethalBreaches ? "text-red" : "text-green"}>leth {lethalBreaches}</span>
            </div>
          </div>
        );
      })}
    </div>
  );
}
