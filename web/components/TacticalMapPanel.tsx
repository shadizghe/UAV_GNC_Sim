"use client";

import {
  Ban,
  Crosshair,
  LocateFixed,
  Pause,
  Plane,
  Play,
  Plus,
  RotateCcw,
  ShieldAlert,
  SkipBack,
} from "lucide-react";
import type { PointerEvent, ReactElement, WheelEvent } from "react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useAppStore } from "@/lib/store";
import type {
  DefensiveEvent,
  EnemyPayload,
  FriendlyDronePayload,
  FriendlyTrack,
  InterceptorBatteryPayload,
  SimResponse,
  Vec3,
  ZonePayload,
} from "@/lib/types";
import { cn } from "@/lib/utils";

type DragTarget =
  | { kind: "drone" }
  | { kind: "friendly"; index: number }
  | { kind: "waypoint"; index: number }
  | { kind: "enemy"; index: number }
  | { kind: "zone"; index: number }
  | { kind: "battery"; index: number }
  | { kind: "pan"; sx: number; sy: number; cx: number; cy: number };

type AddKind = "drone" | "friendly" | "waypoint" | "bandit" | "no_fly" | "threat";

interface ViewState {
  cx: number;
  cy: number;
  zoom: number;
}

const MIN_ZOOM = 8;
const MAX_ZOOM = 160;
const SPEEDS = [0.5, 1, 2, 4];
const INTERCEPTOR_STATUS = {
  inactive: 0,
  boost: 1,
  coast: 2,
  hit: 3,
  miss: 4,
} as const;
const SEEKER_STATUS = {
  search: 0,
  locked: 1,
  memory: 2,
} as const;

const round = (value: number, digits = 2) => {
  const scale = 10 ** digits;
  return Math.round(value * scale) / scale;
};

const defaultEnemy = (name: string, x: number, y: number, z: number): EnemyPayload => ({
  name,
  x,
  y,
  z,
  behavior: "patrol",
  speed: 1.4,
  det_r: 3,
  leth_r: 1,
  orbit_cx: x,
  orbit_cy: y,
  orbit_r: 2,
});

const defaultZone = (
  name: string,
  kind: ZonePayload["kind"],
  cx: number,
  cy: number,
): ZonePayload => ({
  name,
  kind,
  cx,
  cy,
  r: kind === "threat" ? 1.4 : 1.2,
  z_min: 0,
  z_max: kind === "threat" ? 7 : 6,
});

function nextName(existing: string[], stem: string) {
  const used = new Set(existing);
  let i = 1;
  while (used.has(`${stem}-${i}`)) i += 1;
  return `${stem}-${i}`;
}

export function TacticalMapPanel({ expanded = false }: { expanded?: boolean }) {
  const {
    currentPreset,
    initialPosition,
    friendlyDrones,
    antiAirConfig,
    simResult,
    selectedWaypointIndex,
    selectWaypoint,
    updateWaypoint,
    addWaypoint,
    addFriendlyDrone,
    updateFriendlyDronePosition,
    updateEnemyPosition,
    updateBattery,
    addEnemy,
    updateZonePosition,
    addZone,
    setInitialPosition,
    monteCarloRuns,
    monteCarloResult,
  } = useAppStore();

  const canvasRef = useRef<HTMLCanvasElement>(null);
  const viewRef = useRef<ViewState>({ cx: 0, cy: 0, zoom: 28 });
  const dragRef = useRef<DragTarget | null>(null);
  const playheadRef = useRef(0);
  const sweepRef = useRef(0);
  const monteCarloPlaybackRef = useRef({ runCount: 0, progress: 0 });
  const lastFrameRef = useRef<number | null>(null);

  const [playing, setPlaying] = useState(false);
  const [speedIndex, setSpeedIndex] = useState(1);
  const [playhead, setPlayhead] = useState(0);
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null);
  const [selectedTarget, setSelectedTarget] = useState<DragTarget | null>(null);
  const [addKind, setAddKind] = useState<AddKind>("waypoint");
  const [draft, setDraft] = useState({ x: 0, y: 0, z: 3, yaw: 0, r: 1.5, name: "" });

  const waypoints = currentPreset?.waypoints ?? [];
  const friendlyTracks = simResult?.friendly_tracks ?? [];
  const enemies = currentPreset?.enemies ?? [];
  const zones = currentPreset?.zones ?? [];
  const interceptorBatteries = simResult?.interceptor_batteries?.length
    ? simResult.interceptor_batteries
    : antiAirConfig.batteries;
  const timeline = simResult?.t ?? [];
  const speed = SPEEDS[speedIndex];

  const maxPlayhead = Math.max(0, timeline.length - 1);
  const currentTime = timeline[Math.min(playhead, maxPlayhead)] ?? 0;
  const currentReroute = useMemo(() => {
    if (!simResult?.reroute_events?.length) return null;
    let latest = null as (typeof simResult.reroute_events)[number] | null;
    for (const event of simResult.reroute_events) {
      if (event.frame <= playhead) latest = event;
      else break;
    }
    return latest;
  }, [playhead, simResult]);
  const currentEvasion = useMemo(() => {
    if (!simResult?.defensive_hist?.length) return null;
    const row = simResult.defensive_hist[Math.min(playhead, simResult.defensive_hist.length - 1)];
    if (!row || row[0] < 0.5) return null;
    let latest = null as DefensiveEvent | null;
    for (const event of simResult.defensive_events ?? []) {
      if (event.frame <= playhead) latest = event;
      else break;
    }
    return {
      row,
      event: latest,
    };
  }, [playhead, simResult]);

  // Frame at which each waypoint was captured (active-waypoint advanced
  // past it). Drives the green "reached" colouring on the map.
  const waypointReachedFrames = useMemo(() => {
    if (!simResult || waypoints.length === 0) return [] as number[];
    const frames: number[] = [];
    let prev = simResult.waypoint_active[0];
    let i = 0;
    for (let k = 1; k < simResult.waypoint_active.length; k++) {
      const w = simResult.waypoint_active[k];
      if (!prev || !w) { prev = w; continue; }
      if (w[0] !== prev[0] || w[1] !== prev[1] || w[2] !== prev[2]) {
        if (i < waypoints.length) frames[i++] = k;
      }
      prev = w;
    }
    while (frames.length < waypoints.length) frames.push(Number.POSITIVE_INFINITY);
    return frames;
  }, [simResult, waypoints]);

  // First frame the ownship enters any bandit's engagement radius
  // (1.5 × leth_r — bandit weapon envelope, sits between lethal core and
  // detection bubble). Same trigger used in the 3D scene.
  const shotDownInfo = useMemo(() => {
    const events: { frame: number; x: number; y: number }[] = [];
    if (simResult && enemies.length > 0 && simResult.enemy_hist.length > 0) {
      const M = Math.min(enemies.length, simResult.enemy_hist[0]?.length ?? 0);
      for (let k = 0; k < simResult.pos.length; k++) {
        const own = simResult.pos[k];
        const slice = simResult.enemy_hist[k];
        if (!slice) continue;
        for (let j = 0; j < M; j++) {
          const e = slice[j];
          if (!e) continue;
          const r = enemies[j].leth_r * 1.5;
          const dx = e[0] - own[0], dy = e[1] - own[1], dz = e[2] - own[2];
          if (Math.hypot(dx, dy, dz) < r) {
            events.push({ frame: k, x: own[0], y: own[1] });
            k = simResult.pos.length;
            break;
          }
        }
      }
    }
    for (const event of simResult?.interceptor_events ?? []) {
      if (event.type === "hit") {
        events.push({
          frame: event.frame,
          x: event.position[0],
          y: event.position[1],
        });
      }
    }
    events.sort((a, b) => a.frame - b.frame);
    return events[0] ?? null;
  }, [simResult, enemies]);

  const fitView = useCallback(() => {
    const points: [number, number][] = [];
    points.push([initialPosition[0], initialPosition[1]]);
    friendlyDrones.forEach((drone) => points.push([drone.x, drone.y]));
    friendlyTracks.forEach((track) => {
      track.pos.forEach((p, index) => {
        if (index % Math.max(1, Math.floor(track.pos.length / 180)) === 0) {
          points.push([p[0], p[1]]);
        }
      });
    });
    waypoints.forEach((wp) => points.push([wp[0], wp[1]]));
    simResult?.pos.forEach((p, index) => {
      if (index % Math.max(1, Math.floor(simResult.pos.length / 300)) === 0) points.push([p[0], p[1]]);
    });
    enemies.forEach((enemy) => {
      points.push([enemy.x + enemy.det_r, enemy.y + enemy.det_r]);
      points.push([enemy.x - enemy.det_r, enemy.y - enemy.det_r]);
    });
    zones.forEach((zone) => {
      points.push([zone.cx + zone.r, zone.cy + zone.r]);
      points.push([zone.cx - zone.r, zone.cy - zone.r]);
    });
    interceptorBatteries.forEach((battery) => {
      points.push([battery.x + battery.launch_range, battery.y + battery.launch_range]);
      points.push([battery.x - battery.launch_range, battery.y - battery.launch_range]);
    });
    simResult?.interceptor_hist?.forEach((frame, index) => {
      if (index % Math.max(1, Math.floor((simResult.interceptor_hist?.length ?? 1) / 240)) !== 0) return;
      frame.forEach((row) => {
        if (!row || row[6] === INTERCEPTOR_STATUS.inactive) return;
        points.push([row[0], row[1]]);
      });
    });
    simResult?.defensive_hist?.forEach((row, index) => {
      if (!row || row[0] < 0.5) return;
      if (index % Math.max(1, Math.floor((simResult.defensive_hist?.length ?? 1) / 160)) !== 0) return;
      points.push([row[1], row[2]]);
      if (Number.isFinite(row[6]) && Number.isFinite(row[7])) points.push([row[6], row[7]]);
    });
    monteCarloRuns.forEach((run) => {
      points.push([run.endpoint[0], run.endpoint[1]]);
      run.trajectory.forEach((p, index) => {
        if (index % Math.max(1, Math.floor(run.trajectory.length / 50)) === 0) {
          points.push([p[0], p[1]]);
        }
      });
    });
    monteCarloResult?.waypoints.forEach((wp, index) => {
      const radius = Math.max(
        monteCarloResult.cep50_per_wp[index] ?? 0,
        monteCarloResult.cep95_per_wp[index] ?? 0,
      );
      if (radius > 0) {
        points.push([wp[0] + radius, wp[1] + radius]);
        points.push([wp[0] - radius, wp[1] - radius]);
      }
    });

    const canvas = canvasRef.current;
    if (!canvas || points.length === 0) return;
    let xmin = Infinity;
    let xmax = -Infinity;
    let ymin = Infinity;
    let ymax = -Infinity;
    points.forEach(([x, y]) => {
      xmin = Math.min(xmin, x);
      xmax = Math.max(xmax, x);
      ymin = Math.min(ymin, y);
      ymax = Math.max(ymax, y);
    });

    const width = canvas.clientWidth || 500;
    const height = canvas.clientHeight || 320;
    const pad = 1.5;
    const zoom = Math.max(
      MIN_ZOOM,
      Math.min(
        MAX_ZOOM,
        Math.min((width - 42) / Math.max(0.1, xmax - xmin + pad * 2), (height - 42) / Math.max(0.1, ymax - ymin + pad * 2)),
      ),
    );
    viewRef.current = {
      cx: (xmin + xmax) / 2,
      cy: (ymin + ymax) / 2,
      zoom,
    };
  }, [enemies, friendlyDrones, friendlyTracks, initialPosition, interceptorBatteries, monteCarloResult, monteCarloRuns, simResult?.interceptor_hist, simResult?.pos, waypoints, zones]);

  useEffect(() => {
    fitView();
  }, [fitView, currentPreset?.label]);

  useEffect(() => {
    playheadRef.current = maxPlayhead;
    setPlayhead(maxPlayhead);
    setPlaying(false);
  }, [maxPlayhead, simResult]);

  useEffect(() => {
    playheadRef.current = playhead;
  }, [playhead]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const resize = () => {
      const dpr = window.devicePixelRatio || 1;
      const rect = canvas.getBoundingClientRect();
      canvas.width = Math.max(1, Math.floor(rect.width * dpr));
      canvas.height = Math.max(1, Math.floor(rect.height * dpr));
    };

    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(canvas);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    let frame = 0;

    const w2s = (x: number, y: number) => {
      const dpr = window.devicePixelRatio || 1;
      const width = canvas.width / dpr;
      const height = canvas.height / dpr;
      const view = viewRef.current;
      return {
        x: width / 2 + (x - view.cx) * view.zoom,
        y: height / 2 - (y - view.cy) * view.zoom,
      };
    };

    const draw = (now: number) => {
      const dpr = window.devicePixelRatio || 1;
      const width = canvas.width / dpr;
      const height = canvas.height / dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = "#060912";
      ctx.fillRect(0, 0, width, height);

      if (playing && timeline.length > 1) {
        const last = lastFrameRef.current ?? now;
        const dt = Math.min(0.08, (now - last) / 1000);
        const duration = timeline[timeline.length - 1] - timeline[0] || 1;
        const next = Math.min(maxPlayhead, playheadRef.current + (dt * speed * maxPlayhead) / duration);
        playheadRef.current = next;
        if (next >= maxPlayhead) setPlaying(false);
        setPlayhead(Math.floor(next));
      }
      lastFrameRef.current = now;
      sweepRef.current = (sweepRef.current + 0.012) % (Math.PI * 2);
      if (monteCarloPlaybackRef.current.runCount !== monteCarloRuns.length) {
        monteCarloPlaybackRef.current = { runCount: monteCarloRuns.length, progress: 0 };
      } else if (monteCarloRuns.length > 0) {
        monteCarloPlaybackRef.current.progress = (monteCarloPlaybackRef.current.progress + 0.008) % 1;
      }

      const ph = Math.floor(playheadRef.current);
      const shotDown = shotDownInfo !== null && ph >= shotDownInfo.frame;
      const truncateFrame = shotDownInfo?.frame ?? Number.POSITIVE_INFINITY;
      const reachedNow = waypointReachedFrames.map(
        (f) => f <= ph && f <= truncateFrame,
      );

      drawGrid(ctx, width, height, w2s, viewRef.current);
      drawPlannerCostField(ctx, simResult?.reroute_events ?? [], ph, w2s);
      drawInterceptorBatteries(ctx, interceptorBatteries, w2s, selectedTarget);
      drawZones(ctx, zones, w2s, selectedTarget);
      drawMonteCarlo(ctx, monteCarloRuns, monteCarloResult, w2s, monteCarloPlaybackRef.current.progress);
      drawPaths(ctx, waypoints, simResult?.pos ?? [], ph, w2s, truncateFrame);
      drawFriendlyDrones(ctx, friendlyDrones, friendlyTracks, ph, w2s, selectedTarget);
      drawReroutePlan(ctx, simResult?.replanned_waypoints ?? [], simResult?.reroute_events ?? [], ph, w2s);
      drawEnemies(ctx, enemies, simResult?.enemy_hist ?? [], ph, w2s, selectedTarget);
      drawInterceptorProjectiles(ctx, simResult, ph, w2s);
      drawDefensiveEvasion(ctx, simResult, ph, w2s);
      drawWaypoints(ctx, waypoints, w2s, selectedWaypointIndex, selectedTarget, reachedNow);
      drawOwnship(ctx, simResult, ph, w2s, shotDown ? shotDownInfo!.frame : Number.POSITIVE_INFINITY);
      if (shotDown && shotDownInfo) drawShotDown(ctx, w2s, shotDownInfo);
      drawLaunchDrone(ctx, initialPosition, w2s, selectedTarget);
      drawSweep(ctx, width, height, w2s, sweepRef.current);
      drawCompass(ctx, width);

      frame = requestAnimationFrame(draw);
    };

    frame = requestAnimationFrame(draw);
    return () => cancelAnimationFrame(frame);
  }, [enemies, friendlyDrones, friendlyTracks, initialPosition, interceptorBatteries, maxPlayhead, monteCarloResult, monteCarloRuns, playing, selectedTarget, selectedWaypointIndex, shotDownInfo, simResult, speed, timeline, waypointReachedFrames, waypoints, zones]);

  const screenToWorld = useCallback((clientX: number, clientY: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return { x: 0, y: 0, sx: 0, sy: 0 };
    const rect = canvas.getBoundingClientRect();
    const sx = clientX - rect.left;
    const sy = clientY - rect.top;
    const view = viewRef.current;
    return {
      sx,
      sy,
      x: view.cx + (sx - rect.width / 2) / view.zoom,
      y: view.cy - (sy - rect.height / 2) / view.zoom,
    };
  }, []);

  const hitTest = useCallback((sx: number, sy: number) => {
    const canvas = canvasRef.current;
    if (!canvas) return null;
    const rect = canvas.getBoundingClientRect();
    const toScreen = (x: number, y: number) => ({
      x: rect.width / 2 + (x - viewRef.current.cx) * viewRef.current.zoom,
      y: rect.height / 2 - (y - viewRef.current.cy) * viewRef.current.zoom,
    });

    const launch = toScreen(initialPosition[0], initialPosition[1]);
    if (Math.hypot(sx - launch.x, sy - launch.y) <= 14) return { kind: "drone" as const };

    for (let i = friendlyDrones.length - 1; i >= 0; i -= 1) {
      const live = friendlyTracks[i]?.pos?.[Math.floor(playheadRef.current)];
      const point = toScreen(live?.[0] ?? friendlyDrones[i].x, live?.[1] ?? friendlyDrones[i].y);
      if (Math.hypot(sx - point.x, sy - point.y) <= 14) return { kind: "friendly" as const, index: i };
    }
    for (let i = waypoints.length - 1; i >= 0; i -= 1) {
      const point = toScreen(waypoints[i][0], waypoints[i][1]);
      if (Math.hypot(sx - point.x, sy - point.y) <= 13) return { kind: "waypoint" as const, index: i };
    }
    for (let i = interceptorBatteries.length - 1; i >= 0; i -= 1) {
      const point = toScreen(interceptorBatteries[i].x, interceptorBatteries[i].y);
      if (Math.hypot(sx - point.x, sy - point.y) <= 16) return { kind: "battery" as const, index: i };
    }
    for (let i = enemies.length - 1; i >= 0; i -= 1) {
      const live = simResult?.enemy_hist?.[Math.floor(playheadRef.current)]?.[i];
      const point = toScreen(live?.[0] ?? enemies[i].x, live?.[1] ?? enemies[i].y);
      if (Math.hypot(sx - point.x, sy - point.y) <= 14) return { kind: "enemy" as const, index: i };
    }
    for (let i = zones.length - 1; i >= 0; i -= 1) {
      const point = toScreen(zones[i].cx, zones[i].cy);
      const distance = Math.hypot(sx - point.x, sy - point.y);
      const radius = zones[i].r * viewRef.current.zoom;
      if (distance <= 12 || Math.abs(distance - radius) <= 7) return { kind: "zone" as const, index: i };
    }
    return null;
  }, [enemies, friendlyDrones, friendlyTracks, initialPosition, interceptorBatteries, simResult?.enemy_hist, waypoints, zones]);

  const handlePointerDown = useCallback((event: PointerEvent<HTMLCanvasElement>) => {
    const { sx, sy, x, y } = screenToWorld(event.clientX, event.clientY);
    const hit = hitTest(sx, sy);
    event.currentTarget.setPointerCapture(event.pointerId);
    setPlaying(false);

    if (event.shiftKey && !hit) {
      const z = waypoints[selectedWaypointIndex]?.[2] ?? waypoints.at(-1)?.[2] ?? 2;
      addWaypoint([round(x), round(y), z]);
      return;
    }

    if (hit) {
      dragRef.current = hit;
      setSelectedTarget(hit);
      if (hit.kind === "waypoint") selectWaypoint(hit.index);
      return;
    }

    dragRef.current = { kind: "pan", sx, sy, cx: viewRef.current.cx, cy: viewRef.current.cy };
    setSelectedTarget(null);
  }, [addWaypoint, hitTest, screenToWorld, selectWaypoint, selectedWaypointIndex, waypoints]);

  const handlePointerMove = useCallback((event: PointerEvent<HTMLCanvasElement>) => {
    const point = screenToWorld(event.clientX, event.clientY);
    setCursor({ x: point.x, y: point.y });
    const drag = dragRef.current;
    if (!drag) return;

    if (drag.kind === "waypoint") {
      const wp = waypoints[drag.index];
      if (wp) updateWaypoint(drag.index, [round(point.x), round(point.y), wp[2]]);
    } else if (drag.kind === "drone") {
      setInitialPosition([round(point.x), round(point.y), initialPosition[2]]);
    } else if (drag.kind === "friendly") {
      updateFriendlyDronePosition(drag.index, round(point.x), round(point.y));
    } else if (drag.kind === "enemy") {
      updateEnemyPosition(drag.index, round(point.x), round(point.y));
    } else if (drag.kind === "battery") {
      updateBattery(drag.index, { x: round(point.x), y: round(point.y) });
    } else if (drag.kind === "zone") {
      updateZonePosition(drag.index, round(point.x), round(point.y));
    } else {
      viewRef.current = {
        ...viewRef.current,
        cx: drag.cx - (point.sx - drag.sx) / viewRef.current.zoom,
        cy: drag.cy + (point.sy - drag.sy) / viewRef.current.zoom,
      };
    }
  }, [initialPosition, screenToWorld, setInitialPosition, updateBattery, updateEnemyPosition, updateFriendlyDronePosition, updateWaypoint, updateZonePosition, waypoints]);

  const handlePointerUp = useCallback((event: PointerEvent<HTMLCanvasElement>) => {
    dragRef.current = null;
    event.currentTarget.releasePointerCapture(event.pointerId);
  }, []);

  const handleWheel = useCallback((event: WheelEvent<HTMLCanvasElement>) => {
    event.preventDefault();
    const before = screenToWorld(event.clientX, event.clientY);
    const factor = event.deltaY < 0 ? 1.14 : 1 / 1.14;
    const view = viewRef.current;
    const nextZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, view.zoom * factor));
    viewRef.current = { ...view, zoom: nextZoom };
    const after = screenToWorld(event.clientX, event.clientY);
    viewRef.current = {
      ...viewRef.current,
      cx: viewRef.current.cx + before.x - after.x,
      cy: viewRef.current.cy + before.y - after.y,
    };
  }, [screenToWorld]);

  const addScenarioItem = useCallback(() => {
    if (!currentPreset) return;
    const x = Number.isFinite(draft.x) ? draft.x : 0;
    const y = Number.isFinite(draft.y) ? draft.y : 0;
    if (addKind === "drone") {
      setInitialPosition([x, y, Math.max(0, draft.z)]);
      setSelectedTarget({ kind: "drone" });
      return;
    }
    if (addKind === "friendly") {
      const name = draft.name.trim() || nextName(friendlyDrones.map((drone) => drone.name), "UAV");
      addFriendlyDrone({ name, x, y, z: Math.max(0, draft.z), route_mode: "formation", enabled: true });
      setSelectedTarget({ kind: "friendly", index: friendlyDrones.length });
      return;
    }
    if (addKind === "waypoint") {
      addWaypoint([x, y, Math.max(0, draft.z)], draft.yaw);
      return;
    }
    if (addKind === "bandit") {
      const name = draft.name.trim() || nextName(enemies.map((enemy) => enemy.name), "BANDIT");
      addEnemy(defaultEnemy(name, x, y, Math.max(0, draft.z)));
      return;
    }
    const kind = addKind === "threat" ? "threat" : "no_fly";
    const stem = kind === "threat" ? "THREAT" : "NO-FLY";
    const name = draft.name.trim() || nextName(zones.map((zone) => zone.name), stem);
    addZone({ ...defaultZone(name, kind, x, y), r: Math.max(0.1, draft.r) });
  }, [addEnemy, addFriendlyDrone, addKind, addWaypoint, addZone, currentPreset, draft, enemies, friendlyDrones, setInitialPosition, zones]);

  const activeLabel = useMemo(() => {
    if (!selectedTarget) return "SCAN";
    if (selectedTarget.kind === "drone") return "DRONE";
    if (selectedTarget.kind === "friendly") return friendlyDrones[selectedTarget.index]?.name ?? "UAV";
    if (selectedTarget.kind === "waypoint") return `WPT-${selectedTarget.index + 1}`;
    if (selectedTarget.kind === "enemy") return enemies[selectedTarget.index]?.name ?? "BANDIT";
    if (selectedTarget.kind === "zone") return zones[selectedTarget.index]?.name ?? "ZONE";
    if (selectedTarget.kind === "battery") return interceptorBatteries[selectedTarget.index]?.name ?? "SAM";
    return "PAN";
  }, [enemies, friendlyDrones, interceptorBatteries, selectedTarget, zones]);

  if (!currentPreset) return null;

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <header className="flex items-center gap-2">
          <span className="h-5 w-1 rounded-sm bg-green" />
          <div>
            <h2 className="text-[0.74rem] font-semibold uppercase tracking-[0.18em] text-green">
              Tactical Map
            </h2>
            <p className="mt-0.5 text-xs text-muted">
              {activeLabel} | t={currentTime.toFixed(2)} s
              {currentReroute ? ` | ${currentReroute.message}` : ""}
              {currentEvasion ? " | MISSILE WARNING" : ""}
            </p>
          </div>
        </header>
        <button
          type="button"
          title="Fit map"
          onClick={fitView}
          className="flex h-8 items-center gap-2 rounded-md border border-cyan/20 bg-panel-2 px-3 text-xs font-semibold text-cyan transition-colors hover:border-cyan/40"
        >
          <LocateFixed className="h-3.5 w-3.5" />
          Fit
        </button>
      </div>

      <div className="overflow-hidden rounded-lg border border-cyan/15 bg-[#060912]">
        <div className={cn("relative", expanded ? "h-[520px]" : "h-[320px]")}>
          <canvas
            ref={canvasRef}
            className="h-full w-full cursor-crosshair touch-none"
            onPointerDown={handlePointerDown}
            onPointerMove={handlePointerMove}
            onPointerLeave={() => setCursor(null)}
            onPointerUp={handlePointerUp}
            onWheel={handleWheel}
          />
          <div className="pointer-events-none absolute left-3 top-3 rounded border border-cyan/20 bg-bg/75 px-2 py-1 font-mono text-[0.64rem] uppercase tracking-wider text-muted">
            ENU | Radar | {activeLabel}
          </div>
          <div className="pointer-events-none absolute bottom-3 left-3 rounded border border-cyan/20 bg-bg/75 px-2 py-1 font-mono text-[0.64rem] uppercase tracking-wider text-muted">
            {cursor ? `X ${cursor.x.toFixed(2)} | Y ${cursor.y.toFixed(2)}` : "Cursor --"}
          </div>
          <div className="pointer-events-none absolute right-3 top-3 flex flex-wrap justify-end gap-2 text-[0.62rem] uppercase tracking-wider">
            <span className="pill-amber">WPT</span>
            <span className="pill-cyan">Track</span>
            {friendlyDrones.length > 0 && <span className="pill-green">Wingmen</span>}
            <span className="pill-red">Bandit</span>
            {simResult?.reroute_events?.some((event) => event.cost_grid?.length) ? <span className="pill-amber">Cost field</span> : null}
            {simResult?.reroute_events?.length ? <span className="pill-green">Reroute</span> : null}
            {simResult?.defensive_events?.length ? <span className="pill-amber">Evasion</span> : null}
            {(monteCarloRuns.length > 0 || monteCarloResult) && <span className="pill-violet">CEP</span>}
          </div>
          {currentReroute && (
            <div className="pointer-events-none absolute left-3 right-3 top-11 rounded border border-amber/40 bg-bg/85 px-3 py-2 font-mono text-[0.66rem] uppercase tracking-wider text-amber shadow-lg shadow-amber/10">
              {currentReroute.message} | {currentReroute.threat_name} | WPT-{currentReroute.waypoint_index + 1}
            </div>
          )}
          {currentEvasion && (
            <div className={cn(
              "pointer-events-none absolute left-3 right-3 rounded border border-amber/45 bg-bg/90 px-3 py-2 font-mono text-[0.66rem] uppercase tracking-wider text-amber shadow-lg shadow-amber/10",
              currentReroute ? "top-[5.25rem]" : "top-11",
            )}>
              MISSILE WARNING | {currentEvasion.event?.mode?.toUpperCase() ?? "EVADE"} | TGO {Number.isFinite(currentEvasion.row[5]) ? currentEvasion.row[5].toFixed(2) : "--"}s
            </div>
          )}
        </div>

        <div className="border-t border-cyan/15 bg-panel px-3 py-2">
          <div className="flex items-center gap-2">
            <button
              type="button"
              title={playing ? "Pause" : "Play"}
              onClick={() => {
                if (!playing && playheadRef.current >= maxPlayhead) {
                  playheadRef.current = 0;
                  setPlayhead(0);
                }
                lastFrameRef.current = null;
                setPlaying((value) => !value);
              }}
              disabled={timeline.length < 2}
              className="icon-map-button"
            >
              {playing ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
            </button>
            <button
              type="button"
              title="Restart"
              onClick={() => {
                playheadRef.current = 0;
                setPlayhead(0);
                setPlaying(false);
              }}
              disabled={timeline.length < 2}
              className="icon-map-button"
            >
              <SkipBack className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              title="Playback speed"
              onClick={() => setSpeedIndex((value) => (value + 1) % SPEEDS.length)}
              className="h-8 rounded-md border border-cyan/20 bg-bg/60 px-2 font-mono text-xs text-cyan"
            >
              {speed}x
            </button>
            <input
              type="range"
              min={0}
              max={maxPlayhead}
              value={playhead}
              onChange={(event) => {
                const next = Number(event.target.value);
                playheadRef.current = next;
                setPlayhead(next);
                setPlaying(false);
              }}
              className="min-w-0 flex-1 accent-cyan"
            />
            <span className="w-16 text-right font-mono text-xs text-cyan">{currentTime.toFixed(1)} s</span>
          </div>
        </div>
      </div>

      <section className="panel p-3 space-y-3">
        <div className="flex items-center justify-between">
          <div className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-green">
            Add to Scenario
          </div>
          <Crosshair className="h-3.5 w-3.5 text-green" />
        </div>

        <div className="grid grid-cols-3 gap-1.5 sm:grid-cols-6">
          <AddModeButton
            active={addKind === "drone"}
            icon={<Plane />}
            label="Drone"
            onClick={() => {
              setAddKind("drone");
              setDraft((prev) => ({ ...prev, x: initialPosition[0], y: initialPosition[1], z: initialPosition[2] }));
            }}
          />
          <AddModeButton
            active={addKind === "friendly"}
            icon={<Plane />}
            label="UAV+"
            onClick={() => {
              setAddKind("friendly");
              setDraft((prev) => ({
                ...prev,
                x: initialPosition[0],
                y: initialPosition[1] - 1,
                z: initialPosition[2],
              }));
            }}
          />
          <AddModeButton active={addKind === "waypoint"} icon={<Plus />} label="WPT" onClick={() => setAddKind("waypoint")} />
          <AddModeButton active={addKind === "bandit"} icon={<ShieldAlert />} label="Bandit" onClick={() => setAddKind("bandit")} />
          <AddModeButton active={addKind === "no_fly"} icon={<Ban />} label="No-fly" onClick={() => setAddKind("no_fly")} />
          <AddModeButton active={addKind === "threat"} icon={<Crosshair />} label="Threat" onClick={() => setAddKind("threat")} />
        </div>

        <div className="grid grid-cols-2 gap-2">
          <NumberField label="x" value={draft.x} onChange={(x) => setDraft((prev) => ({ ...prev, x }))} />
          <NumberField label="y" value={draft.y} onChange={(y) => setDraft((prev) => ({ ...prev, y }))} />
          {(addKind === "waypoint" || addKind === "drone" || addKind === "friendly") && (
            <>
              <NumberField label="z" value={draft.z} min={0} onChange={(z) => setDraft((prev) => ({ ...prev, z }))} />
              {addKind === "waypoint" && (
                <NumberField label="yaw" value={draft.yaw} step={5} onChange={(yaw) => setDraft((prev) => ({ ...prev, yaw }))} />
              )}
              {addKind === "friendly" && (
                <label className="space-y-1 text-xs text-muted">
                  <span>Name</span>
                  <input
                    value={draft.name}
                    onChange={(event) => setDraft((prev) => ({ ...prev, name: event.target.value }))}
                    className="field"
                  />
                </label>
              )}
            </>
          )}
          {addKind !== "waypoint" && addKind !== "drone" && addKind !== "friendly" && (
            <>
              <NumberField label={addKind === "bandit" ? "alt" : "r"} value={addKind === "bandit" ? draft.z : draft.r} min={0} onChange={(value) => setDraft((prev) => addKind === "bandit" ? { ...prev, z: value } : { ...prev, r: value })} />
              <label className="space-y-1 text-xs text-muted">
                <span>Name</span>
                <input
                  value={draft.name}
                  onChange={(event) => setDraft((prev) => ({ ...prev, name: event.target.value }))}
                  className="field"
                />
              </label>
            </>
          )}
        </div>

        <button
          type="button"
          onClick={addScenarioItem}
          className="flex w-full items-center justify-center gap-2 rounded-md border border-green/35 bg-green/10 px-3 py-2 text-xs font-semibold uppercase tracking-wider text-green transition-colors hover:bg-green/15"
        >
          <Plus className="h-3.5 w-3.5" />
          {addKind === "drone" ? "Set Drone" : `Add ${addKind === "no_fly" ? "No-fly" : addKind === "friendly" ? "UAV" : addKind}`}
        </button>
      </section>
    </section>
  );
}

function drawGrid(
  ctx: CanvasRenderingContext2D,
  width: number,
  height: number,
  w2s: (x: number, y: number) => { x: number; y: number },
  view: ViewState,
) {
  const bg = ctx.createRadialGradient(width * 0.5, height * 0.45, 20, width * 0.5, height * 0.45, Math.max(width, height) * 0.72);
  bg.addColorStop(0, "rgba(12, 31, 58, 0.95)");
  bg.addColorStop(0.52, "rgba(6, 12, 26, 0.98)");
  bg.addColorStop(1, "rgba(3, 5, 12, 1)");
  ctx.fillStyle = bg;
  ctx.fillRect(0, 0, width, height);

  const span = Math.max(width, height) / view.zoom;
  const step = [0.5, 1, 2, 5, 10, 20].find((candidate) => span / candidate <= 14) ?? 20;
  const xMin = view.cx - width / 2 / view.zoom;
  const xMax = view.cx + width / 2 / view.zoom;
  const yMin = view.cy - height / 2 / view.zoom;
  const yMax = view.cy + height / 2 / view.zoom;

  ctx.strokeStyle = "rgba(0, 212, 255, 0.08)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let x = Math.floor(xMin / step) * step; x <= xMax; x += step) {
    const sx = w2s(x, 0).x;
    ctx.moveTo(sx, 0);
    ctx.lineTo(sx, height);
  }
  for (let y = Math.floor(yMin / step) * step; y <= yMax; y += step) {
    const sy = w2s(0, y).y;
    ctx.moveTo(0, sy);
    ctx.lineTo(width, sy);
  }
  ctx.stroke();

  const origin = w2s(0, 0);
  ctx.strokeStyle = "rgba(0, 212, 255, 0.28)";
  ctx.beginPath();
  ctx.moveTo(0, origin.y);
  ctx.lineTo(width, origin.y);
  ctx.moveTo(origin.x, 0);
  ctx.lineTo(origin.x, height);
  ctx.stroke();

  ctx.strokeStyle = "rgba(0, 212, 255, 0.13)";
  ctx.setLineDash([2, 5]);
  [2.5, 5, 10, 20].forEach((radius) => {
    const r = radius * view.zoom;
    if (r > 24 && r < Math.max(width, height)) {
      ctx.beginPath();
      ctx.arc(origin.x, origin.y, r, 0, Math.PI * 2);
      ctx.stroke();
    }
  });
  ctx.setLineDash([]);

  const vignette = ctx.createRadialGradient(width * 0.5, height * 0.5, Math.min(width, height) * 0.18, width * 0.5, height * 0.5, Math.max(width, height) * 0.72);
  vignette.addColorStop(0, "rgba(0,0,0,0)");
  vignette.addColorStop(1, "rgba(0,0,0,0.42)");
  ctx.fillStyle = vignette;
  ctx.fillRect(0, 0, width, height);
}

function drawSweep(ctx: CanvasRenderingContext2D, width: number, height: number, w2s: (x: number, y: number) => { x: number; y: number }, sweep: number) {
  const origin = w2s(0, 0);
  const radius = Math.hypot(width, height);
  const gradient = ctx.createRadialGradient(origin.x, origin.y, 0, origin.x, origin.y, radius);
  gradient.addColorStop(0, "rgba(0, 212, 255, 0.12)");
  gradient.addColorStop(1, "rgba(0, 212, 255, 0)");
  ctx.fillStyle = gradient;
  ctx.beginPath();
  ctx.moveTo(origin.x, origin.y);
  ctx.arc(origin.x, origin.y, radius, sweep - 0.52, sweep);
  ctx.closePath();
  ctx.fill();
  ctx.strokeStyle = "rgba(0, 212, 255, 0.45)";
  ctx.beginPath();
  ctx.moveTo(origin.x, origin.y);
  ctx.lineTo(origin.x + Math.cos(sweep) * radius, origin.y + Math.sin(sweep) * radius);
  ctx.stroke();
}

function drawPaths(
  ctx: CanvasRenderingContext2D,
  waypoints: Vec3[],
  flown: Vec3[],
  playhead: number,
  w2s: (x: number, y: number) => { x: number; y: number },
  truncateFrame: number,
) {
  if (waypoints.length > 1) {
    ctx.setLineDash([7, 5]);
    ctx.strokeStyle = "rgba(255, 193, 7, 0.85)";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    waypoints.forEach((wp, index) => {
      const point = w2s(wp[0], wp[1]);
      if (index === 0) ctx.moveTo(point.x, point.y);
      else ctx.lineTo(point.x, point.y);
    });
    ctx.stroke();
    ctx.setLineDash([]);
  }

  if (flown.length > 1) {
    const cutoff = Math.min(playhead, truncateFrame);
    const end = Math.max(2, Math.min(flown.length, cutoff + 1));
    const stride = Math.max(1, Math.floor(end / 600));
    ctx.strokeStyle = "rgba(0, 212, 255, 0.95)";
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let i = 0; i < end; i += stride) {
      const point = w2s(flown[i][0], flown[i][1]);
      if (i === 0) ctx.moveTo(point.x, point.y);
      else ctx.lineTo(point.x, point.y);
    }
    ctx.stroke();
  }
}

function drawFriendlyDrones(
  ctx: CanvasRenderingContext2D,
  friendlies: FriendlyDronePayload[],
  tracks: FriendlyTrack[],
  playhead: number,
  w2s: (x: number, y: number) => { x: number; y: number },
  selectedTarget: DragTarget | null,
) {
  friendlies.forEach((friendly, index) => {
    const track = tracks[index];
    const live = track?.pos?.[Math.min(playhead, Math.max(0, (track?.pos?.length ?? 1) - 1))];
    const pos = live ?? ([friendly.x, friendly.y, friendly.z] as Vec3);
    const yaw = track?.euler?.[Math.min(playhead, Math.max(0, (track?.euler?.length ?? 1) - 1))]?.[2] ?? 0;
    const selected = selectedTarget?.kind === "friendly" && selectedTarget.index === index;
    const color = selected ? "#a7ffdf" : "#2ecc71";
    const point = w2s(pos[0], pos[1]);

    if (track?.pos?.length) {
      const end = Math.min(playhead + 1, track.pos.length);
      const stride = Math.max(1, Math.floor(end / 320));
      ctx.save();
      ctx.strokeStyle = friendly.enabled ? "rgba(46,204,113,0.62)" : "rgba(154,164,178,0.35)";
      ctx.lineWidth = selected ? 2.4 : 1.6;
      ctx.setLineDash([6, 4]);
      ctx.beginPath();
      for (let i = 0; i < end; i += stride) {
        const p = w2s(track.pos[i][0], track.pos[i][1]);
        if (i === 0) ctx.moveTo(p.x, p.y);
        else ctx.lineTo(p.x, p.y);
      }
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.restore();
    }

    ctx.save();
    ctx.shadowBlur = selected ? 18 : 10;
    ctx.shadowColor = "rgba(46,204,113,0.65)";
    ctx.strokeStyle = selected ? "rgba(167,255,223,0.95)" : "rgba(46,204,113,0.65)";
    ctx.lineWidth = selected ? 2 : 1.2;
    ctx.setLineDash([2, 5]);
    ctx.beginPath();
    ctx.arc(point.x, point.y, selected ? 17 : 14, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);

    ctx.translate(point.x, point.y);
    ctx.rotate(-yaw);
    ctx.fillStyle = color;
    ctx.strokeStyle = "#060912";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(12, 0);
    ctx.lineTo(-8, 7);
    ctx.lineTo(-4, 0);
    ctx.lineTo(-8, -7);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.restore();

    ctx.fillStyle = color;
    ctx.font = "700 10px JetBrains Mono, Consolas, monospace";
    ctx.fillText(friendly.name, point.x + 14, point.y - 8);
    ctx.fillStyle = "rgba(225,232,240,0.72)";
    ctx.font = "9px JetBrains Mono, Consolas, monospace";
    const status = track?.interceptor_killed ? "DOWN" : friendly.route_mode.toUpperCase();
    ctx.fillText(`${status} | z=${pos[2].toFixed(1)}`, point.x + 14, point.y + 5);
  });
}

function drawReroutePlan(
  ctx: CanvasRenderingContext2D,
  replannedWaypoints: Vec3[],
  events: SimResponse["reroute_events"],
  playhead: number,
  w2s: (x: number, y: number) => { x: number; y: number },
) {
  if (replannedWaypoints.length > 1 && events.length > 0) {
    ctx.save();
    ctx.setLineDash([2, 4]);
    ctx.strokeStyle = "rgba(46, 204, 113, 0.9)";
    ctx.lineWidth = 2;
    ctx.shadowBlur = 10;
    ctx.shadowColor = "rgba(46, 204, 113, 0.55)";
    ctx.beginPath();
    replannedWaypoints.forEach((wp, index) => {
      const point = w2s(wp[0], wp[1]);
      if (index === 0) ctx.moveTo(point.x, point.y);
      else ctx.lineTo(point.x, point.y);
    });
    ctx.stroke();
    ctx.restore();
  }

  events.forEach((event) => {
    if (event.frame > playhead) return;
    const point = w2s(event.inserted_waypoint[0], event.inserted_waypoint[1]);
    ctx.save();
    ctx.shadowBlur = 14;
    ctx.shadowColor = "rgba(46, 204, 113, 0.85)";
    ctx.fillStyle = "#2ecc71";
    ctx.strokeStyle = "#060912";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(point.x, point.y, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.fillStyle = "#2ecc71";
    ctx.font = "700 10px JetBrains Mono, Consolas, monospace";
    ctx.fillText("REROUTE", point.x + 9, point.y + 4);
    ctx.restore();
  });
}

function drawPlannerCostField(
  ctx: CanvasRenderingContext2D,
  events: SimResponse["reroute_events"],
  playhead: number,
  w2s: (x: number, y: number) => { x: number; y: number },
) {
  let active = null as SimResponse["reroute_events"][number] | null;
  for (const event of events) {
    if (event.frame <= playhead && event.cost_grid?.length) active = event;
    else if (event.frame > playhead) break;
  }
  if (!active?.cost_grid?.length) return;

  const zoom = currentZoomFromW2s(w2s);
  ctx.save();
  ctx.globalCompositeOperation = "screen";
  for (const [x, y, cost, blocked, size] of active.cost_grid) {
    const point = w2s(x, y);
    const px = Math.max(3, size * zoom);
    const risk = Math.max(0, Math.min(1, cost / 120));
    const alpha = blocked > 0 ? 0.22 : 0.04 + risk * 0.2;
    ctx.fillStyle = blocked > 0
      ? `rgba(255, 82, 82, ${alpha})`
      : `rgba(255, 193, 7, ${alpha})`;
    ctx.fillRect(point.x - px / 2, point.y - px / 2, px, px);
  }
  ctx.restore();
}

function drawWaypoints(
  ctx: CanvasRenderingContext2D,
  waypoints: Vec3[],
  w2s: (x: number, y: number) => { x: number; y: number },
  selectedWaypointIndex: number,
  selectedTarget: DragTarget | null,
  reached: boolean[],
) {
  waypoints.forEach((wp, index) => {
    const point = w2s(wp[0], wp[1]);
    const selected = selectedWaypointIndex === index || (selectedTarget?.kind === "waypoint" && selectedTarget.index === index);
    const isReached = reached[index] ?? false;
    const radius = selected ? 10 : 7;
    const color = selected ? "#00d4ff" : isReached ? "#2ecc71" : "#ffc107";
    ctx.fillStyle = color;
    ctx.strokeStyle = "#060912";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(point.x, point.y - radius);
    ctx.lineTo(point.x + radius, point.y);
    ctx.lineTo(point.x, point.y + radius);
    ctx.lineTo(point.x - radius, point.y);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.fillStyle = color;
    ctx.font = "700 10px JetBrains Mono, Consolas, monospace";
    ctx.fillText(
      `WPT-${index + 1}${isReached ? " ✓" : ""}`,
      point.x + radius + 4,
      point.y - 4,
    );
    ctx.fillStyle = "rgba(225,232,240,0.7)";
    ctx.font = "9px JetBrains Mono, Consolas, monospace";
    ctx.fillText(`z=${wp[2].toFixed(1)}`, point.x + radius + 4, point.y + 8);
  });
}

function drawZones(
  ctx: CanvasRenderingContext2D,
  zones: ZonePayload[],
  w2s: (x: number, y: number) => { x: number; y: number },
  selectedTarget: DragTarget | null,
) {
  zones.forEach((zone, index) => {
    const point = w2s(zone.cx, zone.cy);
    const color = zone.kind === "threat" ? "255,193,7" : "255,82,82";
    const selected = selectedTarget?.kind === "zone" && selectedTarget.index === index;
    ctx.fillStyle = `rgba(${color},0.13)`;
    ctx.strokeStyle = `rgba(${color},${selected ? 1 : 0.78})`;
    ctx.lineWidth = selected ? 2.5 : 1.4;
    ctx.setLineDash(zone.kind === "threat" ? [6, 4] : []);
    ctx.beginPath();
    ctx.arc(point.x, point.y, zone.r * currentZoomFromW2s(w2s), 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = `rgba(${color},1)`;
    ctx.font = "700 10px JetBrains Mono, Consolas, monospace";
    ctx.fillText(zone.name, point.x + 8, point.y - 8);
  });
}

function drawInterceptorBatteries(
  ctx: CanvasRenderingContext2D,
  batteries: InterceptorBatteryPayload[],
  w2s: (x: number, y: number) => { x: number; y: number },
  selectedTarget: DragTarget | null,
) {
  const zoom = currentZoomFromW2s(w2s);
  batteries.forEach((battery, index) => {
    const point = w2s(battery.x, battery.y);
    const selected = selectedTarget?.kind === "battery" && selectedTarget.index === index;
    ctx.save();
    ctx.strokeStyle = selected ? "rgba(255, 138, 138, 0.65)" : "rgba(255, 82, 82, 0.28)";
    ctx.fillStyle = selected ? "rgba(255, 82, 82, 0.1)" : "rgba(255, 82, 82, 0.05)";
    ctx.lineWidth = selected ? 2 : 1.2;
    ctx.setLineDash([8, 6]);
    ctx.beginPath();
    ctx.arc(point.x, point.y, battery.launch_range * zoom, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.setLineDash([]);

    if (selected) {
      ctx.strokeStyle = "rgba(255, 209, 102, 0.9)";
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.arc(point.x, point.y, 19, 0, Math.PI * 2);
      ctx.stroke();
    }

    ctx.shadowBlur = selected ? 18 : 12;
    ctx.shadowColor = "rgba(255, 82, 82, 0.75)";
    ctx.fillStyle = selected ? "#ff8a8a" : "#ff5252";
    ctx.strokeStyle = "#060912";
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(point.x, point.y - 11);
    ctx.lineTo(point.x + 10, point.y + 7);
    ctx.lineTo(point.x - 10, point.y + 7);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.shadowBlur = 0;

    ctx.strokeStyle = "#ffd166";
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(point.x - 6, point.y + 1);
    ctx.lineTo(point.x + 10, point.y - 9);
    ctx.stroke();

    ctx.fillStyle = selected ? "#ffd166" : "#ff8a8a";
    ctx.font = "700 10px JetBrains Mono, Consolas, monospace";
    ctx.fillText(selected ? `${battery.name} DRAG` : battery.name, point.x + 13, point.y + 4);
    ctx.fillStyle = "rgba(225,232,240,0.72)";
    ctx.font = "9px JetBrains Mono, Consolas, monospace";
    ctx.fillText(`N=${battery.nav_constant.toFixed(1)} R=${battery.launch_range.toFixed(1)}m`, point.x + 13, point.y + 15);
    ctx.restore();
  });
}

function drawInterceptorProjectiles(
  ctx: CanvasRenderingContext2D,
  simResult: SimResponse | null,
  playhead: number,
  w2s: (x: number, y: number) => { x: number; y: number },
) {
  const hist = simResult?.interceptor_hist ?? [];
  if (hist.length === 0) return;
  const frame = Math.max(0, Math.min(playhead, hist.length - 1));
  const rows = hist[frame] ?? [];

  rows.forEach((row, slot) => {
    if (!row || row[6] === INTERCEPTOR_STATUS.inactive) return;

    const trailStride = Math.max(1, Math.floor((frame + 1) / 260));
    ctx.save();
    ctx.strokeStyle = row[6] === INTERCEPTOR_STATUS.boost
      ? "rgba(255, 138, 61, 0.9)"
      : "rgba(255, 51, 79, 0.84)";
    ctx.lineWidth = 2.2;
    ctx.shadowBlur = 8;
    ctx.shadowColor = "rgba(255, 51, 79, 0.55)";
    ctx.beginPath();
    let started = false;
    for (let k = 0; k <= frame; k += trailStride) {
      const past = hist[k]?.[slot];
      if (!past || past[6] === INTERCEPTOR_STATUS.inactive) continue;
      const point = w2s(past[0], past[1]);
      if (!started) {
        ctx.moveTo(point.x, point.y);
        started = true;
      } else {
        ctx.lineTo(point.x, point.y);
      }
    }
    ctx.stroke();
    ctx.restore();

    const point = w2s(row[0], row[1]);
    const nose = w2s(row[0] + row[3], row[1] + row[4]);
    const heading = Math.atan2(nose.y - point.y, nose.x - point.x);
    const boost = row[6] === INTERCEPTOR_STATUS.boost;
    const terminal = row[6] === INTERCEPTOR_STATUS.hit || row[6] === INTERCEPTOR_STATUS.miss;
    const seeker = row[7] ?? SEEKER_STATUS.search;
    const color = row[6] === INTERCEPTOR_STATUS.hit
      ? "#ffd166"
      : row[6] === INTERCEPTOR_STATUS.miss
        ? "#9aa4b2"
        : boost
          ? "#ff8a3d"
          : "#ff334f";

    ctx.save();
    ctx.translate(point.x, point.y);
    ctx.rotate(heading);
    ctx.shadowBlur = terminal ? 16 : 11;
    ctx.shadowColor = color;
    ctx.fillStyle = color;
    ctx.strokeStyle = "#060912";
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(13, 0);
    ctx.lineTo(-9, 6);
    ctx.lineTo(-5, 0);
    ctx.lineTo(-9, -6);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    if (boost) {
      ctx.fillStyle = "#ffd166";
      ctx.beginPath();
      ctx.moveTo(-9, 0);
      ctx.lineTo(-18, 4);
      ctx.lineTo(-15, 0);
      ctx.lineTo(-18, -4);
      ctx.closePath();
      ctx.fill();
    }
    ctx.restore();

    ctx.save();
    ctx.strokeStyle = "rgba(255, 209, 102, 0.32)";
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 4]);
    ctx.beginPath();
    ctx.moveTo(point.x, point.y);
    ctx.lineTo(nose.x, nose.y);
    ctx.stroke();
    ctx.setLineDash([]);
    if (Number.isFinite(row[8]) && Number.isFinite(row[9])) {
      const seekerPoint = w2s(row[8], row[9]);
      ctx.strokeStyle = seeker === SEEKER_STATUS.locked
        ? "rgba(255, 209, 102, 0.65)"
        : seeker === SEEKER_STATUS.memory
          ? "rgba(179, 136, 255, 0.55)"
          : "rgba(154, 164, 178, 0.32)";
      ctx.lineWidth = 1.2;
      ctx.setLineDash(seeker === SEEKER_STATUS.locked ? [] : [2, 5]);
      ctx.beginPath();
      ctx.moveTo(point.x, point.y);
      ctx.lineTo(seekerPoint.x, seekerPoint.y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle = seeker === SEEKER_STATUS.locked ? "#ffd166" : seeker === SEEKER_STATUS.memory ? "#b388ff" : "#9aa4b2";
      ctx.beginPath();
      ctx.arc(seekerPoint.x, seekerPoint.y, 3.5, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.fillStyle = color;
    ctx.font = "700 9px JetBrains Mono, Consolas, monospace";
    const flightLabel = boost ? "BOOST" : terminal ? (row[6] === INTERCEPTOR_STATUS.hit ? "HIT" : "MISS") : "COAST";
    const seekerLabel = seeker === SEEKER_STATUS.locked ? "LOCK" : seeker === SEEKER_STATUS.memory ? "MEM" : "SEARCH";
    ctx.fillText(`${flightLabel} | ${seekerLabel}`, point.x + 10, point.y - 9);
    ctx.restore();
  });

  for (const event of simResult?.interceptor_events ?? []) {
    if (event.frame > frame || (event.type !== "hit" && event.type !== "miss")) continue;
    const point = w2s(event.position[0], event.position[1]);
    const hit = event.type === "hit";
    ctx.save();
    ctx.strokeStyle = hit ? "rgba(255, 209, 102, 0.9)" : "rgba(154, 164, 178, 0.72)";
    ctx.fillStyle = hit ? "rgba(255, 209, 102, 0.14)" : "rgba(154, 164, 178, 0.1)";
    ctx.lineWidth = hit ? 2 : 1.5;
    ctx.setLineDash(hit ? [] : [4, 4]);
    ctx.beginPath();
    ctx.arc(point.x, point.y, hit ? 16 : 12, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.setLineDash([]);
    if (hit) {
      for (let i = 0; i < 6; i += 1) {
        const a = (i * Math.PI) / 3;
        ctx.beginPath();
        ctx.moveTo(point.x + Math.cos(a) * 5, point.y + Math.sin(a) * 5);
        ctx.lineTo(point.x + Math.cos(a) * 21, point.y + Math.sin(a) * 21);
        ctx.stroke();
      }
    }
    ctx.fillStyle = hit ? "#ffd166" : "#9aa4b2";
    ctx.font = "700 9px JetBrains Mono, Consolas, monospace";
    ctx.fillText(`${hit ? "PN HIT" : "PN MISS"} ${event.miss_distance.toFixed(2)}m`, point.x + 18, point.y + 4);
    ctx.restore();
  }
}

function drawDefensiveEvasion(
  ctx: CanvasRenderingContext2D,
  simResult: SimResponse | null,
  playhead: number,
  w2s: (x: number, y: number) => { x: number; y: number },
) {
  const hist = simResult?.defensive_hist ?? [];
  if (!simResult?.pos?.length || hist.length === 0) return;

  const frame = Math.max(0, Math.min(playhead, hist.length - 1, simResult.pos.length - 1));
  const row = hist[frame];
  const active = Boolean(row && row[0] >= 0.5);

  ctx.save();
  for (const event of simResult.defensive_events ?? []) {
    if (event.frame > frame) continue;
    const target = w2s(event.escape_target[0], event.escape_target[1]);
    ctx.strokeStyle = "rgba(255, 193, 7, 0.35)";
    ctx.fillStyle = "rgba(255, 193, 7, 0.1)";
    ctx.lineWidth = 1.2;
    ctx.setLineDash([4, 5]);
    ctx.beginPath();
    ctx.arc(target.x, target.y, 11, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  }
  ctx.restore();

  if (!active) return;

  const own = simResult.pos[frame];
  const ownPoint = w2s(own[0], own[1]);
  const escapePoint = w2s(row[1], row[2]);
  const missilePoint = Number.isFinite(row[6]) && Number.isFinite(row[7])
    ? w2s(row[6], row[7])
    : null;

  ctx.save();
  ctx.shadowBlur = 15;
  ctx.shadowColor = "rgba(255, 193, 7, 0.75)";
  ctx.strokeStyle = "rgba(255, 193, 7, 0.95)";
  ctx.lineWidth = 2.4;
  ctx.setLineDash([10, 5]);
  ctx.beginPath();
  ctx.moveTo(ownPoint.x, ownPoint.y);
  ctx.lineTo(escapePoint.x, escapePoint.y);
  ctx.stroke();
  ctx.setLineDash([]);

  const angle = Math.atan2(escapePoint.y - ownPoint.y, escapePoint.x - ownPoint.x);
  ctx.translate(escapePoint.x, escapePoint.y);
  ctx.rotate(angle);
  ctx.fillStyle = "#ffc107";
  ctx.strokeStyle = "#060912";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(12, 0);
  ctx.lineTo(-8, 7);
  ctx.lineTo(-5, 0);
  ctx.lineTo(-8, -7);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  ctx.restore();

  if (missilePoint) {
    ctx.save();
    ctx.strokeStyle = "rgba(255, 82, 82, 0.65)";
    ctx.lineWidth = 1.5;
    ctx.setLineDash([3, 4]);
    ctx.beginPath();
    ctx.moveTo(missilePoint.x, missilePoint.y);
    ctx.lineTo(ownPoint.x, ownPoint.y);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.fillStyle = "#ff5252";
    ctx.font = "700 9px JetBrains Mono, Consolas, monospace";
    ctx.fillText("TGO " + (Number.isFinite(row[5]) ? row[5].toFixed(2) : "--") + "s", missilePoint.x + 10, missilePoint.y - 8);
    ctx.restore();
  }

  ctx.save();
  ctx.fillStyle = "#ffc107";
  ctx.font = "700 10px JetBrains Mono, Consolas, monospace";
  ctx.fillText("EVADE", escapePoint.x + 12, escapePoint.y + 4);
  ctx.fillStyle = "rgba(225,232,240,0.76)";
  ctx.font = "9px JetBrains Mono, Consolas, monospace";
  ctx.fillText(`z=${row[3].toFixed(1)}`, escapePoint.x + 12, escapePoint.y + 16);
  ctx.restore();
}

function drawMonteCarlo(
  ctx: CanvasRenderingContext2D,
  runs: Array<{ trajectory: Vec3[]; endpoint: Vec3; success: boolean }>,
  result: {
    waypoints: Vec3[];
    cep50_per_wp: number[];
    cep95_per_wp: number[];
  } | null,
  w2s: (x: number, y: number) => { x: number; y: number },
  playbackProgress: number,
) {
  if (runs.length === 0 && !result) return;
  const zoom = currentZoomFromW2s(w2s);

  runs.forEach((run, runIndex) => {
    if (run.trajectory.length > 1) {
      const latest = runIndex === runs.length - 1;
      ctx.strokeStyle = latest ? "rgba(179,136,255,0.22)" : "rgba(179,136,255,0.11)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      run.trajectory.forEach((p, index) => {
        const point = w2s(p[0], p[1]);
        if (index === 0) ctx.moveTo(point.x, point.y);
        else ctx.lineTo(point.x, point.y);
      });
      ctx.stroke();
    }

    const endpoint = w2s(run.endpoint[0], run.endpoint[1]);
    ctx.fillStyle = run.success ? "#2ecc71" : "#ff5252";
    ctx.strokeStyle = "#060912";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.arc(endpoint.x, endpoint.y, run.success ? 3.5 : 4.5, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  });

  const currentRun = runs[runs.length - 1];
  if (currentRun?.trajectory.length > 1) {
    const end = Math.max(1, Math.floor((currentRun.trajectory.length - 1) * playbackProgress));
    ctx.save();
    ctx.shadowBlur = 14;
    ctx.shadowColor = "rgba(179,136,255,0.85)";
    ctx.strokeStyle = "rgba(179,136,255,0.95)";
    ctx.lineWidth = 2.5;
    ctx.beginPath();
    for (let i = 0; i <= end; i += 1) {
      const p = currentRun.trajectory[i];
      const point = w2s(p[0], p[1]);
      if (i === 0) ctx.moveTo(point.x, point.y);
      else ctx.lineTo(point.x, point.y);
    }
    ctx.stroke();

    const head = currentRun.trajectory[end];
    const point = w2s(head[0], head[1]);
    ctx.fillStyle = "#b388ff";
    ctx.strokeStyle = "#060912";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.arc(point.x, point.y, 6, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
    ctx.restore();
  }

  result?.waypoints.forEach((wp, index) => {
    const point = w2s(wp[0], wp[1]);
    const cep50 = result.cep50_per_wp[index] ?? 0;
    const cep95 = result.cep95_per_wp[index] ?? 0;

    if (cep95 > 0) {
      ctx.strokeStyle = "rgba(179,136,255,0.82)";
      ctx.lineWidth = 1.4;
      ctx.setLineDash([7, 5]);
      ctx.beginPath();
      ctx.arc(point.x, point.y, cep95 * zoom, 0, Math.PI * 2);
      ctx.stroke();
    }
    if (cep50 > 0) {
      ctx.strokeStyle = "rgba(255,64,129,0.92)";
      ctx.lineWidth = 1.4;
      ctx.setLineDash([2, 4]);
      ctx.beginPath();
      ctx.arc(point.x, point.y, cep50 * zoom, 0, Math.PI * 2);
      ctx.stroke();
    }
    ctx.setLineDash([]);

    if (cep50 > 0 || cep95 > 0) {
      ctx.fillStyle = "#ff4081";
      ctx.font = "700 9px JetBrains Mono, Consolas, monospace";
      ctx.fillText(`CEP ${cep50.toFixed(2)}/${cep95.toFixed(2)}m`, point.x + 9, point.y + 18);
    }
  });
}

function drawLaunchDrone(
  ctx: CanvasRenderingContext2D,
  initialPosition: Vec3,
  w2s: (x: number, y: number) => { x: number; y: number },
  selectedTarget: DragTarget | null,
) {
  const point = w2s(initialPosition[0], initialPosition[1]);
  const selected = selectedTarget?.kind === "drone";

  ctx.save();
  ctx.shadowBlur = selected ? 18 : 10;
  ctx.shadowColor = "rgba(0,212,255,0.65)";
  ctx.strokeStyle = selected ? "rgba(0,212,255,0.95)" : "rgba(0,212,255,0.55)";
  ctx.lineWidth = selected ? 2 : 1.4;
  ctx.setLineDash([3, 5]);
  ctx.beginPath();
  ctx.arc(point.x, point.y, selected ? 18 : 15, 0, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);

  ctx.translate(point.x, point.y);
  ctx.fillStyle = selected ? "#72ecff" : "#00d4ff";
  ctx.strokeStyle = "#060912";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(13, 0);
  ctx.lineTo(-8, 7);
  ctx.lineTo(-4, 0);
  ctx.lineTo(-8, -7);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  ctx.restore();

  ctx.fillStyle = selected ? "#72ecff" : "#00d4ff";
  ctx.font = "700 10px JetBrains Mono, Consolas, monospace";
  ctx.fillText("DRONE", point.x + 16, point.y + 4);
  ctx.fillStyle = "rgba(225,232,240,0.7)";
  ctx.font = "9px JetBrains Mono, Consolas, monospace";
  ctx.fillText(`z=${initialPosition[2].toFixed(1)}`, point.x + 16, point.y + 16);
}

function currentZoomFromW2s(w2s: (x: number, y: number) => { x: number; y: number }) {
  return Math.abs(w2s(1, 0).x - w2s(0, 0).x);
}

function drawEnemies(
  ctx: CanvasRenderingContext2D,
  enemies: EnemyPayload[],
  enemyHist: number[][][],
  playhead: number,
  w2s: (x: number, y: number) => { x: number; y: number },
  selectedTarget: DragTarget | null,
) {
  enemies.forEach((enemy, index) => {
    const live = enemyHist[playhead]?.[index];
    const x = live?.[0] ?? enemy.x;
    const y = live?.[1] ?? enemy.y;
    const heading = live?.[3] ?? 0;
    const point = w2s(x, y);
    const selected = selectedTarget?.kind === "enemy" && selectedTarget.index === index;
    const zoom = currentZoomFromW2s(w2s);

    ctx.strokeStyle = "rgba(255,82,82,0.25)";
    ctx.setLineDash([3, 5]);
    ctx.beginPath();
    ctx.arc(point.x, point.y, enemy.det_r * zoom, 0, Math.PI * 2);
    ctx.stroke();
    ctx.setLineDash([]);

    if (enemyHist.length > 1) {
      ctx.strokeStyle = "rgba(255,82,82,0.35)";
      ctx.lineWidth = 1;
      ctx.beginPath();
      for (let i = 0; i <= playhead && i < enemyHist.length; i += Math.max(1, Math.floor(playhead / 300))) {
        const hist = enemyHist[i]?.[index];
        if (!hist) continue;
        const p = w2s(hist[0], hist[1]);
        if (i === 0) ctx.moveTo(p.x, p.y);
        else ctx.lineTo(p.x, p.y);
      }
      ctx.stroke();
    }

    ctx.save();
    ctx.translate(point.x, point.y);
    ctx.rotate(-heading);
    ctx.fillStyle = selected ? "#ff8a8a" : "#ff5252";
    ctx.strokeStyle = "#060912";
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(11, 0);
    ctx.lineTo(-8, 7);
    ctx.lineTo(-5, 0);
    ctx.lineTo(-8, -7);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    ctx.restore();
    ctx.fillStyle = "#ff5252";
    ctx.font = "700 10px JetBrains Mono, Consolas, monospace";
    ctx.fillText(enemy.name, point.x + 12, point.y - 8);
  });
}

function drawOwnship(
  ctx: CanvasRenderingContext2D,
  simResult: SimResponse | null,
  playhead: number,
  w2s: (x: number, y: number) => { x: number; y: number },
  truncateFrame: number,
) {
  if (!simResult?.pos.length) return;
  // After shoot-down, freeze the live ownship icon at the impact frame so
  // the explosion marker (drawn on top by drawShotDown) lands on it.
  const index = Math.min(playhead, truncateFrame, simResult.pos.length - 1);
  const pos = simResult.pos[index];
  const yaw = simResult.euler[index]?.[2] ?? 0;
  const point = w2s(pos[0], pos[1]);
  ctx.save();
  ctx.translate(point.x, point.y);
  ctx.rotate(-yaw);
  ctx.fillStyle = "#00d4ff";
  ctx.strokeStyle = "#060912";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  ctx.moveTo(12, 0);
  ctx.lineTo(-8, 7);
  ctx.lineTo(-4, 0);
  ctx.lineTo(-8, -7);
  ctx.closePath();
  ctx.fill();
  ctx.stroke();
  ctx.restore();
}

function drawShotDown(
  ctx: CanvasRenderingContext2D,
  w2s: (x: number, y: number) => { x: number; y: number },
  info: { x: number; y: number },
) {
  const point = w2s(info.x, info.y);
  ctx.save();
  ctx.shadowBlur = 18;
  ctx.shadowColor = "rgba(255, 82, 82, 0.85)";
  ctx.strokeStyle = "rgba(255, 82, 82, 1)";
  ctx.lineWidth = 2.2;
  ctx.beginPath();
  for (let i = 0; i < 8; i++) {
    const a = (i * Math.PI) / 4;
    const r1 = 5, r2 = 15;
    ctx.moveTo(point.x + Math.cos(a) * r1, point.y + Math.sin(a) * r1);
    ctx.lineTo(point.x + Math.cos(a) * r2, point.y + Math.sin(a) * r2);
  }
  ctx.stroke();
  ctx.shadowBlur = 0;

  ctx.fillStyle = "#ffd966";
  ctx.beginPath();
  ctx.arc(point.x, point.y, 3.5, 0, Math.PI * 2);
  ctx.fill();

  ctx.strokeStyle = "rgba(255, 82, 82, 0.55)";
  ctx.lineWidth = 1.2;
  ctx.setLineDash([3, 3]);
  ctx.beginPath();
  ctx.arc(point.x, point.y, 22, 0, Math.PI * 2);
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.restore();

  ctx.fillStyle = "#ff5252";
  ctx.font = "700 11px JetBrains Mono, Consolas, monospace";
  ctx.fillText("UAV DOWN", point.x + 20, point.y - 8);
}

function drawCompass(ctx: CanvasRenderingContext2D, width: number) {
  const cx = width - 34;
  const cy = 36;
  ctx.strokeStyle = "rgba(0, 212, 255, 0.55)";
  ctx.beginPath();
  ctx.arc(cx, cy, 20, 0, Math.PI * 2);
  ctx.stroke();
  ctx.fillStyle = "#ff4081";
  ctx.beginPath();
  ctx.moveTo(cx, cy - 16);
  ctx.lineTo(cx - 4, cy + 2);
  ctx.lineTo(cx + 4, cy + 2);
  ctx.closePath();
  ctx.fill();
  ctx.fillStyle = "#00d4ff";
  ctx.font = "700 9px JetBrains Mono, Consolas, monospace";
  ctx.textAlign = "center";
  ctx.fillText("N", cx, cy - 23);
  ctx.textAlign = "start";
}

function AddModeButton({
  active,
  icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: ReactElement;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "flex h-8 items-center justify-center gap-1.5 rounded-md border text-[0.68rem] font-semibold transition-colors",
        active ? "border-green/45 bg-green/15 text-green" : "border-cyan/15 bg-panel-2 text-text/75 hover:border-cyan/35",
      )}
    >
      {icon && <span className="[&_svg]:h-3.5 [&_svg]:w-3.5">{icon}</span>}
      {label}
    </button>
  );
}

function NumberField({
  label,
  value,
  onChange,
  min,
  step = 0.5,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  step?: number;
}) {
  return (
    <label className="space-y-1 text-xs text-muted">
      <span>{label}</span>
      <input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        min={min}
        step={step}
        onChange={(event) => onChange(Number(event.target.value))}
        className="field font-mono"
      />
    </label>
  );
}
