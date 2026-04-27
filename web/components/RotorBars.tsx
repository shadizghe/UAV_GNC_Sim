"use client";

import { useMemo } from "react";
import { useAppStore } from "@/lib/store";
import { cn } from "@/lib/utils";

/**
 * Per-rotor thrust visualisation — 4 bars (front-right, back-right,
 * back-left, front-left) showing the *delivered* thrust each rotor is
 * producing at the current replay frame, plus a faint outline showing
 * what the controller *commanded* (which is what the rotor would
 * produce if no fault were active).
 *
 * Reads from the live sim result; if no sim has run yet, shows zeroes.
 * When a motor fault is active during the current frame, the affected
 * bar is tinted red and labelled FAIL.
 */

const ROTORS = [
  { id: 0, label: "FR", color: "#ff5252" },
  { id: 1, label: "BR", color: "#ff8c42" },
  { id: 2, label: "BL", color: "#ffc107" },
  { id: 3, label: "FL", color: "#7fdfff" },
] as const;

export function RotorBars() {
  const { simResult, replayIndex, faultConfig } = useAppStore();

  const frame = simResult
    ? Math.max(0, Math.min(replayIndex, simResult.pos.length - 1))
    : 0;
  const tNow = simResult ? simResult.t[frame] : 0;

  const cmd = simResult?.motor_cmd?.[frame] ?? [0, 0, 0, 0];
  const actual = simResult?.motor_actual?.[frame] ?? [0, 0, 0, 0];

  // Pick a normaliser: highest command across the whole run, or fallback.
  const peak = useMemo(() => {
    if (!simResult?.motor_cmd?.length) return 10;
    let p = 0;
    for (const row of simResult.motor_cmd) {
      for (const v of row) {
        const a = Math.abs(v);
        if (a > p) p = a;
      }
    }
    return Math.max(p, 1.5);
  }, [simResult]);

  // Which rotors are failed *right now*?
  const failed = new Set<number>();
  for (const f of faultConfig.motor) {
    if (f.t_start <= tNow && tNow <= f.t_end && f.severity < 1) {
      failed.add(f.rotor);
    }
  }

  return (
    <section className="space-y-3">
      <header className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="h-5 w-1 rounded-sm bg-cyan" />
          <h3 className="text-[0.74rem] font-semibold uppercase tracking-[0.18em] text-cyan">
            Rotor Telemetry
          </h3>
        </div>
        <span className="font-mono text-[0.66rem] text-muted">
          peak {peak.toFixed(1)} N
        </span>
      </header>

      <div className="panel grid grid-cols-4 gap-1 p-3">
        {ROTORS.map((r) => {
          const cmdN = cmd[r.id] ?? 0;
          const actN = actual[r.id] ?? 0;
          const cmdPct = clamp01(Math.abs(cmdN) / peak);
          const actPct = clamp01(Math.abs(actN) / peak);
          const isFailed = failed.has(r.id);
          return (
            <div key={r.id} className="space-y-1">
              <div className="flex items-center justify-between gap-1">
                <span
                  className="text-[0.66rem] font-bold tracking-wide"
                  style={{ color: isFailed ? "#ff5252" : r.color }}
                >
                  {r.label}
                </span>
                <span className={cn(
                  "font-mono text-[0.6rem]",
                  isFailed ? "text-red" : "text-muted",
                )}>
                  {actN.toFixed(1)}
                </span>
              </div>
              <div className="relative h-20 w-full overflow-hidden rounded-sm border border-cyan/15 bg-bg/45">
                {/* Commanded outline */}
                <div
                  className="absolute bottom-0 left-0 right-0 border-t-2 border-dashed"
                  style={{
                    height: `${cmdPct * 100}%`,
                    borderColor: r.color + "55",
                  }}
                />
                {/* Actual fill */}
                <div
                  className="absolute bottom-0 left-0 right-0 transition-[height] duration-75"
                  style={{
                    height: `${actPct * 100}%`,
                    background: isFailed
                      ? "linear-gradient(to top, #ff525288 0%, #ff525244 100%)"
                      : `linear-gradient(to top, ${r.color}aa 0%, ${r.color}33 100%)`,
                  }}
                />
                {isFailed && (
                  <div className="absolute inset-0 grid place-items-center">
                    <span className="rounded bg-red/60 px-1.5 py-0.5 text-[0.55rem] font-bold uppercase tracking-widest text-bg">
                      Fail
                    </span>
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <p className="text-[0.66rem] leading-snug text-muted">
        Solid fill = delivered thrust · dashed outline = commanded thrust.
        Discrepancy reveals fault-injection compensation.
      </p>
    </section>
  );
}

function clamp01(x: number) {
  if (Number.isNaN(x)) return 0;
  return x < 0 ? 0 : x > 1 ? 1 : x;
}
