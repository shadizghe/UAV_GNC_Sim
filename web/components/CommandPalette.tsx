"use client";

import {
  BookOpen, ChevronRight, Cloud, CloudSun, Crosshair, Eye, Layers, Map, Moon,
  Play, Radar, Route, Rss, ScanLine, Search, Sparkles, Sun, Sunrise,
  Trash2, Volume2, VolumeX, Wrench, X,
} from "lucide-react";
import { ReactNode, useEffect, useMemo, useRef, useState } from "react";
import { useAppStore } from "@/lib/store";
import { cn } from "@/lib/utils";
import { playClick, playWhoosh } from "@/lib/sounds";
import {
  AnimatePresence,
  motion,
  overlayFade,
  paletteReveal,
} from "@/lib/motion";

/**
 * Command palette — ⌘K / Ctrl+K opens a modal with fuzzy-searchable
 * actions: load preset, switch room mode, toggle visual layers, run
 * the sim, clear faults, etc.  Inspired by VS Code / Linear / Raycast.
 *
 * All actions read from / write to the zustand store, so adding a new
 * action is just one entry in the `useActions` hook below.
 */

interface PaletteAction {
  id: string;
  label: string;
  hint?: string;
  group: string;
  icon: ReactNode;
  keywords?: string[];
  run: () => void;
}

export function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef  = useRef<HTMLDivElement>(null);

  // Build actions whenever store state that influences them changes.
  const actions = useActions(() => {
    setOpen(false);
    setQuery("");
  });

  // Filter
  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return actions;
    return actions.filter((a) => {
      const hay = (
        a.label + " " + (a.hint ?? "") + " " + (a.keywords ?? []).join(" ")
      ).toLowerCase();
      return hay.includes(q);
    });
  }, [actions, query]);

  // Keep selection in range
  useEffect(() => { setSelected(0); }, [query, open]);

  // External open trigger (e.g. TopBar button) dispatches `palette:open`.
  useEffect(() => {
    const onOpen = () => {
      setOpen((o) => {
        if (!o) playWhoosh();
        return true;
      });
    };
    window.addEventListener("palette:open", onOpen);
    return () => window.removeEventListener("palette:open", onOpen);
  }, []);

  // Global ⌘K / Ctrl+K toggle
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const isCmdK = (e.ctrlKey || e.metaKey) && (e.key === "k" || e.key === "K");
      if (isCmdK) {
        e.preventDefault();
        setOpen((o) => {
          if (!o) playWhoosh();
          return !o;
        });
        return;
      }
      if (!open) return;
      if (e.key === "Escape") {
        e.preventDefault();
        setOpen(false);
      } else if (e.key === "ArrowDown") {
        e.preventDefault();
        setSelected((s) => Math.min(filtered.length - 1, s + 1));
      } else if (e.key === "ArrowUp") {
        e.preventDefault();
        setSelected((s) => Math.max(0, s - 1));
      } else if (e.key === "Enter") {
        e.preventDefault();
        const action = filtered[selected];
        if (action) {
          playClick();
          action.run();
        }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, filtered, selected]);

  // Auto-focus input when opening
  useEffect(() => {
    if (open) {
      const id = window.setTimeout(() => inputRef.current?.focus(), 0);
      return () => window.clearTimeout(id);
    }
  }, [open]);

  // Auto-scroll selected into view
  useEffect(() => {
    const list = listRef.current;
    if (!list) return;
    const el = list.querySelector<HTMLButtonElement>(`[data-idx="${selected}"]`);
    el?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  // Group filtered actions by their `group` field for the dropdown header.
  const groups = useMemo(() => {
    const out: Array<{ group: string; items: PaletteAction[] }> = [];
    for (const a of filtered) {
      let g = out.find((x) => x.group === a.group);
      if (!g) { g = { group: a.group, items: [] }; out.push(g); }
      g.items.push(a);
    }
    return out;
  }, [filtered]);

  // Flat index used to highlight `selected` across groups
  let flatIdx = -1;

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          variants={overlayFade}
          initial="hidden"
          animate="visible"
          exit="exit"
          className="fixed inset-0 z-50 flex items-start justify-center bg-bg/70 px-4 pt-24 backdrop-blur-sm"
          onClick={() => setOpen(false)}
        >
          <motion.div
            variants={paletteReveal}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="panel w-full max-w-xl overflow-hidden"
            onClick={(e) => e.stopPropagation()}
          >
        <div className="flex items-center gap-2 border-b border-cyan/15 px-3.5 py-2.5">
          <Search className="h-4 w-4 text-cyan" />
          <input
            ref={inputRef}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Type a command, scenario, or toggle…"
            className="flex-1 bg-transparent text-sm text-text outline-none placeholder:text-muted"
          />
          <kbd className="rounded border border-cyan/20 px-1.5 py-0.5 text-[0.6rem] font-mono text-muted">
            ESC
          </kbd>
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="grid h-6 w-6 place-items-center rounded text-muted hover:bg-panel-2 hover:text-text"
            aria-label="Close command palette"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>

        <div ref={listRef} className="max-h-[55vh] overflow-y-auto">
          {filtered.length === 0 ? (
            <div className="px-4 py-8 text-center text-xs text-muted">
              No matching actions.  Try a preset name or "toggle".
            </div>
          ) : (
            groups.map((g) => (
              <div key={g.group}>
                <div className="border-y border-cyan/10 bg-bg/60 px-3 py-1 text-[0.6rem] font-semibold uppercase tracking-[0.18em] text-muted">
                  {g.group}
                </div>
                {g.items.map((a) => {
                  flatIdx++;
                  const isActive = flatIdx === selected;
                  const idx = flatIdx;
                  return (
                    <button
                      key={a.id}
                      type="button"
                      data-idx={idx}
                      onMouseEnter={() => setSelected(idx)}
                      onClick={() => { playClick(); a.run(); }}
                      className={cn(
                        "flex w-full items-center gap-3 px-3.5 py-2 text-left transition-colors",
                        isActive ? "bg-cyan/10" : "hover:bg-panel-2",
                      )}
                    >
                      <span className={cn(
                        "grid h-7 w-7 shrink-0 place-items-center rounded-md border",
                        isActive
                          ? "border-cyan/40 bg-cyan/15 text-cyan"
                          : "border-cyan/15 bg-bg/50 text-muted",
                      )}>
                        {a.icon}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className={cn(
                          "block text-sm",
                          isActive ? "text-cyan font-semibold" : "text-text",
                        )}>
                          {a.label}
                        </span>
                        {a.hint && (
                          <span className="block truncate text-[0.7rem] text-muted">
                            {a.hint}
                          </span>
                        )}
                      </span>
                      <ChevronRight className={cn(
                        "h-3.5 w-3.5 shrink-0 transition-opacity",
                        isActive ? "opacity-100 text-cyan" : "opacity-0",
                      )} />
                    </button>
                  );
                })}
              </div>
            ))
          )}
        </div>

        <div className="flex items-center justify-between gap-3 border-t border-cyan/15 bg-bg/60 px-3 py-1.5 text-[0.62rem] text-muted">
          <div className="flex items-center gap-3">
            <span className="flex items-center gap-1">
              <kbd className="rounded border border-cyan/20 px-1 font-mono">↑</kbd>
              <kbd className="rounded border border-cyan/20 px-1 font-mono">↓</kbd>
              navigate
            </span>
            <span className="flex items-center gap-1">
              <kbd className="rounded border border-cyan/20 px-1 font-mono">⏎</kbd>
              select
            </span>
          </div>
          <span className="font-mono">
            <kbd className="rounded border border-cyan/20 px-1">Ctrl</kbd>
            {" + "}
            <kbd className="rounded border border-cyan/20 px-1">K</kbd>
            {" anywhere to reopen"}
          </span>
        </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

// --------------------------------------------------------------------- //
// Action catalogue                                                      //
// --------------------------------------------------------------------- //

function useActions(onRun: () => void): PaletteAction[] {
  const store = useAppStore();
  const fire = (fn: () => void) => () => { fn(); onRun(); };

  const actions: PaletteAction[] = [];

  // ---- Help ---- //
  actions.push({
    id: "help:tutorial",
    group: "Help",
    label: "Open step-by-step tutorial",
    hint: "Walkthrough of every panel, shortcut, and workflow",
    icon: <BookOpen className="h-3.5 w-3.5" />,
    keywords: ["help", "guide", "walkthrough", "how to", "intro", "onboarding"],
    run: fire(() => window.dispatchEvent(new CustomEvent("tutorial:open"))),
  });

  // ---- Mission scenarios ---- //
  for (const preset of store.presetSummaries) {
    actions.push({
      id: `preset:${preset.label}`,
      group: "Mission scenarios",
      label: `Load: ${preset.label}`,
      hint: preset.description,
      icon: <Route className="h-3.5 w-3.5" />,
      keywords: [preset.tag, "preset", "scenario", "mission"],
      run: fire(() => store.loadPreset(preset.label)),
    });
  }

  // ---- Sim controls ---- //
  actions.push({
    id: "sim:run",
    group: "Simulation",
    label: "Run simulation",
    hint: "Submit current mission to the backend simulator",
    icon: <Play className="h-3.5 w-3.5" />,
    keywords: ["start", "go", "execute"],
    run: fire(() => store.runSimulation()),
  });
  actions.push({
    id: "sim:replay-restart",
    group: "Simulation",
    label: "Restart playback",
    hint: "Jump replay scrubber to t = 0",
    icon: <Rss className="h-3.5 w-3.5" />,
    keywords: ["scrub", "rewind", "begin"],
    run: fire(() => store.setReplayIndex(0)),
  });
  actions.push({
    id: "sim:replay-toggle",
    group: "Simulation",
    label: store.replayPlaying ? "Pause replay" : "Play replay",
    icon: <Play className="h-3.5 w-3.5" />,
    keywords: ["space", "playback"],
    run: fire(() => store.setReplayPlaying(!store.replayPlaying)),
  });

  // ---- Faults ---- //
  actions.push({
    id: "faults:clear",
    group: "Faults",
    label: "Clear all injected faults",
    hint: "Remove every motor failure / IMU dropout / GPS-denied window",
    icon: <Trash2 className="h-3.5 w-3.5" />,
    keywords: ["wipe", "reset", "clean"],
    run: fire(() => store.clearFaults()),
  });

  // ---- Mission edits ---- //
  actions.push({
    id: "mission:reset",
    group: "Mission",
    label: "Reset mission to preset baseline",
    hint: "Discard waypoint / zone / bandit edits",
    icon: <Crosshair className="h-3.5 w-3.5" />,
    keywords: ["undo", "discard", "revert"],
    run: fire(() => store.resetMissionPlan()),
  });

  // ---- Room view: lighting modes ---- //
  const roomModes: Array<{ id: typeof store.sceneRoomMode; icon: ReactNode; hint: string }> = [
    { id: "range",    icon: <Sunrise className="h-3.5 w-3.5" />, hint: "Warm dawn lighting" },
    { id: "night",    icon: <Moon    className="h-3.5 w-3.5" />, hint: "Indigo night lighting" },
    { id: "analysis", icon: <Sun     className="h-3.5 w-3.5" />, hint: "Neutral warehouse lighting" },
  ];
  for (const m of roomModes) {
    actions.push({
      id: `room:${m.id}`,
      group: "Lighting",
      label: `Lighting: ${capitalise(m.id)}`,
      hint: m.hint,
      icon: m.icon,
      keywords: ["scene", "mode", m.id],
      run: fire(() => store.setSceneRoomMode(m.id)),
    });
  }

  // ---- Camera presets ---- //
  const cameraPresets: Array<typeof store.sceneCameraPreset> = ["orbit", "top", "chase"];
  for (const p of cameraPresets) {
    actions.push({
      id: `camera:${p}`,
      group: "Camera",
      label: `Camera: ${capitalise(p)}`,
      icon: <Eye className="h-3.5 w-3.5" />,
      keywords: ["view", "angle"],
      run: fire(() => store.setSceneCameraPreset(p)),
    });
  }

  // ---- Visual layer toggles ---- //
  const layerToggles: Array<{
    id: string; label: string; on: boolean; setter: (v: boolean) => void;
    icon: ReactNode; keywords?: string[];
  }> = [
    { id: "terrain",   label: "Terrain",        on: store.showTerrain,    setter: store.setShowTerrain,    icon: <Layers className="h-3.5 w-3.5" />, keywords: ["hills", "ground"] },
    { id: "particles", label: "Particle FX",    on: store.showParticles,  setter: store.setShowParticles,  icon: <Sparkles className="h-3.5 w-3.5" />, keywords: ["wash", "trail", "burst"] },
    { id: "sky",       label: "Sky environment",on: store.showSky,        setter: store.setShowSky,        icon: <CloudSun className="h-3.5 w-3.5" />, keywords: ["hdri", "skybox", "reflection"] },
    { id: "postfx",    label: "Post-processing",on: store.showPostFX,     setter: store.setShowPostFX,     icon: <Cloud className="h-3.5 w-3.5" />, keywords: ["bloom", "ssao", "vignette"] },
    { id: "radar",     label: "Radar sweep",    on: store.showRadarSweep, setter: store.setShowRadarSweep, icon: <ScanLine className="h-3.5 w-3.5" />, keywords: ["radar", "sweep", "scan"] },
    { id: "audio",     label: "Audio",          on: store.soundEnabled,   setter: store.setSoundEnabled,   icon: store.soundEnabled ? <Volume2 className="h-3.5 w-3.5" /> : <VolumeX className="h-3.5 w-3.5" />, keywords: ["sound", "mute", "rotor"] },
  ];
  for (const t of layerToggles) {
    actions.push({
      id: `toggle:${t.id}`,
      group: "Visual layers",
      label: `${t.on ? "Hide" : "Show"} ${t.label}`,
      hint: t.on ? "Currently on" : "Currently off",
      icon: t.icon,
      keywords: ["toggle", ...(t.keywords ?? [])],
      run: fire(() => t.setter(!t.on)),
    });
  }

  return actions;
}

function capitalise(s: string): string {
  return s.length ? s[0].toUpperCase() + s.slice(1) : s;
}
