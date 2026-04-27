"use client";

import dynamic from "next/dynamic";
import { TopBar } from "@/components/TopBar";
import { Sidebar } from "@/components/Sidebar";
import { WorkspacePanel } from "@/components/WorkspacePanel";
import { CommandPalette } from "@/components/CommandPalette";
import { TutorialOverlay } from "@/components/TutorialOverlay";
import { useAppStore } from "@/lib/store";

// Three.js / WebGL must render client-side; `ssr: false` keeps Next from
// trying to instantiate the canvas during static prerender.
const Scene3D = dynamic(
  () => import("@/components/Scene3D").then((m) => m.Scene3D),
  { ssr: false },
);

export default function Page() {
  const { simRunning, simError, simResult } = useAppStore();

  return (
    <div className="min-h-screen lg:h-screen flex flex-col bg-bg">
      <TopBar />
      <div className="flex flex-1 flex-col overflow-y-auto lg:flex-row lg:overflow-hidden">
        <Sidebar />
        <main className="relative h-[440px] min-w-0 flex-none lg:h-auto lg:flex-1">
          <div className="absolute inset-0">
            <Scene3D />
          </div>

          <div className="absolute top-4 left-4 panel px-3 py-2 text-[0.72rem] tracking-widest uppercase text-muted">
            World Frame | ENU | units = m
          </div>

          {simResult && (
            <div className="absolute top-4 right-4 panel px-4 py-2.5 text-xs space-y-1.5">
              <div className="flex items-center justify-between gap-6">
                <span className="text-muted">Sim time</span>
                <span className="font-mono text-cyan">
                  {simResult.t[simResult.t.length - 1].toFixed(2)} s
                </span>
              </div>
              <div className="flex items-center justify-between gap-6">
                <span className="text-muted">Samples</span>
                <span className="font-mono text-cyan">{simResult.t.length}</span>
              </div>
              <div className="flex items-center justify-between gap-6">
                <span className="text-muted">Reached</span>
                <span className="font-mono text-amber">
                  {simResult.waypoints_reached} / {simResult.waypoints_total}
                </span>
              </div>
            </div>
          )}

          {simRunning && (
            <div className="absolute bottom-6 left-1/2 -translate-x-1/2 panel px-4 py-2 text-xs tracking-widest uppercase text-amber">
              Running closed-loop simulation...
            </div>
          )}

          {simError && (
            <div className="absolute bottom-6 left-1/2 -translate-x-1/2 panel border-red/40 px-4 py-2 text-xs text-red max-w-md text-center">
              {simError}
            </div>
          )}
        </main>
        <WorkspacePanel />
      </div>

      {/* Global ⌘K / Ctrl+K command palette — modal overlay. */}
      <CommandPalette />

      {/* Global ? / F1 step-by-step tutorial overlay. */}
      <TutorialOverlay />
    </div>
  );
}
