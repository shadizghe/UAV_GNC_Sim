"use client";

import { PauseCircle, Play, RotateCcw, ShieldCheck } from "lucide-react";
import { useMemo, useState } from "react";
import { PlotlyChart } from "./PlotlyChart";
import { useAppStore } from "@/lib/store";
import type { MonteCarloConfig, MonteCarloResult, MonteCarloRun, Vec3, ZonePayload } from "@/lib/types";
import { cn } from "@/lib/utils";

const colors = {
  cyan: "#00d4ff",
  amber: "#ffc107",
  green: "#2ecc71",
  violet: "#b388ff",
  pink: "#ff4081",
  red: "#ff5252",
  text: "#e1e8f0",
};

const round = (value: number, digits = 2) => value.toFixed(digits);

const ring = (cx: number, cy: number, radius: number, samples = 96) => {
  const x: number[] = [];
  const y: number[] = [];
  for (let i = 0; i <= samples; i += 1) {
    const theta = (i / samples) * Math.PI * 2;
    x.push(cx + Math.cos(theta) * radius);
    y.push(cy + Math.sin(theta) * radius);
  }
  return { x, y };
};

function cloudChart(
  runs: MonteCarloRun[],
  result: MonteCarloResult | null,
  waypoints: Vec3[],
  zones: ZonePayload[],
) {
  const data: Array<Record<string, unknown>> = [];

  zones.forEach((zone) => {
    const circle = ring(zone.cx, zone.cy, zone.r);
    const color = zone.kind === "threat" ? "255,193,7" : "255,82,82";
    data.push({
      type: "scatter",
      mode: "lines",
      fill: "toself",
      x: circle.x,
      y: circle.y,
      line: { color: `rgba(${color},0.65)`, width: 1, dash: "dash" },
      fillcolor: `rgba(${color},0.10)`,
      hoverinfo: "skip",
      showlegend: false,
    });
  });

  runs.forEach((run) => {
    data.push({
      type: "scatter",
      mode: "lines",
      x: run.trajectory.map((p) => p[0]),
      y: run.trajectory.map((p) => p[1]),
      line: { color: "rgba(0,212,255,0.16)", width: 1 },
      hoverinfo: "skip",
      showlegend: false,
    });
  });

  if (waypoints.length > 1) {
    data.push({
      type: "scatter",
      mode: "lines+markers+text",
      x: waypoints.map((p) => p[0]),
      y: waypoints.map((p) => p[1]),
      text: waypoints.map((_, index) => `WPT-${index + 1}`),
      textposition: "top center",
      line: { color: colors.amber, width: 1.5, dash: "dash" },
      marker: { color: colors.amber, size: 9, symbol: "diamond" },
      textfont: { color: colors.amber, size: 10 },
      name: "Waypoints",
    });
  }

  result?.waypoints.forEach((wp, index) => {
    const cep50 = result.cep50_per_wp[index] ?? 0;
    const cep95 = result.cep95_per_wp[index] ?? 0;
    if (cep50 > 0) {
      const circle = ring(wp[0], wp[1], cep50);
      data.push({
        type: "scatter",
        mode: "lines",
        x: circle.x,
        y: circle.y,
        line: { color: colors.pink, width: 1.4, dash: "dot" },
        name: index === 0 ? "CEP50" : undefined,
        showlegend: index === 0,
        hovertemplate: `CEP50 WPT-${index + 1}: ${round(cep50)} m<extra></extra>`,
      });
    }
    if (cep95 > 0) {
      const circle = ring(wp[0], wp[1], cep95);
      data.push({
        type: "scatter",
        mode: "lines",
        x: circle.x,
        y: circle.y,
        line: { color: colors.violet, width: 1.4, dash: "dash" },
        name: index === 0 ? "CEP95" : undefined,
        showlegend: index === 0,
        hovertemplate: `CEP95 WPT-${index + 1}: ${round(cep95)} m<extra></extra>`,
      });
    }
  });

  const success = runs.filter((run) => run.success);
  const misses = runs.filter((run) => !run.success);
  if (success.length) {
    data.push({
      type: "scatter",
      mode: "markers",
      x: success.map((run) => run.endpoint[0]),
      y: success.map((run) => run.endpoint[1]),
      marker: { color: colors.green, size: 7, line: { color: "#060912", width: 1 } },
      name: `Success (${success.length})`,
    });
  }
  if (misses.length) {
    data.push({
      type: "scatter",
      mode: "markers",
      x: misses.map((run) => run.endpoint[0]),
      y: misses.map((run) => run.endpoint[1]),
      marker: { color: colors.red, size: 8, symbol: "x" },
      name: `Miss (${misses.length})`,
    });
  }

  return {
    data,
    layout: {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "#060912",
      font: { color: colors.text, family: "Inter, Segoe UI, sans-serif", size: 11 },
      margin: { l: 42, r: 16, t: 16, b: 36 },
      xaxis: {
        title: "East X [m]",
        scaleanchor: "y",
        scaleratio: 1,
        gridcolor: "rgba(0, 212, 255, 0.08)",
        zerolinecolor: "rgba(0, 212, 255, 0.18)",
      },
      yaxis: {
        title: "North Y [m]",
        gridcolor: "rgba(0, 212, 255, 0.08)",
        zerolinecolor: "rgba(0, 212, 255, 0.18)",
      },
      legend: { orientation: "h", y: 1.12, x: 0, font: { size: 10 } },
      hovermode: "closest",
    },
  };
}

function histogramChart(result: MonteCarloResult | null, successRadius: number) {
  const minMiss = (result?.min_miss_distances ?? []).filter((value): value is number => (
    typeof value === "number" && Number.isFinite(value)
  ));
  return {
    data: [
      {
        type: "histogram",
        x: result?.final_errors ?? [],
        nbinsx: 18,
        marker: { color: colors.cyan, line: { color: "#060912", width: 1 } },
        opacity: 0.9,
        name: "Final error",
      },
      ...(minMiss.length
        ? [{
            type: "histogram",
            x: minMiss,
            nbinsx: 18,
            marker: { color: colors.amber, line: { color: "#060912", width: 1 } },
            opacity: 0.68,
            name: "SAM min miss",
          }]
        : []),
    ],
    layout: {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "#060912",
      font: { color: colors.text, family: "Inter, Segoe UI, sans-serif", size: 11 },
      margin: { l: 42, r: 16, t: 16, b: 36 },
      xaxis: {
        title: "Error / min miss [m]",
        gridcolor: "rgba(0, 212, 255, 0.08)",
        zerolinecolor: "rgba(0, 212, 255, 0.18)",
      },
      yaxis: {
        title: "Runs",
        gridcolor: "rgba(0, 212, 255, 0.08)",
        zerolinecolor: "rgba(0, 212, 255, 0.18)",
      },
      shapes: [
        {
          type: "line",
          x0: successRadius,
          x1: successRadius,
          y0: 0,
          y1: 1,
          yref: "paper",
          line: { color: colors.green, width: 2, dash: "dash" },
        },
      ],
      barmode: "overlay",
      showlegend: minMiss.length > 0,
      bargap: 0.06,
    },
  };
}

export function MonteCarloPanel() {
  const {
    currentPreset,
    monteCarloConfig,
    monteCarloRuns,
    monteCarloResult,
    monteCarloRunning,
    monteCarloError,
    monteCarloProgress,
    runMonteCarlo,
    clearMonteCarlo,
  } = useAppStore();
  const [draft, setDraft] = useState<MonteCarloConfig>(monteCarloConfig);

  const cloud = useMemo(
    () => cloudChart(monteCarloRuns, monteCarloResult, currentPreset?.waypoints ?? [], currentPreset?.zones ?? []),
    [currentPreset?.waypoints, currentPreset?.zones, monteCarloResult, monteCarloRuns],
  );
  const histogram = useMemo(
    () => histogramChart(monteCarloResult, draft.success_radius),
    [draft.success_radius, monteCarloResult],
  );

  const latest = monteCarloRuns[monteCarloRuns.length - 1];
  const total = monteCarloResult?.total ?? draft.n_runs;
  const completed = monteCarloRuns.length;

  if (!currentPreset) return null;

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <header className="flex items-center gap-2">
          <span className="h-5 w-1 rounded-sm bg-pink" />
          <div>
            <h2 className="text-[0.74rem] font-semibold uppercase tracking-[0.18em] text-pink">
              Monte Carlo
            </h2>
            <p className="mt-0.5 text-xs text-muted">
              WebSocket-streamed dispersion sweep and CEP rings
            </p>
          </div>
        </header>
        <ShieldCheck className="h-4 w-4 text-pink" />
      </div>

      <section className="panel p-3 space-y-3">
        <div className="grid grid-cols-2 gap-2">
          <NumberField label="runs" value={draft.n_runs} min={1} max={200} step={1} onChange={(n_runs) => setDraft((prev) => ({ ...prev, n_runs: Math.round(n_runs) }))} />
          <NumberField label="seed" value={draft.seed_base} step={1} onChange={(seed_base) => setDraft((prev) => ({ ...prev, seed_base: Math.round(seed_base) }))} />
          <NumberField label="wind jitter" value={draft.wind_mean_jitter} min={0} step={0.05} onChange={(wind_mean_jitter) => setDraft((prev) => ({ ...prev, wind_mean_jitter }))} />
          <NumberField label="gust jitter" value={draft.wind_extra_gust} min={0} step={0.05} onChange={(wind_extra_gust) => setDraft((prev) => ({ ...prev, wind_extra_gust }))} />
          <NumberField label="mass jitter" value={draft.mass_jitter} min={0} step={0.01} onChange={(mass_jitter) => setDraft((prev) => ({ ...prev, mass_jitter }))} />
          <NumberField label="start xy" value={draft.start_xy_jitter} min={0} step={0.05} onChange={(start_xy_jitter) => setDraft((prev) => ({ ...prev, start_xy_jitter }))} />
          <NumberField label="imu bias" value={draft.imu_bias_std_deg} min={0} step={0.1} onChange={(imu_bias_std_deg) => setDraft((prev) => ({ ...prev, imu_bias_std_deg }))} />
          <NumberField label="success r" value={draft.success_radius} min={0.1} step={0.1} onChange={(success_radius) => setDraft((prev) => ({ ...prev, success_radius }))} />
          <NumberField label="missile jitter" value={draft.missile_speed_jitter} min={0} max={1} step={0.02} onChange={(missile_speed_jitter) => setDraft((prev) => ({ ...prev, missile_speed_jitter }))} />
          <NumberField label="seeker jitter" value={draft.seeker_noise_jitter} min={0} max={2} step={0.05} onChange={(seeker_noise_jitter) => setDraft((prev) => ({ ...prev, seeker_noise_jitter }))} />
          <NumberField label="warning jitter" value={draft.warning_delay_jitter} min={0} max={2} step={0.05} onChange={(warning_delay_jitter) => setDraft((prev) => ({ ...prev, warning_delay_jitter }))} />
          <button
            type="button"
            onClick={() => setDraft((prev) => ({ ...prev, survival_mode: !prev.survival_mode }))}
            className={cn(
              "mt-5 h-9 rounded-md border px-2 text-[0.66rem] font-semibold uppercase tracking-wider transition-colors",
              draft.survival_mode
                ? "border-amber/35 bg-amber/10 text-amber"
                : "border-cyan/15 bg-panel-2 text-muted hover:border-cyan/35",
            )}
          >
            Survival Gate
          </button>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => runMonteCarlo(draft)}
            disabled={monteCarloRunning}
            className="flex h-9 flex-1 items-center justify-center gap-2 rounded-md border border-pink/35 bg-pink/10 px-3 text-xs font-semibold uppercase tracking-wider text-pink transition-colors hover:bg-pink/15 disabled:cursor-not-allowed disabled:opacity-50"
          >
            {monteCarloRunning ? <PauseCircle className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
            {monteCarloRunning ? "Streaming" : "Run Sweep"}
          </button>
          <button
            type="button"
            title="Clear sweep"
            onClick={clearMonteCarlo}
            disabled={monteCarloRunning || (!monteCarloResult && monteCarloRuns.length === 0)}
            className="icon-map-button"
          >
            <RotateCcw className="h-3.5 w-3.5" />
          </button>
        </div>

        <div className="h-2 overflow-hidden rounded-full bg-bg">
          <div
            className="h-full bg-pink transition-[width]"
            style={{ width: `${Math.round(monteCarloProgress * 100)}%` }}
          />
        </div>
        <div className="flex items-center justify-between font-mono text-[0.68rem] text-muted">
          <span>{completed} / {total} runs</span>
          <span>{latest ? `last error ${round(latest.final_error)} m` : "ready"}</span>
        </div>
        {monteCarloError && (
          <div className="rounded-md border border-red/35 bg-red/10 px-3 py-2 text-xs text-red">
            {monteCarloError}
          </div>
        )}
      </section>

      <div className="grid grid-cols-4 gap-2">
        <Stat label="Success" value={monteCarloResult ? `${round(monteCarloResult.success_rate * 100, 1)}%` : "--"} />
        <Stat label="Final err" value={monteCarloResult ? `${round(monteCarloResult.final_error_mean)} m` : "--"} />
        <Stat label="RMS err" value={monteCarloResult ? `${round(monteCarloResult.rms_error_mean)} m` : "--"} />
        <Stat label="Mean time" value={monteCarloResult ? `${round(monteCarloResult.mission_time_mean, 1)} s` : "--"} />
      </div>
      <div className="grid grid-cols-4 gap-2">
        <Stat label="Survive SAM" value={monteCarloResult ? `${round((monteCarloResult.survival_rate ?? 0) * 100, 1)}%` : "--"} />
        <Stat label="SAM Pk" value={monteCarloResult ? `${round((monteCarloResult.sam_kill_rate ?? 0) * 100, 1)}%` : "--"} />
        <Stat label="Min miss" value={monteCarloResult ? `${round(monteCarloResult.mean_min_miss_distance ?? 0)} m` : "--"} />
        <Stat label="Evasion" value={monteCarloResult ? `${round((monteCarloResult.evasion_rate ?? 0) * 100, 1)}%` : "--"} />
      </div>

      <div className="overflow-hidden rounded-lg border border-cyan/15 bg-panel">
        <PlotlyChart data={cloud.data} layout={cloud.layout} className="h-[420px] w-full" />
      </div>

      <div className="overflow-hidden rounded-lg border border-cyan/15 bg-panel">
        <PlotlyChart data={histogram.data} layout={histogram.layout} className="h-[240px] w-full" />
      </div>

      <CepTable result={monteCarloResult} />
    </section>
  );
}

function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step = 0.1,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
}) {
  return (
    <label className="space-y-1 text-xs text-muted">
      <span>{label}</span>
      <input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        min={min}
        max={max}
        step={step}
        onChange={(event) => onChange(Number(event.target.value))}
        className="field font-mono"
      />
    </label>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="panel-soft px-3 py-2">
      <div className="text-[0.6rem] uppercase tracking-widest text-muted">{label}</div>
      <div className="mt-0.5 truncate font-mono text-sm font-semibold text-pink">{value}</div>
    </div>
  );
}

function CepTable({ result }: { result: MonteCarloResult | null }) {
  if (!result) {
    return (
      <div className="panel p-3 text-xs text-muted">
        Run a sweep to calculate CEP50 and CEP95 per waypoint.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-cyan/15">
      <table className="w-full text-left text-xs">
        <thead className="bg-panel-2 text-[0.62rem] uppercase tracking-widest text-muted">
          <tr>
            <th className="px-3 py-2">Waypoint</th>
            <th className="px-3 py-2">CEP50</th>
            <th className="px-3 py-2">CEP95</th>
          </tr>
        </thead>
        <tbody>
          {result.waypoints.map((_, index) => (
            <tr
              key={index}
              className={cn("border-t border-cyan/10", index % 2 === 0 ? "bg-panel/70" : "bg-panel-2/45")}
            >
              <td className="px-3 py-2 font-semibold text-text">WPT-{index + 1}</td>
              <td className="px-3 py-2 font-mono text-pink">{round(result.cep50_per_wp[index] ?? 0)} m</td>
              <td className="px-3 py-2 font-mono text-violet">{round(result.cep95_per_wp[index] ?? 0)} m</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
