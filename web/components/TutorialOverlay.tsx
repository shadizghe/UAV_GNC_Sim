"use client";

import {
  Activity, ArrowLeft, ArrowRight, BarChart3, BookOpen, Box, CheckCircle2,
  Command, Cpu, Crosshair, Keyboard, Lightbulb, Map, Play, Rocket, Route,
  Target, Telescope, Wrench, X,
} from "lucide-react";
import {
  ReactNode, useCallback, useEffect, useRef, useState,
} from "react";
import { cn } from "@/lib/utils";
import { playClick, playWhoosh } from "@/lib/sounds";
import {
  AnimatePresence, motion, overlayFade, paletteReveal,
} from "@/lib/motion";

/**
 * Tutorial overlay — press `?` / `F1` (or click the help pill in the
 * top-bar) to open a step-by-step walkthrough of the simulator.
 * Mirrors CommandPalette's modal styling so the two feel like siblings.
 *
 * Dispatch `window.dispatchEvent(new CustomEvent("tutorial:open"))`
 * from anywhere (e.g. the command-palette action) to launch it.
 */

interface TutorialStep {
  id: string;
  title: string;
  subtitle: string;
  icon: ReactNode;
  /** Markdown-ish paragraphs.  Plain strings, rendered as <p>. */
  body: string[];
  /** Concrete actions the user should perform to follow along. */
  tryIt?: string[];
  /** Pro-tips, gotchas, keyboard shortcuts. */
  tips?: Array<{ kbd?: string[]; text: string }>;
}

const STEPS: TutorialStep[] = [
  {
    id: "welcome",
    title: "Welcome to Drone Flight Control",
    subtitle: "What this simulator actually does",
    icon: <Rocket className="h-4 w-4" />,
    body: [
      "This is a closed-loop, 6-DOF quadrotor flight simulator. The backend integrates rigid-body dynamics at a 10 ms time step, with a cascaded PID stack for position / velocity / attitude control and an EKF that fuses GPS and IMU measurements.",
      "The browser is the cockpit: you load a mission preset, edit waypoints, inject sensor faults, run the sim, then scrub through the resulting telemetry on a 3D scene plus charts.",
      "This walkthrough covers every panel and shortcut. Use ← / → (or the buttons below) to move between steps. Press Esc at any time to dismiss — you can always reopen with ? or F1.",
    ],
    tryIt: [
      "Look at the top-bar: it shows the current mission, sim status (IDLE / RUNNING / NOMINAL), API connection, and time-step.",
      "Notice the left sidebar (mission scenarios + performance) and the right workspace (seven tabs).",
    ],
    tips: [
      { kbd: ["?"], text: "Reopen this tutorial from anywhere." },
      { kbd: ["Esc"], text: "Close the tutorial without losing your spot." },
    ],
  },
  {
    id: "preset",
    title: "Step 1 · Pick a mission scenario",
    subtitle: "The Mission Scenario block in the left sidebar",
    icon: <Route className="h-4 w-4" />,
    body: [
      "Every simulation starts from a preset — a pre-baked combination of vehicle parameters, waypoints, no-fly zones, threat bandits, and controller gains. The preset list is fetched from the backend on first load.",
      "Clicking a preset card loads it into the store and immediately repopulates the 3D scene, the mission planner, and the tactical map. A check-mark appears on the active card.",
    ],
    tryIt: [
      "In the left sidebar, find the \"Mission Scenario\" section.",
      "Click any preset card. Watch the 3D scene re-center on the new mission and the top-bar update with the preset name + tag.",
      "If you want to undo edits later, the command palette has a \"Reset mission to preset baseline\" action.",
    ],
    tips: [
      { text: "The top-bar shows the active mission label and a colored tag pill — handy when juggling several scenarios." },
    ],
  },
  {
    id: "scene",
    title: "Step 2 · Read the 3D scene",
    subtitle: "The center viewport — Three.js / WebGL",
    icon: <Telescope className="h-4 w-4" />,
    body: [
      "The viewport renders the world frame in ENU (East-North-Up) with units in meters — see the badge in the top-left corner. The drone, waypoint markers, no-fly zones, bandits, and the trajectory ribbon all live in this scene.",
      "Camera presets: Orbit (free orbit around the drone), Top (overhead survey), Chase (third-person follow). Switch between them via the Sim Room tab or the command palette.",
      "Lighting modes: Range (warm dawn), Night (indigo), Analysis (neutral warehouse) — each retones the entire scene including reflections and the post-process tint.",
    ],
    tryIt: [
      "Click + drag inside the viewport to orbit. Scroll-wheel to dolly in/out. Right-drag to pan.",
      "Open the command palette (Ctrl+K) and type \"camera\" — try each preset.",
      "Type \"lighting\" in the palette and switch between Range / Night / Analysis.",
    ],
    tips: [
      { text: "Once a sim has finished, the scene shows a translucent ribbon along the actual flown trajectory." },
    ],
  },
  {
    id: "mission-plan",
    title: "Step 3 · Edit the mission plan",
    subtitle: "Workspace tab → Mission",
    icon: <Crosshair className="h-4 w-4" />,
    body: [
      "The Mission tab on the right is where you sculpt the flight: add / remove / drag waypoints, draw cylindrical no-fly zones, place bandit emitters, and tweak speed limits.",
      "All edits live in the zustand store and are reflected in the 3D scene in real-time. Edits stack on top of the loaded preset until you hit \"Reset mission to preset baseline\".",
    ],
    tryIt: [
      "Click the Mission tab in the right-side workspace tab-bar.",
      "Add a waypoint and drag its altitude slider — watch the marker climb in the 3D scene.",
      "Try the \"Reset mission\" action in the command palette to wipe your edits.",
    ],
    tips: [
      { text: "Waypoints are visited in list order. Drag them in the list to reorder." },
    ],
  },
  {
    id: "sim-room",
    title: "Step 4 · Tune the Sim Room",
    subtitle: "Workspace tab → Sim Room",
    icon: <Box className="h-4 w-4" />,
    body: [
      "The Sim Room tab controls everything visual: lighting mode, camera preset, terrain on/off, particle FX, sky environment (HDRI), post-processing (bloom / SSAO / vignette), the radar sweep overlay, and master audio.",
      "Toggling layers off is the fastest way to claw back framerate on a low-end GPU. None of these toggles affect the simulated physics — they're purely cosmetic.",
    ],
    tryIt: [
      "Open the Sim Room tab and toggle \"Particle FX\" off — the rotor wash trails disappear.",
      "Switch lighting to \"Night\" and toggle the radar sweep on for the full operations-center look.",
    ],
    tips: [
      { kbd: ["Ctrl", "K"], text: "Every toggle here is also reachable from the command palette." },
    ],
  },
  {
    id: "faults",
    title: "Step 5 · Inject faults",
    subtitle: "Workspace tab → Faults",
    icon: <Wrench className="h-4 w-4" />,
    body: [
      "This is where the fun starts. Schedule motor failures, IMU dropouts, GPS-denied windows, and wind gusts — each with a start time, duration, and severity.",
      "Faults are visualized as the four rotor bars (live thrust per motor) and as colored bands along the telemetry timeline once the sim runs.",
      "Use \"Clear all injected faults\" from the command palette to start over without losing your mission edits.",
    ],
    tryIt: [
      "Open the Faults tab. Add a motor-1 fault at t = 4 s with 30% thrust loss for 2 s.",
      "Run the simulation (next step) and watch how the controller compensates. If it compensates.",
    ],
    tips: [
      { text: "GPS-denied windows force the EKF to dead-reckon on IMU alone — drift grows fast." },
    ],
  },
  {
    id: "run",
    title: "Step 6 · Run the simulation",
    subtitle: "Submit the mission, watch it execute",
    icon: <Play className="h-4 w-4" />,
    body: [
      "Hitting \"Run simulation\" packages your current mission + faults + parameters and POSTs them to the backend, which returns a full timeline of state, control, estimator, and event samples.",
      "While running, the top-bar status pill turns amber (\"RUNNING\") and a banner appears at the bottom of the viewport. When done, a results card materializes top-right with sim time, sample count, and waypoints reached.",
      "After a successful run you can scrub through the timeline (Play / Pause / Restart playback) — the 3D scene replays the actual flown trajectory.",
    ],
    tryIt: [
      "Open the command palette (Ctrl+K) and run \"Run simulation\".",
      "When the green \"NOMINAL\" pill appears, run \"Play replay\" and watch the drone fly its mission.",
      "Try \"Restart playback\" to jump back to t = 0.",
    ],
    tips: [
      { text: "If the run fails, a red banner appears with the backend error message — usually a malformed waypoint or an out-of-range gain." },
    ],
  },
  {
    id: "autonomy",
    title: "Step 7 · Watch autonomy replan",
    subtitle: "Workspace tab → Autonomy",
    icon: <Cpu className="h-4 w-4" />,
    body: [
      "The Autonomy tab makes threat-aware replanning visible. It shows whether replanning is armed, how many threat sources are being watched, how long the aircraft spent on inserted reroute legs, and the latest CONTACT - REROUTING event.",
      "When the active leg becomes contested by a projected bandit envelope or a threat/no-fly zone, the backend inserts a temporary waypoint and returns a contact log entry. That is real simulator telemetry, not a cosmetic overlay.",
      "Use the replanning switch to compare behavior: armed runs can insert detours; standby runs fall back to the fixed waypoint follower plus the existing local evasion behavior.",
    ],
    tryIt: [
      "Load Strike Ingress from the left sidebar.",
      "Open the Autonomy tab and confirm Replanning is armed.",
      "Click Run Autonomy. When the run completes, inspect the contact log for threat name, inserted waypoint, envelope radius, and clearance.",
      "Toggle replanning to Standby and run again to compare the mission without route insertion.",
    ],
    tips: [
      { text: "Green route overlays in the 3D scene and Tactical map come from the replanned waypoint list returned by the backend." },
      { text: "Planner cost and expanded-node counts are backend A* telemetry, useful for spotting routes that need finer grid resolution or more clearance." },
    ],
  },
  {
    id: "tactical",
    title: "Step 8 · Read the tactical map",
    subtitle: "Workspace tab → Tactical",
    icon: <Map className="h-4 w-4" />,
    body: [
      "The Tactical tab is a 2D top-down view: waypoints, no-fly zones, bandit threat circles, and the flown path projected onto the XY plane. Useful when the 3D camera makes it hard to judge horizontal separation.",
      "After an autonomy run, the Tactical map also shows the inserted reroute path, CONTACT - REROUTING markers, and the A* planner cost field. It is the fastest way to see whether the planned leg was contested and how the route bent around the threat picture.",
    ],
    tryIt: [
      "Switch to the Tactical tab after a run and confirm your trajectory steered around the red bandit circles.",
      "Look for the amber/red cost field, green reroute path, and REROUTE marker if the contact log reported an event.",
    ],
  },
  {
    id: "telemetry",
    title: "Step 9 · Inspect telemetry",
    subtitle: "Workspace tab → Telemetry",
    icon: <BarChart3 className="h-4 w-4" />,
    body: [
      "Telemetry is a stack of Plotly time-series: position, velocity, attitude (roll/pitch/yaw), motor thrusts, control effort, and EKF residuals.",
      "All charts share an x-axis cursor — hover one to see a synced crosshair across the rest. The yellow vertical line is the current replay scrubber.",
    ],
    tryIt: [
      "Open Telemetry after a run. Hover the position chart and watch the cursor track across velocity, attitude, and rotor charts.",
    ],
    tips: [
      { text: "If the EKF estimator was used, the sidebar's EKF section shows the noise reduction vs raw GPS — typically 70–95%." },
    ],
  },
  {
    id: "monte-carlo",
    title: "Step 10 · Run Monte Carlo sweeps",
    subtitle: "Workspace tab → Monte Carlo",
    icon: <Activity className="h-4 w-4" />,
    body: [
      "Monte Carlo runs the same mission N times with randomized noise seeds, wind, and fault timings. The result is a distribution: success rate, RMS error spread, time-to-completion histogram.",
      "This is the right tab to answer \"how robust is this controller to sensor noise?\" — a single deterministic run can be misleading.",
    ],
    tryIt: [
      "Open Monte Carlo, set N = 25, click Run, and watch the success-rate dial converge as runs come back.",
    ],
    tips: [
      { text: "Bigger N → tighter confidence intervals but longer runs. 25–50 is a good first cut." },
    ],
  },
  {
    id: "command-palette",
    title: "Step 11 · Master the command palette",
    subtitle: "Ctrl+K from anywhere",
    icon: <Command className="h-4 w-4" />,
    body: [
      "The command palette is the fastest way to reach any action without hunting through tabs. It's fuzzy-searched, keyboard-driven, and grouped by category (Mission, Simulation, Faults, Camera, Lighting, Visual layers).",
      "Examples: type \"night\" → switch to night lighting. Type \"clear\" → clear all faults. Type the name of a preset → load it. Type \"chase\" → switch camera.",
    ],
    tryIt: [
      "Press Ctrl+K. Type \"top\" — hit Enter to switch to the overhead camera.",
      "Reopen with Ctrl+K, type \"audio\" — toggle sound on/off.",
    ],
    tips: [
      { kbd: ["Ctrl", "K"], text: "Open / close the palette." },
      { kbd: ["↑", "↓"], text: "Navigate filtered results." },
      { kbd: ["⏎"], text: "Run the highlighted action." },
    ],
  },
  {
    id: "shortcuts",
    title: "Cheat sheet · Keyboard shortcuts",
    subtitle: "Everything you can do without leaving the keyboard",
    icon: <Keyboard className="h-4 w-4" />,
    body: [
      "All shortcuts are global — they fire regardless of which panel is focused. Click anywhere outside an input field if a shortcut feels unresponsive.",
    ],
    tips: [
      { kbd: ["Ctrl", "K"], text: "Open the command palette." },
      { kbd: ["?"],         text: "Open this tutorial." },
      { kbd: ["F1"],        text: "Open this tutorial (alt key)." },
      { kbd: ["Esc"],       text: "Close the active modal." },
      { kbd: ["←", "→"],   text: "Tutorial: previous / next step." },
      { kbd: ["↑", "↓"],   text: "Command palette: navigate results." },
      { kbd: ["⏎"],         text: "Command palette: run highlighted action." },
    ],
  },
];

export function TutorialOverlay() {
  const [open, setOpen] = useState(false);
  const [stepIdx, setStepIdx] = useState(0);
  const [completed, setCompleted] = useState<Set<string>>(new Set());
  const contentRef = useRef<HTMLDivElement>(null);

  const step = STEPS[stepIdx];
  const isLast = stepIdx === STEPS.length - 1;
  const isFirst = stepIdx === 0;
  const progress = ((stepIdx + 1) / STEPS.length) * 100;

  const close = useCallback(() => setOpen(false), []);
  const next = useCallback(() => {
    setCompleted((s) => new Set(s).add(STEPS[stepIdx].id));
    if (!isLast) setStepIdx((i) => i + 1);
  }, [stepIdx, isLast]);
  const prev = useCallback(() => {
    if (!isFirst) setStepIdx((i) => i - 1);
  }, [isFirst]);

  // External open trigger (TopBar button, command-palette action).
  useEffect(() => {
    const onOpen = () => {
      playWhoosh();
      setOpen(true);
    };
    window.addEventListener("tutorial:open", onOpen);
    return () => window.removeEventListener("tutorial:open", onOpen);
  }, []);

  // Keyboard: ? / F1 opens, Esc / arrows / Enter while open.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const inField =
        target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA");

      if (!open) {
        if (!inField && (e.key === "?" || e.key === "F1")) {
          e.preventDefault();
          playWhoosh();
          setOpen(true);
        }
        return;
      }

      if (e.key === "Escape") {
        e.preventDefault();
        close();
      } else if (e.key === "ArrowRight") {
        e.preventDefault();
        if (!isLast) { playClick(); next(); }
      } else if (e.key === "ArrowLeft") {
        e.preventDefault();
        if (!isFirst) { playClick(); prev(); }
      } else if (e.key === "Enter") {
        e.preventDefault();
        if (isLast) close();
        else { playClick(); next(); }
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, isFirst, isLast, next, prev, close]);

  // Reset scroll when stepping.
  useEffect(() => {
    contentRef.current?.scrollTo({ top: 0, behavior: "auto" });
  }, [stepIdx]);

  // Mark final step complete the moment it's viewed.
  useEffect(() => {
    if (open && isLast) {
      setCompleted((s) => {
        if (s.has(STEPS[stepIdx].id)) return s;
        const next = new Set(s);
        next.add(STEPS[stepIdx].id);
        return next;
      });
    }
  }, [open, isLast, stepIdx]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          variants={overlayFade}
          initial="hidden"
          animate="visible"
          exit="exit"
          className="fixed inset-0 z-50 flex items-start justify-center bg-bg/75 px-4 pt-12 backdrop-blur-sm sm:pt-16"
          onClick={close}
        >
          <motion.div
            variants={paletteReveal}
            initial="hidden"
            animate="visible"
            exit="exit"
            className="panel flex w-full max-w-4xl flex-col overflow-hidden lg:max-h-[85vh] lg:flex-row"
            onClick={(e) => e.stopPropagation()}
            role="dialog"
            aria-label="Drone Flight Control tutorial"
            aria-modal="true"
          >
            {/* ─── Header ────────────────────────────────────────── */}
            <div className="flex items-center gap-2 border-b border-cyan/15 px-3.5 py-2.5 lg:hidden">
              <BookOpen className="h-4 w-4 text-cyan" />
              <span className="flex-1 text-sm font-semibold text-text">
                Tutorial · Step {stepIdx + 1} of {STEPS.length}
              </span>
              <button
                type="button"
                onClick={close}
                className="grid h-6 w-6 place-items-center rounded text-muted hover:bg-panel-2 hover:text-text"
                aria-label="Close tutorial"
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>

            {/* ─── Chapter list (sidebar) ────────────────────────── */}
            <nav className="border-b border-cyan/15 bg-bg/50 lg:w-64 lg:shrink-0 lg:border-b-0 lg:border-r lg:overflow-y-auto">
              <div className="hidden items-center gap-2 border-b border-cyan/15 px-4 py-3 lg:flex">
                <BookOpen className="h-4 w-4 text-cyan" />
                <div className="flex-1">
                  <div className="text-sm font-semibold text-text">Tutorial</div>
                  <div className="text-[0.62rem] uppercase tracking-widest text-muted">
                    {STEPS.length} chapters
                  </div>
                </div>
                <button
                  type="button"
                  onClick={close}
                  className="grid h-6 w-6 place-items-center rounded text-muted hover:bg-panel-2 hover:text-text"
                  aria-label="Close tutorial"
                >
                  <X className="h-3.5 w-3.5" />
                </button>
              </div>

              <ol className="flex gap-1 overflow-x-auto px-2 py-2 lg:flex-col lg:gap-0.5 lg:overflow-visible lg:px-2 lg:py-3">
                {STEPS.map((s, i) => {
                  const active = i === stepIdx;
                  const done = completed.has(s.id) && !active;
                  return (
                    <li key={s.id} className="shrink-0 lg:shrink">
                      <button
                        type="button"
                        onClick={() => { playClick(); setStepIdx(i); }}
                        className={cn(
                          "flex w-full items-center gap-2.5 whitespace-nowrap rounded-md px-2.5 py-1.5 text-left text-xs transition-colors lg:whitespace-normal",
                          active
                            ? "bg-cyan/15 text-cyan"
                            : "text-muted hover:bg-panel-2 hover:text-text",
                        )}
                      >
                        <span className={cn(
                          "grid h-5 w-5 shrink-0 place-items-center rounded-full border text-[0.6rem] font-mono font-semibold",
                          active
                            ? "border-cyan bg-cyan/20 text-cyan"
                            : done
                              ? "border-green/50 bg-green/15 text-green"
                              : "border-cyan/20 bg-bg/60 text-muted",
                        )}>
                          {done ? <CheckCircle2 className="h-3 w-3" /> : i + 1}
                        </span>
                        <span className="min-w-0 flex-1 truncate font-semibold lg:whitespace-normal">
                          {shortTitle(s)}
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ol>
            </nav>

            {/* ─── Content pane ──────────────────────────────────── */}
            <div className="flex min-w-0 flex-1 flex-col">
              {/* Progress bar */}
              <div className="h-1 w-full bg-bg/60">
                <motion.div
                  className="h-full bg-gradient-to-r from-cyan via-cyan to-violet"
                  initial={false}
                  animate={{ width: `${progress}%` }}
                  transition={{ type: "spring", stiffness: 220, damping: 28 }}
                />
              </div>

              <div ref={contentRef} className="flex-1 overflow-y-auto px-5 py-5 sm:px-7 sm:py-6">
                <AnimatePresence mode="wait">
                  <motion.div
                    key={step.id}
                    initial={{ opacity: 0, y: 6 }}
                    animate={{ opacity: 1, y: 0 }}
                    exit={{ opacity: 0, y: -4 }}
                    transition={{ duration: 0.16, ease: [0.22, 1, 0.36, 1] }}
                  >
                    <div className="flex items-center gap-3">
                      <span className="grid h-9 w-9 place-items-center rounded-md border border-cyan/30 bg-cyan/10 text-cyan">
                        {step.icon}
                      </span>
                      <div className="min-w-0">
                        <div className="text-[0.62rem] uppercase tracking-[0.2em] text-muted">
                          Chapter {stepIdx + 1} / {STEPS.length}
                        </div>
                        <h2 className="text-lg font-semibold text-text leading-tight">
                          {step.title}
                        </h2>
                      </div>
                    </div>

                    <p className="mt-1 ml-12 text-[0.7rem] uppercase tracking-widest text-muted">
                      {step.subtitle}
                    </p>

                    <div className="mt-5 space-y-3 text-sm leading-relaxed text-text/90">
                      {step.body.map((para, i) => (
                        <p key={i}>{para}</p>
                      ))}
                    </div>

                    {step.tryIt && step.tryIt.length > 0 && (
                      <section className="mt-6 panel-soft border-amber/25 bg-amber/[0.04] p-4">
                        <header className="flex items-center gap-2 text-amber">
                          <Target className="h-3.5 w-3.5" />
                          <span className="text-[0.66rem] font-semibold uppercase tracking-[0.18em]">
                            Try it
                          </span>
                        </header>
                        <ol className="mt-2.5 space-y-2 text-sm text-text/90">
                          {step.tryIt.map((item, i) => (
                            <li key={i} className="flex gap-2.5">
                              <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-amber/15 text-[0.65rem] font-mono font-semibold text-amber">
                                {i + 1}
                              </span>
                              <span>{item}</span>
                            </li>
                          ))}
                        </ol>
                      </section>
                    )}

                    {step.tips && step.tips.length > 0 && (
                      <section className="mt-5 panel-soft border-violet/20 bg-violet/[0.04] p-4">
                        <header className="flex items-center gap-2 text-violet">
                          <Lightbulb className="h-3.5 w-3.5" />
                          <span className="text-[0.66rem] font-semibold uppercase tracking-[0.18em]">
                            Tips & shortcuts
                          </span>
                        </header>
                        <ul className="mt-2.5 space-y-2 text-sm text-text/90">
                          {step.tips.map((tip, i) => (
                            <li key={i} className="flex flex-wrap items-center gap-2">
                              {tip.kbd && (
                                <span className="flex shrink-0 items-center gap-1 font-mono text-[0.7rem]">
                                  {tip.kbd.map((k, ki) => (
                                    <span key={ki} className="flex items-center gap-1">
                                      {ki > 0 && <span className="text-muted">+</span>}
                                      <kbd className="rounded border border-cyan/25 bg-bg/60 px-1.5 py-0.5 text-cyan">
                                        {k}
                                      </kbd>
                                    </span>
                                  ))}
                                </span>
                              )}
                              <span className="flex-1 min-w-[16ch]">{tip.text}</span>
                            </li>
                          ))}
                        </ul>
                      </section>
                    )}
                  </motion.div>
                </AnimatePresence>
              </div>

              {/* ─── Footer / nav ───────────────────────────────── */}
              <div className="flex items-center justify-between gap-3 border-t border-cyan/15 bg-bg/60 px-4 py-3">
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => { playClick(); prev(); }}
                    disabled={isFirst}
                    className={cn(
                      "flex items-center gap-1.5 rounded-md border px-3 py-1.5 text-xs font-semibold transition-colors",
                      isFirst
                        ? "cursor-not-allowed border-cyan/10 text-muted/50"
                        : "border-cyan/25 text-text hover:bg-panel-2 hover:border-cyan/45",
                    )}
                  >
                    <ArrowLeft className="h-3.5 w-3.5" />
                    Back
                  </button>
                  <span className="hidden text-[0.66rem] uppercase tracking-widest text-muted sm:inline">
                    {stepIdx + 1} / {STEPS.length}
                  </span>
                </div>

                <div className="flex items-center gap-2">
                  <span className="hidden items-center gap-1 text-[0.62rem] uppercase tracking-widest text-muted sm:flex">
                    <kbd className="rounded border border-cyan/20 px-1 font-mono normal-case">←</kbd>
                    <kbd className="rounded border border-cyan/20 px-1 font-mono normal-case">→</kbd>
                    navigate
                  </span>
                  <button
                    type="button"
                    onClick={() => {
                      playClick();
                      if (isLast) close();
                      else next();
                    }}
                    className={cn(
                      "flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors",
                      isLast
                        ? "bg-green/15 text-green hover:bg-green/20"
                        : "bg-cyan/15 text-cyan hover:bg-cyan/25",
                    )}
                  >
                    {isLast ? (
                      <>
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        Got it — close
                      </>
                    ) : (
                      <>
                        Next
                        <ArrowRight className="h-3.5 w-3.5" />
                      </>
                    )}
                  </button>
                </div>
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

/** Strip the "Step N · " prefix for the sidebar list. */
function shortTitle(s: TutorialStep): string {
  return s.title.replace(/^Step\s+\d+\s*·\s*/, "").replace(/^Cheat sheet\s*·\s*/, "");
}
