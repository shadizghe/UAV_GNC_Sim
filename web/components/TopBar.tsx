"use client";

import { Activity, Cpu, HelpCircle, Wifi } from "lucide-react";
import { useAppStore } from "@/lib/store";

export function TopBar() {
  const { simResult, simRunning, currentPreset } = useAppStore();

  const statusText = simRunning
    ? "RUNNING"
    : simResult
      ? "NOMINAL"
      : "IDLE";
  const statusClass = simRunning
    ? "pill-amber"
    : simResult
      ? "pill-green"
      : "pill-cyan";

  return (
    <header className="relative z-20 flex min-h-14 flex-wrap items-center gap-x-5 gap-y-2 border-b border-cyan/15 bg-bg/80 px-4 py-2 backdrop-blur-md lg:h-14 lg:flex-nowrap lg:px-5 lg:py-0">
      {/* Brand */}
      <div className="flex items-center gap-2.5">
        <div className="w-8 h-8 rounded-md bg-panel border border-cyan/30 grid place-items-center shadow-glow">
          <span className="text-cyan font-bold text-sm tracking-tight">DFC</span>
        </div>
        <div className="leading-tight">
          <div className="text-sm font-semibold tracking-tight">
            Drone Flight Control
          </div>
          <div className="text-[0.68rem] text-muted tracking-[0.18em] uppercase">
            GNC · 6-DOF · cascaded PID + EKF
          </div>
        </div>
      </div>

      {/* Center: current scenario */}
      <div className="ml-0 flex items-center gap-2 lg:ml-8">
        <span className="text-[0.66rem] text-muted tracking-widest uppercase">Mission</span>
        <span className="text-sm font-semibold text-cyan">
          {currentPreset?.label ?? "—"}
        </span>
        {currentPreset && (
          <span className="pill-violet">{currentPreset.tag}</span>
        )}
      </div>

      {/* Right: live indicators */}
      <div className="ml-0 flex flex-wrap items-center gap-3 text-[0.7rem] tracking-widest uppercase text-muted lg:ml-auto">
        <button
          type="button"
          onClick={() => window.dispatchEvent(new CustomEvent("tutorial:open"))}
          className="flex items-center gap-1.5 rounded-md border border-cyan/20 bg-bg/40 px-2 py-1 normal-case text-[0.66rem] tracking-normal text-muted transition-colors hover:border-cyan/45 hover:text-cyan"
          title="Open the step-by-step tutorial (?)"
        >
          <HelpCircle className="h-3.5 w-3.5 text-cyan" />
          <span>Tutorial</span>
          <kbd className="rounded border border-cyan/30 bg-panel px-1 font-mono text-cyan">?</kbd>
        </button>
        <button
          type="button"
          onClick={() => window.dispatchEvent(new CustomEvent("palette:open"))}
          className="hidden items-center gap-1.5 rounded-md border border-cyan/20 bg-bg/40 px-2 py-1 normal-case text-[0.66rem] tracking-normal text-muted transition-colors hover:border-cyan/45 hover:text-cyan lg:flex"
          title="Open the command palette (Ctrl+K)"
        >
          <kbd className="rounded border border-cyan/30 bg-panel px-1 font-mono text-cyan">Ctrl</kbd>
          <span>+</span>
          <kbd className="rounded border border-cyan/30 bg-panel px-1 font-mono text-cyan">K</kbd>
          <span className="ml-1">command palette</span>
        </button>
        <span className="flex items-center gap-1.5">
          <Wifi className="w-3.5 h-3.5 text-green" />
          API
        </span>
        <span className="flex items-center gap-1.5">
          <Cpu className="w-3.5 h-3.5 text-cyan" />
          dt = 10 ms
        </span>
        <span className={statusClass + " gap-1.5"}>
          <Activity className="w-3 h-3" /> {statusText}
        </span>
      </div>
    </header>
  );
}
