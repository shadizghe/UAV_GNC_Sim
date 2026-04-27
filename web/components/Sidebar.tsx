"use client";

import { PresetPicker } from "./PresetPicker";
import { useAppStore } from "@/lib/store";
import { AnimatePresence, motion, panelReveal } from "@/lib/motion";

export function Sidebar() {
  const { simResult, currentPreset } = useAppStore();

  return (
    <aside className="w-full shrink-0 border-b border-cyan/15 bg-bg/60 backdrop-blur-md
                      px-4 py-5 space-y-6 lg:h-[calc(100vh-3.5rem)] lg:w-[300px]
                      lg:overflow-y-auto lg:border-b-0 lg:border-r">
      <div className="text-[0.66rem] tracking-[0.18em] uppercase text-cyan font-semibold">
        Flight Configuration
      </div>

      <PresetPicker />

      <AnimatePresence mode="popLayout">
        {simResult && currentPreset && (
          <motion.section
            layout
            key="perf"
            variants={panelReveal}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="space-y-2"
          >
            <header className="flex items-center gap-2">
              <span className="w-1 h-4 bg-amber rounded-sm" />
              <h3 className="text-[0.74rem] tracking-[0.18em] uppercase text-amber font-semibold">
                Performance
              </h3>
            </header>
            <div className="grid grid-cols-2 gap-2">
              <Stat label="Reached" value={`${simResult.waypoints_reached} / ${simResult.waypoints_total}`} />
              <Stat label="RMS error"  value={`${simResult.rms_position_error.toFixed(2)} m`} />
              <Stat label="Final err"  value={`${simResult.final_position_error.toFixed(2)} m`} />
              <Stat label="Steps"      value={simResult.t.length.toString()} />
            </div>
          </motion.section>
        )}

        {simResult?.estimator_used && (
          <motion.section
            layout
            key="ekf"
            variants={panelReveal}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="space-y-2"
          >
            <header className="flex items-center gap-2">
              <span className="w-1 h-4 bg-violet rounded-sm" />
              <h3 className="text-[0.74rem] tracking-[0.18em] uppercase text-violet font-semibold">
                EKF Estimator
              </h3>
            </header>
            <div className="grid grid-cols-2 gap-2">
              <Stat label="Raw GPS"   value={`${(simResult.raw_pos_rms * 100).toFixed(2)} cm`} />
              <Stat label="EKF est"   value={`${(simResult.ekf_pos_rms * 100).toFixed(2)} cm`}
                    highlight />
            </div>
            <div className="text-[0.7rem] text-muted leading-snug pt-1">
              EKF cuts position noise by{" "}
              <span className="text-violet font-semibold">
                {simResult.raw_pos_rms > 0
                  ? Math.round((1 - simResult.ekf_pos_rms / simResult.raw_pos_rms) * 100)
                  : 0}
                %
              </span>{" "}
              vs raw measurements.
            </div>
          </motion.section>
        )}
      </AnimatePresence>
    </aside>
  );
}

function Stat({ label, value, highlight }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="panel-soft px-3 py-2">
      <div className="text-[0.62rem] tracking-widest uppercase text-muted">{label}</div>
      <div className={"text-sm font-semibold " + (highlight ? "text-violet" : "text-cyan")}>
        {value}
      </div>
    </div>
  );
}
