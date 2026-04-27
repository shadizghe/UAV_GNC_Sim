"use client";

import { useEffect } from "react";
import { CheckCircle2, Loader2 } from "lucide-react";
import { useAppStore } from "@/lib/store";
import { cn } from "@/lib/utils";

export function PresetPicker() {
  const {
    presetSummaries,
    currentPreset,
    loadingPreset,
    fetchPresetList,
    loadPreset,
  } = useAppStore();

  useEffect(() => {
    if (presetSummaries.length === 0) {
      void fetchPresetList();
    }
  }, [presetSummaries.length, fetchPresetList]);

  return (
    <section className="space-y-3">
      <header className="flex items-center gap-2">
        <span className="w-1 h-4 bg-cyan rounded-sm" />
        <h3 className="text-[0.74rem] tracking-[0.18em] uppercase text-cyan font-semibold">
          Mission Scenario
        </h3>
      </header>

      <div className="grid grid-cols-1 gap-2">
        {presetSummaries.length === 0 && (
          <div className="text-xs text-muted flex items-center gap-2 py-2">
            <Loader2 className="w-3.5 h-3.5 animate-spin" />
            Loading presets...
          </div>
        )}

        {presetSummaries.map((preset) => {
          const active = currentPreset?.label === preset.label;
          return (
            <button
              key={preset.label}
              type="button"
              onClick={() => loadPreset(preset.label)}
              disabled={loadingPreset}
              className={cn(
                "text-left px-3 py-2.5 rounded-md text-sm transition-colors border",
                active
                  ? "bg-cyan/10 border-cyan/40 text-cyan"
                  : "bg-panel hover:bg-panel-2 text-text/85 border-cyan/10 hover:border-cyan/25",
              )}
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <div className="flex items-center gap-2">
                    <span className="font-semibold">{preset.label}</span>
                    <span className="pill-violet">{preset.tag}</span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-[0.72rem] leading-snug text-muted">
                    {preset.description}
                  </p>
                </div>
                {active && <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-green" />}
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                <span className="pill-cyan">{preset.n_waypoints} WPT</span>
                <span className="pill-amber">{preset.n_zones} ZONE</span>
                <span className="pill-red">{preset.n_enemies} BANDIT</span>
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}
