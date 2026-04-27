"use client";

import { Activity, BarChart3, Box, Cpu, Map, Route, Wrench } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";
import { AutonomyPanel } from "./AutonomyPanel";
import { FaultInjectionPanel } from "./FaultInjectionPanel";
import { MissionPlanPanel } from "./MissionPlanPanel";
import { MonteCarloPanel } from "./MonteCarloPanel";
import { RotorBars } from "./RotorBars";
import { SimulationRoomPanel } from "./SimulationRoomPanel";
import { TacticalMapPanel } from "./TacticalMapPanel";
import { TelemetryPanel } from "./TelemetryPanel";
import { cn } from "@/lib/utils";

type WorkspaceTab =
  | "mission" | "autonomy" | "room" | "faults" | "tactical" | "telemetry" | "monte-carlo";

const tabs: Array<{ id: WorkspaceTab; label: string; icon: ReactNode }> = [
  { id: "tactical",    label: "Tactical",    icon: <Map   className="h-3.5 w-3.5" /> },
  { id: "autonomy",    label: "Autonomy",    icon: <Cpu   className="h-3.5 w-3.5" /> },
  { id: "room",        label: "Sim Room",    icon: <Box   className="h-3.5 w-3.5" /> },
  { id: "faults",      label: "Faults",      icon: <Wrench className="h-3.5 w-3.5" /> },
  { id: "mission",     label: "Mission",     icon: <Route className="h-3.5 w-3.5" /> },
  { id: "telemetry",   label: "Telemetry",   icon: <BarChart3 className="h-3.5 w-3.5" /> },
  { id: "monte-carlo", label: "Monte Carlo", icon: <Activity className="h-3.5 w-3.5" /> },
];

export function WorkspacePanel() {
  const [activeTab, setActiveTab] = useState<WorkspaceTab>("mission");

  return (
    <aside className="w-full shrink-0 border-t border-cyan/15 bg-bg/70 backdrop-blur-md lg:h-[calc(100vh-3.5rem)] lg:w-[620px] lg:overflow-y-auto lg:border-l lg:border-t-0">
      <div className="sticky top-0 z-20 border-b border-cyan/15 bg-bg/90 px-4 py-3 backdrop-blur-md">
        <div className="grid grid-cols-3 gap-1.5 rounded-lg border border-cyan/15 bg-panel p-1 sm:grid-cols-7">
          {tabs.map((tab) => {
            const active = activeTab === tab.id;
            return (
              <button
                key={tab.id}
                type="button"
                onClick={() => setActiveTab(tab.id)}
                className={cn(
                  "flex h-9 items-center justify-center gap-1.5 rounded-md text-[0.62rem] font-semibold uppercase tracking-wider transition-colors",
                  active ? "bg-cyan/15 text-cyan" : "text-muted hover:bg-panel-2 hover:text-text",
                )}
              >
                {tab.icon}
                {tab.label}
              </button>
            );
          })}
        </div>
      </div>

      <div className="px-4 py-5">
        {activeTab === "mission"     && <MissionPlanPanel />}
        {activeTab === "autonomy"    && <AutonomyPanel />}
        {activeTab === "room"        && <SimulationRoomPanel />}
        {activeTab === "faults"      && (
          <div className="space-y-6">
            <FaultInjectionPanel />
            <RotorBars />
          </div>
        )}
        {activeTab === "tactical"    && <TacticalMapPanel expanded />}
        {activeTab === "telemetry"   && <TelemetryPanel />}
        {activeTab === "monte-carlo" && <MonteCarloPanel />}
      </div>
    </aside>
  );
}
