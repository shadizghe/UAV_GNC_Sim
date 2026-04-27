import { create } from "zustand";
import type {
  AntiAirConfig,
  DefensiveEvasionConfig,
  DroneDynamicsConfig,
  EnemyPayload,
  FriendlyDronePayload,
  FaultConfig,
  InterceptorBatteryPayload,
  MonteCarloConfig,
  MonteCarloMessage,
  MonteCarloResult,
  MonteCarloRun,
  PresetDetail,
  PresetSummary,
  SimResponse,
  SimRequest,
  Vec3,
  ZonePayload,
} from "./types";
import { api, defaultMonteCarloConfig, monteCarloWsUrl } from "./api";

const clonePreset = (preset: PresetDetail): PresetDetail => ({
  ...preset,
  waypoints: preset.waypoints.map((wp) => [...wp] as Vec3),
  yaws_deg: [...preset.yaws_deg],
  zones: preset.zones.map((zone) => ({ ...zone })),
  enemies: preset.enemies.map((enemy) => ({ ...enemy })),
});

const normalizeYaws = (waypoints: Vec3[], yaws: number[]): number[] => {
  if (yaws.length === waypoints.length) return yaws;
  if (yaws.length > waypoints.length) return yaws.slice(0, waypoints.length);
  return [...yaws, ...Array.from({ length: waypoints.length - yaws.length }, () => 0)];
};

const withEntityCounts = (preset: PresetDetail): PresetDetail => ({
  ...preset,
  n_waypoints: preset.waypoints.length,
  n_zones: preset.zones.length,
  n_enemies: preset.enemies.length,
});

const cloneVec3 = (value: Vec3): Vec3 => [...value] as Vec3;
const defaultDroneDynamics: DroneDynamicsConfig = {
  mass: 1.2,
  maxSpeedXY: 7.5,
  maxAccelXY: 8,
  maxTiltDeg: 35,
};

const defaultAntiAirConfig: AntiAirConfig = {
  enabled: true,
  batteries: [
    {
      name: "SAM-NORTH",
      x: 0,
      y: 2.7,
      z: 0,
      launch_range: 10.5,
      min_engage_alt: 1,
      cooldown: 1.4,
      max_active: 2,
      max_total_shots: 2,
      initial_speed: 5,
      nav_constant: 4,
      max_lateral_accel: 55,
      boost_time: 0.75,
      boost_accel: 32,
      coast_drag: 0.045,
      lethal_radius: 0.55,
      arming_time: 0.65,
      max_time: 8,
      seeker_enabled: true,
      seeker_range: 14,
      seeker_fov_deg: 70,
      seeker_noise_std_deg: 0.25,
      seeker_memory_time: 0.35,
    },
    {
      name: "SAM-SOUTH",
      x: 0,
      y: -2.7,
      z: 0,
      launch_range: 10.5,
      min_engage_alt: 1,
      cooldown: 1.4,
      max_active: 2,
      max_total_shots: 2,
      initial_speed: 5,
      nav_constant: 4,
      max_lateral_accel: 55,
      boost_time: 0.75,
      boost_accel: 32,
      coast_drag: 0.045,
      lethal_radius: 0.55,
      arming_time: 0.65,
      max_time: 8,
      seeker_enabled: true,
      seeker_range: 14,
      seeker_fov_deg: 70,
      seeker_noise_std_deg: 0.25,
      seeker_memory_time: 0.35,
    },
  ],
};

const defaultFaultConfig: FaultConfig = { motor: [], imu: [], gps: [] };
const defaultDefensiveEvasionConfig: DefensiveEvasionConfig = {
  enabled: true,
  mode: "corridor",
  detect_range: 14,
  trigger_tgo: 5,
  hold_time: 2,
  escape_distance: 6.8,
  altitude_delta: 1.1,
  emergency_max_tilt_deg: 60,
  emergency_max_accel_xy: 16,
  emergency_max_speed_xy: 12,
};

const sanitizeBattery = (
  battery: InterceptorBatteryPayload,
  fallbackName: string,
): InterceptorBatteryPayload => ({
  ...battery,
  name: battery.name.trim() || fallbackName,
  x: Number.isFinite(battery.x) ? battery.x : 0,
  y: Number.isFinite(battery.y) ? battery.y : 0,
  z: Math.max(0, Number.isFinite(battery.z) ? battery.z : 0),
  launch_range: Math.max(0.5, Number(battery.launch_range) || 0.5),
  min_engage_alt: Math.max(0, Number(battery.min_engage_alt) || 0),
  cooldown: Math.max(0, Number(battery.cooldown) || 0),
  max_active: Math.max(1, Math.min(8, Math.round(Number(battery.max_active) || 1))),
  max_total_shots: Math.max(1, Math.min(24, Math.round(Number(battery.max_total_shots) || 1))),
  initial_speed: Math.max(0.1, Number(battery.initial_speed) || 0.1),
  nav_constant: Math.max(0.5, Number(battery.nav_constant) || 0.5),
  max_lateral_accel: Math.max(1, Number(battery.max_lateral_accel) || 1),
  boost_time: Math.max(0, Number(battery.boost_time) || 0),
  boost_accel: Math.max(0, Number(battery.boost_accel) || 0),
  coast_drag: Math.max(0, Number(battery.coast_drag) || 0),
  lethal_radius: Math.max(0.05, Number(battery.lethal_radius) || 0.05),
  arming_time: Math.max(0, Number(battery.arming_time) || 0),
  max_time: Math.max(0.1, Number(battery.max_time) || 0.1),
  seeker_enabled: battery.seeker_enabled ?? true,
  seeker_range: Math.max(0.5, Number(battery.seeker_range) || 0.5),
  seeker_fov_deg: Math.max(1, Math.min(180, Number(battery.seeker_fov_deg) || 1)),
  seeker_noise_std_deg: Math.max(0, Number(battery.seeker_noise_std_deg) || 0),
  seeker_memory_time: Math.max(0, Number(battery.seeker_memory_time) || 0),
});

const cloneDefensiveEvasionConfig = (
  cfg: DefensiveEvasionConfig,
): DefensiveEvasionConfig => ({
  enabled: cfg.enabled,
  mode: cfg.mode === "beam" ? "beam" : "corridor",
  detect_range: Math.max(0.5, Number(cfg.detect_range) || 0.5),
  trigger_tgo: Math.max(0.1, Number(cfg.trigger_tgo) || 0.1),
  hold_time: Math.max(0.1, Number(cfg.hold_time) || 0.1),
  escape_distance: Math.max(0.5, Number(cfg.escape_distance) || 0.5),
  altitude_delta: Number.isFinite(cfg.altitude_delta) ? cfg.altitude_delta : 0,
  emergency_max_tilt_deg: Math.max(1, Math.min(80, Number(cfg.emergency_max_tilt_deg) || 1)),
  emergency_max_accel_xy: Math.max(0.2, Number(cfg.emergency_max_accel_xy) || 0.2),
  emergency_max_speed_xy: Math.max(0.2, Number(cfg.emergency_max_speed_xy) || 0.2),
});

const cloneAntiAirConfig = (cfg: AntiAirConfig): AntiAirConfig => ({
  enabled: cfg.enabled,
  batteries: cfg.batteries.map((battery, index) => (
    sanitizeBattery(battery, `SAM-${index + 1}`)
  )),
});

const cloneFaultConfig = (cfg: FaultConfig): FaultConfig => ({
  motor: cfg.motor.map((f) => ({ ...f })),
  imu:   cfg.imu.map((f) => ({ ...f })),
  gps:   cfg.gps.map((f) => ({ ...f })),
});

const sanitizeFriendlyDrone = (
  drone: FriendlyDronePayload,
  fallbackName: string,
): FriendlyDronePayload => ({
  name: drone.name.trim() || fallbackName,
  x: Number.isFinite(drone.x) ? drone.x : 0,
  y: Number.isFinite(drone.y) ? drone.y : 0,
  z: Math.max(0, Number.isFinite(drone.z) ? drone.z : 0),
  route_mode: drone.route_mode === "same" ? "same" : "formation",
  enabled: drone.enabled ?? true,
});

const cloneFriendlyDrones = (drones: FriendlyDronePayload[]): FriendlyDronePayload[] => (
  drones.map((drone, index) => sanitizeFriendlyDrone(drone, `UAV-${index + 2}`))
);

const buildSimRequest = (
  preset: PresetDetail,
  acceptRadius: number,
  initialPosition: Vec3,
  droneDynamics: DroneDynamicsConfig,
  antiAirConfig: AntiAirConfig,
  defensiveEvasionConfig: DefensiveEvasionConfig,
  friendlyDrones: FriendlyDronePayload[],
  faults: FaultConfig,
  enableReplanning: boolean,
): SimRequest => ({
  waypoints: preset.waypoints as [number, number, number][],
  yaws_deg: preset.yaws_deg,
  zones: preset.zones,
  enemies: preset.enemies,
  friendlies: cloneFriendlyDrones(friendlyDrones),
  duration_s: preset.duration_s,
  initial_position: initialPosition,
  mass: droneDynamics.mass,
  accept_radius: acceptRadius,
  enable_threats: preset.enable_threats,
  enable_replanning: enableReplanning,
  enable_geofence: preset.enable_geofence,
  gains: {
    max_speed_xy: droneDynamics.maxSpeedXY,
    max_accel_xy: droneDynamics.maxAccelXY,
    max_tilt_deg: droneDynamics.maxTiltDeg,
  },
  anti_air: cloneAntiAirConfig(antiAirConfig),
  defensive_evasion: cloneDefensiveEvasionConfig(defensiveEvasionConfig),
  faults,
});

const markMissionDirty = (
  preset: PresetDetail,
  selectedWaypointIndex: number,
): Partial<AppState> => ({
  currentPreset: withEntityCounts(preset),
  selectedWaypointIndex: Math.max(0, Math.min(selectedWaypointIndex, preset.waypoints.length - 1)),
  simResult: null,
  missionDirty: true,
  replayIndex: 0,
  replayPlaying: false,
  monteCarloRuns: [],
  monteCarloResult: null,
  monteCarloError: null,
  monteCarloProgress: 0,
});

interface AppState {
  // Preset catalogue + currently loaded mission
  presetSummaries: PresetSummary[];
  currentPreset: PresetDetail | null;
  loadedPresetBaseline: PresetDetail | null;
  loadingPreset: boolean;
  selectedWaypointIndex: number;
  missionDirty: boolean;
  acceptRadius: number;
  initialPosition: Vec3;
  loadedInitialPositionBaseline: Vec3;
  droneDynamics: DroneDynamicsConfig;
  antiAirConfig: AntiAirConfig;
  defensiveEvasionConfig: DefensiveEvasionConfig;
  friendlyDrones: FriendlyDronePayload[];
  loadedDroneDynamicsBaseline: DroneDynamicsConfig;
  faultConfig: FaultConfig;
  enableReplanning: boolean;
  loadedEnableReplanningBaseline: boolean;

  // Latest sim run
  simResult: SimResponse | null;
  simRunning: boolean;
  simError: string | null;
  replayIndex: number;
  replayPlaying: boolean;
  replaySpeed: number;

  // Monte Carlo sweep
  monteCarloConfig: MonteCarloConfig;
  monteCarloRuns: MonteCarloRun[];
  monteCarloResult: MonteCarloResult | null;
  monteCarloRunning: boolean;
  monteCarloError: string | null;
  monteCarloProgress: number;

  // Simulation room view controls
  sceneRoomMode: "range" | "night" | "analysis";
  sceneCameraPreset: "orbit" | "top" | "chase";
  sceneEditTarget: { kind: "enemy" | "zone" | "battery" | "friendly"; index: number } | null;
  // Visual-layer toggles (terrain mesh, particle FX, post-processing, HDRi sky)
  showTerrain:   boolean;
  showParticles: boolean;
  showPostFX:    boolean;
  showSky:       boolean;
  showRadarSweep: boolean;
  soundEnabled:  boolean;

  // Actions
  fetchPresetList: () => Promise<void>;
  loadPreset:      (label: string) => Promise<void>;
  runSimulation:   () => Promise<void>;
  selectWaypoint:  (index: number) => void;
  updateWaypoint:  (index: number, waypoint: Vec3) => void;
  updateWaypointAxis: (index: number, axis: 0 | 1 | 2, value: number) => void;
  updateYaw:       (index: number, value: number) => void;
  addWaypoint:     (waypoint?: Vec3, yawDeg?: number) => void;
  duplicateWaypoint: (index?: number) => void;
  deleteWaypoint:  (index?: number) => void;
  resetMissionPlan: () => void;
  setAcceptRadius: (value: number) => void;
  setDuration:     (value: number) => void;
  setFaultConfig:  (cfg: FaultConfig) => void;
  clearFaults:     () => void;
  updateEnemyPosition: (index: number, x: number, y: number) => void;
  updateEnemy: (index: number, patch: Partial<EnemyPayload>) => void;
  deleteEnemy: (index: number) => void;
  addEnemy:       (enemy: EnemyPayload) => void;
  addFriendlyDrone: (drone?: Partial<FriendlyDronePayload>) => void;
  updateFriendlyDrone: (index: number, patch: Partial<FriendlyDronePayload>) => void;
  updateFriendlyDronePosition: (index: number, x: number, y: number) => void;
  deleteFriendlyDrone: (index: number) => void;
  resetFriendlyDrones: () => void;
  updateZonePosition: (index: number, cx: number, cy: number) => void;
  updateZone: (index: number, patch: Partial<ZonePayload>) => void;
  deleteZone: (index: number) => void;
  addZone:        (zone: ZonePayload) => void;
  updateBattery: (index: number, patch: Partial<InterceptorBatteryPayload>) => void;
  addBattery: () => void;
  deleteBattery: (index: number) => void;
  resetAntiAirConfig: () => void;
  selectSceneEditTarget: (target: AppState["sceneEditTarget"]) => void;
  setInitialPosition: (position: Vec3) => void;
  updateInitialPositionAxis: (axis: 0 | 1 | 2, value: number) => void;
  resetInitialPosition: () => void;
  setDroneDynamics: (patch: Partial<DroneDynamicsConfig>) => void;
  setAntiAirConfig: (patch: Partial<AntiAirConfig>) => void;
  setDefensiveEvasionConfig: (patch: Partial<DefensiveEvasionConfig>) => void;
  resetDroneDynamics: () => void;
  setEnableReplanning: (value: boolean) => void;
  setReplayIndex: (index: number) => void;
  setReplayPlaying: (playing: boolean) => void;
  setReplaySpeed: (speed: number) => void;
  setSceneRoomMode: (mode: AppState["sceneRoomMode"]) => void;
  setSceneCameraPreset: (preset: AppState["sceneCameraPreset"]) => void;
  setShowTerrain:   (value: boolean) => void;
  setShowParticles: (value: boolean) => void;
  setShowPostFX:    (value: boolean) => void;
  setShowSky:       (value: boolean) => void;
  setShowRadarSweep:(value: boolean) => void;
  setSoundEnabled:  (value: boolean) => void;
  runMonteCarlo: (config?: Partial<MonteCarloConfig>) => Promise<void>;
  clearMonteCarlo: () => void;
}

export const useAppStore = create<AppState>((set, get) => ({
  presetSummaries: [],
  currentPreset: null,
  loadedPresetBaseline: null,
  loadingPreset: false,
  selectedWaypointIndex: 0,
  missionDirty: false,
  acceptRadius: 0.35,
  initialPosition: [0, 0, 0],
  loadedInitialPositionBaseline: [0, 0, 0],
  droneDynamics: defaultDroneDynamics,
  antiAirConfig: cloneAntiAirConfig(defaultAntiAirConfig),
  defensiveEvasionConfig: cloneDefensiveEvasionConfig(defaultDefensiveEvasionConfig),
  friendlyDrones: [],
  loadedDroneDynamicsBaseline: defaultDroneDynamics,
  faultConfig: defaultFaultConfig,
  enableReplanning: true,
  loadedEnableReplanningBaseline: true,
  simResult: null,
  simRunning: false,
  simError: null,
  replayIndex: 0,
  replayPlaying: false,
  replaySpeed: 1,
  monteCarloConfig: defaultMonteCarloConfig,
  monteCarloRuns: [],
  monteCarloResult: null,
  monteCarloRunning: false,
  monteCarloError: null,
  monteCarloProgress: 0,
  sceneRoomMode: "range",
  sceneCameraPreset: "orbit",
  showTerrain: true,
  showParticles: true,
  showPostFX: true,
  showSky: true,
  showRadarSweep: true,
  soundEnabled: false,
  sceneEditTarget: null,

  fetchPresetList: async () => {
    const presets = await api.listPresets();
    set({ presetSummaries: presets });
    // Auto-load the first preset on cold start.
    if (!get().currentPreset && presets.length > 0) {
      await get().loadPreset(presets[0].label);
    }
  },

  loadPreset: async (label: string) => {
    set({ loadingPreset: true, simError: null });
    try {
      const detail = await api.getPreset(label);
      const defaultEnableReplanning =
        detail.enable_threats || detail.zones.some((zone) => zone.kind === "threat" || zone.kind === "no_fly");
      const normalizedDetail = clonePreset({
        ...detail,
        waypoints: detail.waypoints.map((wp) => [...wp] as Vec3),
        yaws_deg: normalizeYaws(detail.waypoints as Vec3[], detail.yaws_deg),
      });
      set({
        currentPreset: clonePreset(normalizedDetail),
        loadedPresetBaseline: clonePreset(normalizedDetail),
        initialPosition: [0, 0, 0],
        loadedInitialPositionBaseline: [0, 0, 0],
        droneDynamics: defaultDroneDynamics,
        antiAirConfig: cloneAntiAirConfig(defaultAntiAirConfig),
        defensiveEvasionConfig: cloneDefensiveEvasionConfig(defaultDefensiveEvasionConfig),
        friendlyDrones: [],
        loadedDroneDynamicsBaseline: defaultDroneDynamics,
        enableReplanning: defaultEnableReplanning,
        loadedEnableReplanningBaseline: defaultEnableReplanning,
        selectedWaypointIndex: 0,
        missionDirty: false,
        simResult: null,
        replayIndex: 0,
        replayPlaying: false,
        monteCarloRuns: [],
        monteCarloResult: null,
        monteCarloError: null,
        monteCarloProgress: 0,
        sceneEditTarget: null,
      });
      // Kick off a sim run immediately so the scene isn't empty.
      void get().runSimulation();
    } finally {
      set({ loadingPreset: false });
    }
  },

  runSimulation: async () => {
    const preset = get().currentPreset;
    if (!preset) return;
    set({ simRunning: true, simError: null });
    try {
      const req = buildSimRequest(
        preset,
        get().acceptRadius,
        get().initialPosition,
        get().droneDynamics,
        get().antiAirConfig,
        get().defensiveEvasionConfig,
        get().friendlyDrones,
        get().faultConfig,
        get().enableReplanning,
      );
      const result = await api.simulate(req);
      set({
        simResult: result,
        missionDirty: false,
        replayIndex: Math.max(0, result.t.length - 1),
        replayPlaying: false,
      });
    } catch (err) {
      set({ simError: err instanceof Error ? err.message : String(err) });
    } finally {
      set({ simRunning: false });
    }
  },

  selectWaypoint: (index: number) => {
    const waypointCount = get().currentPreset?.waypoints.length ?? 0;
    if (waypointCount === 0) return;
    set({
      selectedWaypointIndex: Math.max(0, Math.min(index, waypointCount - 1)),
      sceneEditTarget: null,
    });
  },

  updateWaypoint: (index: number, waypoint: Vec3) => {
    const preset = get().currentPreset;
    if (!preset || index < 0 || index >= preset.waypoints.length) return;
    const next = clonePreset(preset);
    next.waypoints[index] = waypoint.map((value) => Number(value)) as Vec3;
    set({ ...markMissionDirty(next, index), sceneEditTarget: null });
  },

  updateWaypointAxis: (index: number, axis: 0 | 1 | 2, value: number) => {
    const preset = get().currentPreset;
    if (!preset || index < 0 || index >= preset.waypoints.length) return;
    const nextWp = [...preset.waypoints[index]] as Vec3;
    nextWp[axis] = Number.isFinite(value) ? value : 0;
    get().updateWaypoint(index, nextWp);
  },

  updateYaw: (index: number, value: number) => {
    const preset = get().currentPreset;
    if (!preset || index < 0 || index >= preset.waypoints.length) return;
    const next = clonePreset(preset);
    next.yaws_deg = normalizeYaws(next.waypoints, next.yaws_deg);
    next.yaws_deg[index] = Number.isFinite(value) ? value : 0;
    set(markMissionDirty(next, index));
  },

  addWaypoint: (waypoint?: Vec3, yawDeg = 0) => {
    const preset = get().currentPreset;
    if (!preset) return;
    const next = clonePreset(preset);
    const last = next.waypoints[next.waypoints.length - 1] ?? ([0, 0, 2] as Vec3);
    const wp = waypoint ?? ([last[0] + 1.5, last[1] + 1.5, last[2]] as Vec3);
    next.waypoints.push(wp.map((value) => Number(value)) as Vec3);
    next.yaws_deg = normalizeYaws(next.waypoints, [...next.yaws_deg, yawDeg]);
    set(markMissionDirty(next, next.waypoints.length - 1));
  },

  duplicateWaypoint: (index?: number) => {
    const preset = get().currentPreset;
    if (!preset) return;
    const sourceIndex = index ?? get().selectedWaypointIndex;
    if (sourceIndex < 0 || sourceIndex >= preset.waypoints.length) return;
    const next = clonePreset(preset);
    const source = next.waypoints[sourceIndex];
    next.waypoints.splice(sourceIndex + 1, 0, [source[0] + 0.8, source[1] + 0.8, source[2]]);
    const yaws = normalizeYaws(preset.waypoints, preset.yaws_deg);
    next.yaws_deg = [...yaws.slice(0, sourceIndex + 1), yaws[sourceIndex] ?? 0, ...yaws.slice(sourceIndex + 1)];
    set(markMissionDirty(next, sourceIndex + 1));
  },

  deleteWaypoint: (index?: number) => {
    const preset = get().currentPreset;
    if (!preset || preset.waypoints.length <= 2) return;
    const deleteIndex = index ?? get().selectedWaypointIndex;
    if (deleteIndex < 0 || deleteIndex >= preset.waypoints.length) return;
    const next = clonePreset(preset);
    next.waypoints.splice(deleteIndex, 1);
    next.yaws_deg = normalizeYaws(next.waypoints, next.yaws_deg.filter((_, i) => i !== deleteIndex));
    set(markMissionDirty(next, Math.min(deleteIndex, next.waypoints.length - 1)));
  },

  resetMissionPlan: () => {
    const baseline = get().loadedPresetBaseline;
    if (!baseline) return;
    set({
      currentPreset: clonePreset(baseline),
      initialPosition: cloneVec3(get().loadedInitialPositionBaseline),
      droneDynamics: { ...get().loadedDroneDynamicsBaseline },
      antiAirConfig: cloneAntiAirConfig(defaultAntiAirConfig),
      defensiveEvasionConfig: cloneDefensiveEvasionConfig(defaultDefensiveEvasionConfig),
      friendlyDrones: [],
      enableReplanning: get().loadedEnableReplanningBaseline,
      selectedWaypointIndex: 0,
      simResult: null,
      missionDirty: true,
      replayIndex: 0,
      replayPlaying: false,
      monteCarloRuns: [],
      monteCarloResult: null,
      monteCarloError: null,
      monteCarloProgress: 0,
      sceneEditTarget: null,
    });
  },

  setAcceptRadius: (value: number) => {
    set({
      acceptRadius: Number.isFinite(value) ? value : 0.35,
      simResult: null,
      missionDirty: true,
      replayIndex: 0,
      replayPlaying: false,
      monteCarloRuns: [],
      monteCarloResult: null,
      monteCarloError: null,
      monteCarloProgress: 0,
    });
  },

  setDuration: (value: number) => {
    const preset = get().currentPreset;
    if (!preset) return;
    const next = clonePreset(preset);
    next.duration_s = Number.isFinite(value) ? value : preset.duration_s;
    set(markMissionDirty(next, get().selectedWaypointIndex));
  },

  updateEnemyPosition: (index: number, x: number, y: number) => {
    const preset = get().currentPreset;
    if (!preset || index < 0 || index >= preset.enemies.length) return;
    const next = clonePreset(preset);
    next.enemies[index] = {
      ...next.enemies[index],
      x: Number.isFinite(x) ? x : next.enemies[index].x,
      y: Number.isFinite(y) ? y : next.enemies[index].y,
    };
    set({ ...markMissionDirty(next, get().selectedWaypointIndex), sceneEditTarget: { kind: "enemy", index } });
  },

  updateEnemy: (index: number, patch: Partial<EnemyPayload>) => {
    const preset = get().currentPreset;
    if (!preset || index < 0 || index >= preset.enemies.length) return;
    const next = clonePreset(preset);
    next.enemies[index] = {
      ...next.enemies[index],
      ...patch,
    };
    next.enemies[index].speed = Math.max(0, Number(next.enemies[index].speed) || 0);
    next.enemies[index].det_r = Math.max(0.1, Number(next.enemies[index].det_r) || 0.1);
    next.enemies[index].leth_r = Math.max(0.05, Number(next.enemies[index].leth_r) || 0.05);
    next.enemies[index].orbit_r = Math.max(0, Number(next.enemies[index].orbit_r) || 0);
    set({ ...markMissionDirty(next, get().selectedWaypointIndex), sceneEditTarget: { kind: "enemy", index } });
  },

  deleteEnemy: (index: number) => {
    const preset = get().currentPreset;
    if (!preset || index < 0 || index >= preset.enemies.length) return;
    const next = clonePreset(preset);
    next.enemies.splice(index, 1);
    if (next.enemies.length === 0) next.enable_threats = false;
    set({ ...markMissionDirty(next, get().selectedWaypointIndex), sceneEditTarget: null });
  },

  addEnemy: (enemy: EnemyPayload) => {
    const preset = get().currentPreset;
    if (!preset) return;
    const next = clonePreset(preset);
    next.enemies.push({ ...enemy });
    next.enable_threats = true;
    set({ ...markMissionDirty(next, get().selectedWaypointIndex), sceneEditTarget: { kind: "enemy", index: next.enemies.length - 1 } });
  },

  addFriendlyDrone: (drone?: Partial<FriendlyDronePayload>) => {
    const index = get().friendlyDrones.length;
    const base = get().initialPosition;
    const nextDrone = sanitizeFriendlyDrone({
      name: `UAV-${index + 2}`,
      x: base[0],
      y: base[1] + (index % 2 === 0 ? -0.9 : 0.9) * (Math.floor(index / 2) + 1),
      z: base[2],
      route_mode: "formation",
      enabled: true,
      ...drone,
    }, `UAV-${index + 2}`);
    set({
      friendlyDrones: [...get().friendlyDrones.map((item) => ({ ...item })), nextDrone],
      simResult: null,
      simError: null,
      missionDirty: true,
      replayIndex: 0,
      replayPlaying: false,
      monteCarloRuns: [],
      monteCarloResult: null,
      monteCarloError: null,
      monteCarloProgress: 0,
      sceneEditTarget: { kind: "friendly", index },
    });
  },

  updateFriendlyDrone: (index: number, patch: Partial<FriendlyDronePayload>) => {
    const current = get().friendlyDrones;
    if (index < 0 || index >= current.length) return;
    const friendlyDrones = current.map((drone, droneIndex) => (
      droneIndex === index
        ? sanitizeFriendlyDrone({ ...drone, ...patch }, drone.name || `UAV-${droneIndex + 2}`)
        : { ...drone }
    ));
    set({
      friendlyDrones,
      simResult: null,
      simError: null,
      missionDirty: true,
      replayIndex: 0,
      replayPlaying: false,
      monteCarloRuns: [],
      monteCarloResult: null,
      monteCarloError: null,
      monteCarloProgress: 0,
      sceneEditTarget: { kind: "friendly", index },
    });
  },

  updateFriendlyDronePosition: (index: number, x: number, y: number) => {
    get().updateFriendlyDrone(index, { x, y });
  },

  deleteFriendlyDrone: (index: number) => {
    const current = get().friendlyDrones;
    if (index < 0 || index >= current.length) return;
    set({
      friendlyDrones: current.filter((_, droneIndex) => droneIndex !== index),
      simResult: null,
      simError: null,
      missionDirty: true,
      replayIndex: 0,
      replayPlaying: false,
      monteCarloRuns: [],
      monteCarloResult: null,
      monteCarloError: null,
      monteCarloProgress: 0,
      sceneEditTarget: null,
    });
  },

  resetFriendlyDrones: () => {
    set({
      friendlyDrones: [],
      simResult: null,
      simError: null,
      missionDirty: true,
      replayIndex: 0,
      replayPlaying: false,
      monteCarloRuns: [],
      monteCarloResult: null,
      monteCarloError: null,
      monteCarloProgress: 0,
      sceneEditTarget: null,
    });
  },

  updateZonePosition: (index: number, cx: number, cy: number) => {
    const preset = get().currentPreset;
    if (!preset || index < 0 || index >= preset.zones.length) return;
    const next = clonePreset(preset);
    next.zones[index] = {
      ...next.zones[index],
      cx: Number.isFinite(cx) ? cx : next.zones[index].cx,
      cy: Number.isFinite(cy) ? cy : next.zones[index].cy,
    };
    set({ ...markMissionDirty(next, get().selectedWaypointIndex), sceneEditTarget: { kind: "zone", index } });
  },

  updateZone: (index: number, patch: Partial<ZonePayload>) => {
    const preset = get().currentPreset;
    if (!preset || index < 0 || index >= preset.zones.length) return;
    const next = clonePreset(preset);
    next.zones[index] = {
      ...next.zones[index],
      ...patch,
    };
    next.zones[index].r = Math.max(0.1, Number(next.zones[index].r) || 0.1);
    next.zones[index].z_min = Math.max(0, Number(next.zones[index].z_min) || 0);
    next.zones[index].z_max = Math.max(next.zones[index].z_min + 0.1, Number(next.zones[index].z_max) || next.zones[index].z_min + 0.1);
    set({ ...markMissionDirty(next, get().selectedWaypointIndex), sceneEditTarget: { kind: "zone", index } });
  },

  deleteZone: (index: number) => {
    const preset = get().currentPreset;
    if (!preset || index < 0 || index >= preset.zones.length) return;
    const next = clonePreset(preset);
    next.zones.splice(index, 1);
    if (next.zones.length === 0) next.enable_geofence = false;
    set({ ...markMissionDirty(next, get().selectedWaypointIndex), sceneEditTarget: null });
  },

  addZone: (zone: ZonePayload) => {
    const preset = get().currentPreset;
    if (!preset) return;
    const next = clonePreset(preset);
    next.zones.push({ ...zone });
    next.enable_geofence = true;
    set({ ...markMissionDirty(next, get().selectedWaypointIndex), sceneEditTarget: { kind: "zone", index: next.zones.length - 1 } });
  },

  updateBattery: (index: number, patch: Partial<InterceptorBatteryPayload>) => {
    const current = get().antiAirConfig;
    if (index < 0 || index >= current.batteries.length) return;
    const batteries = current.batteries.map((battery, batteryIndex) => (
      batteryIndex === index
        ? sanitizeBattery({ ...battery, ...patch }, battery.name || `SAM-${batteryIndex + 1}`)
        : { ...battery }
    ));
    set({
      antiAirConfig: { ...current, batteries },
      simResult: null,
      simError: null,
      missionDirty: true,
      replayIndex: 0,
      replayPlaying: false,
      monteCarloRuns: [],
      monteCarloResult: null,
      monteCarloError: null,
      monteCarloProgress: 0,
      sceneEditTarget: { kind: "battery", index },
    });
  },

  addBattery: () => {
    const current = get().antiAirConfig;
    const index = current.batteries.length;
    const nextBattery = sanitizeBattery({
      ...(current.batteries[index - 1] ?? defaultAntiAirConfig.batteries[0]),
      name: `SAM-${index + 1}`,
      x: index % 2 === 0 ? 3.2 : -3.2,
      y: index % 2 === 0 ? 3.2 : -3.2,
    }, `SAM-${index + 1}`);
    set({
      antiAirConfig: {
        enabled: true,
        batteries: [...current.batteries.map((battery) => ({ ...battery })), nextBattery],
      },
      simResult: null,
      simError: null,
      missionDirty: true,
      replayIndex: 0,
      replayPlaying: false,
      monteCarloRuns: [],
      monteCarloResult: null,
      monteCarloError: null,
      monteCarloProgress: 0,
      sceneEditTarget: { kind: "battery", index },
    });
  },

  deleteBattery: (index: number) => {
    const current = get().antiAirConfig;
    if (index < 0 || index >= current.batteries.length) return;
    set({
      antiAirConfig: {
        ...current,
        batteries: current.batteries.filter((_, batteryIndex) => batteryIndex !== index),
      },
      simResult: null,
      simError: null,
      missionDirty: true,
      replayIndex: 0,
      replayPlaying: false,
      monteCarloRuns: [],
      monteCarloResult: null,
      monteCarloError: null,
      monteCarloProgress: 0,
      sceneEditTarget: null,
    });
  },

  selectSceneEditTarget: (target: AppState["sceneEditTarget"]) => {
    set({ sceneEditTarget: target });
  },

  setInitialPosition: (position: Vec3) => {
    const clean = position.map((value, index) => {
      const fallback = index === 2 ? 0 : 0;
      return Number.isFinite(value) ? Number(value) : fallback;
    }) as Vec3;
    clean[2] = Math.max(0, clean[2]);
    set({
      initialPosition: clean,
      simResult: null,
      simError: null,
      missionDirty: true,
      replayIndex: 0,
      replayPlaying: false,
      monteCarloRuns: [],
      monteCarloResult: null,
      monteCarloError: null,
      monteCarloProgress: 0,
    });
  },

  updateInitialPositionAxis: (axis: 0 | 1 | 2, value: number) => {
    const next = cloneVec3(get().initialPosition);
    next[axis] = Number.isFinite(value) ? value : 0;
    if (axis === 2) next[axis] = Math.max(0, next[axis]);
    get().setInitialPosition(next);
  },

  resetInitialPosition: () => {
    get().setInitialPosition(cloneVec3(get().loadedInitialPositionBaseline));
  },

  setDroneDynamics: (patch: Partial<DroneDynamicsConfig>) => {
    const current = get().droneDynamics;
    const next: DroneDynamicsConfig = {
      mass: Math.max(0.2, Number(patch.mass ?? current.mass) || current.mass),
      maxSpeedXY: Math.max(0.2, Number(patch.maxSpeedXY ?? current.maxSpeedXY) || current.maxSpeedXY),
      maxAccelXY: Math.max(0.2, Number(patch.maxAccelXY ?? current.maxAccelXY) || current.maxAccelXY),
      maxTiltDeg: Math.max(1, Math.min(80, Number(patch.maxTiltDeg ?? current.maxTiltDeg) || current.maxTiltDeg)),
    };
    set({
      droneDynamics: next,
      simResult: null,
      simError: null,
      missionDirty: true,
      replayIndex: 0,
      replayPlaying: false,
      monteCarloRuns: [],
      monteCarloResult: null,
      monteCarloError: null,
      monteCarloProgress: 0,
    });
  },

  resetDroneDynamics: () => {
    get().setDroneDynamics({ ...get().loadedDroneDynamicsBaseline });
  },

  setAntiAirConfig: (patch: Partial<AntiAirConfig>) => {
    const current = get().antiAirConfig;
    const next = {
      enabled: patch.enabled ?? current.enabled,
      batteries: patch.batteries
        ? patch.batteries.map((battery, index) => sanitizeBattery(battery, `SAM-${index + 1}`))
        : current.batteries.map((battery, index) => sanitizeBattery(battery, `SAM-${index + 1}`)),
    };
    set({
      antiAirConfig: next,
      simResult: null,
      simError: null,
      missionDirty: true,
      replayIndex: 0,
      replayPlaying: false,
      monteCarloRuns: [],
      monteCarloResult: null,
      monteCarloError: null,
      monteCarloProgress: 0,
    });
  },

  setDefensiveEvasionConfig: (patch: Partial<DefensiveEvasionConfig>) => {
    set({
      defensiveEvasionConfig: cloneDefensiveEvasionConfig({
        ...get().defensiveEvasionConfig,
        ...patch,
      }),
      simResult: null,
      simError: null,
      missionDirty: true,
      replayIndex: 0,
      replayPlaying: false,
      monteCarloRuns: [],
      monteCarloResult: null,
      monteCarloError: null,
      monteCarloProgress: 0,
    });
  },

  resetAntiAirConfig: () => {
    set({
      antiAirConfig: cloneAntiAirConfig(defaultAntiAirConfig),
      simResult: null,
      simError: null,
      missionDirty: true,
      replayIndex: 0,
      replayPlaying: false,
      monteCarloRuns: [],
      monteCarloResult: null,
      monteCarloError: null,
      monteCarloProgress: 0,
      sceneEditTarget: null,
    });
  },

  setEnableReplanning: (value: boolean) => {
    set({
      enableReplanning: value,
      simResult: null,
      simError: null,
      missionDirty: true,
      replayIndex: 0,
      replayPlaying: false,
      monteCarloRuns: [],
      monteCarloResult: null,
      monteCarloError: null,
      monteCarloProgress: 0,
    });
  },

  setReplayIndex: (index: number) => {
    const maxIndex = Math.max(0, (get().simResult?.t.length ?? 1) - 1);
    set({ replayIndex: Math.max(0, Math.min(Math.floor(index), maxIndex)) });
  },

  setReplayPlaying: (playing: boolean) => {
    set({ replayPlaying: playing });
  },

  setReplaySpeed: (speed: number) => {
    set({ replaySpeed: Number.isFinite(speed) ? speed : 1 });
  },

  setShowTerrain:   (value: boolean) => set({ showTerrain: value }),
  setShowParticles: (value: boolean) => set({ showParticles: value }),
  setShowPostFX:    (value: boolean) => set({ showPostFX: value }),
  setShowSky:       (value: boolean) => set({ showSky: value }),
  setShowRadarSweep:(value: boolean) => set({ showRadarSweep: value }),
  setSoundEnabled:  (value: boolean) => set({ soundEnabled: value }),

  setFaultConfig: (cfg: FaultConfig) => {
    set({ faultConfig: cloneFaultConfig(cfg), simResult: null, missionDirty: true });
  },
  clearFaults: () => {
    set({ faultConfig: cloneFaultConfig(defaultFaultConfig), simResult: null, missionDirty: true });
  },

  setSceneRoomMode: (mode: AppState["sceneRoomMode"]) => {
    set({ sceneRoomMode: mode });
  },

  setSceneCameraPreset: (preset: AppState["sceneCameraPreset"]) => {
    set({ sceneCameraPreset: preset });
  },

  runMonteCarlo: async (config?: Partial<MonteCarloConfig>) => {
    const preset = get().currentPreset;
    if (!preset || get().monteCarloRunning) return;

    const nextConfig = {
      ...get().monteCarloConfig,
      ...config,
    };
    set({
      monteCarloConfig: nextConfig,
      monteCarloRuns: [],
      monteCarloResult: null,
      monteCarloRunning: true,
      monteCarloError: null,
      monteCarloProgress: 0,
    });

    await new Promise<void>((resolve) => {
      let finished = false;
      let socket: WebSocket | null = null;

      const complete = (updates: Partial<AppState>) => {
        if (finished) return;
        finished = true;
        set({ monteCarloRunning: false, ...updates });
        resolve();
      };

      try {
        socket = new WebSocket(monteCarloWsUrl());
      } catch (err) {
        complete({ monteCarloError: err instanceof Error ? err.message : String(err) });
        return;
      }

      socket.onopen = () => {
        const sim = buildSimRequest(
          preset,
          get().acceptRadius,
          get().initialPosition,
          get().droneDynamics,
          get().antiAirConfig,
          get().defensiveEvasionConfig,
          get().friendlyDrones,
          get().faultConfig,
          get().enableReplanning,
        );
        socket?.send(JSON.stringify({ sim, config: nextConfig }));
      };

      socket.onmessage = (event) => {
        const message = JSON.parse(event.data) as MonteCarloMessage;
        if (message.type === "started") {
          set({ monteCarloProgress: 0 });
          return;
        }
        if (message.type === "run") {
          set({
            monteCarloRuns: [...get().monteCarloRuns, message],
            monteCarloProgress: message.index / Math.max(1, message.total),
          });
          return;
        }
        if (message.type === "complete") {
          const { type: _type, ...result } = message;
          complete({
            monteCarloResult: result,
            monteCarloProgress: 1,
          });
          socket?.close();
          return;
        }
        if (message.type === "error") {
          complete({ monteCarloError: message.message });
          socket?.close();
        }
      };

      socket.onerror = () => {
        complete({ monteCarloError: "Monte Carlo WebSocket connection failed." });
      };

      socket.onclose = () => {
        if (!finished) {
          complete({ monteCarloError: "Monte Carlo stream closed before completion." });
        }
      };
    });
  },

  clearMonteCarlo: () => {
    set({
      monteCarloRuns: [],
      monteCarloResult: null,
      monteCarloError: null,
      monteCarloProgress: 0,
    });
  },
}));
