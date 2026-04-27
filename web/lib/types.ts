// Shape mirrors backend/schemas.py — keep in sync if you add fields.

export type Vec3 = [number, number, number];

export interface ZonePayload {
  name: string;
  cx: number;
  cy: number;
  r: number;
  z_min: number;
  z_max: number;
  kind: "no_fly" | "threat";
}

export interface EnemyPayload {
  name: string;
  x: number;
  y: number;
  z: number;
  behavior: "patrol" | "loiter" | "pursue";
  speed: number;
  det_r: number;
  leth_r: number;
  orbit_cx: number;
  orbit_cy: number;
  orbit_r: number;
}

export interface FriendlyDronePayload {
  name: string;
  x: number;
  y: number;
  z: number;
  route_mode: "formation" | "same";
  enabled: boolean;
}

export interface PresetSummary {
  label: string;
  tag: string;
  description: string;
  duration_s: number;
  n_waypoints: number;
  n_zones: number;
  n_enemies: number;
  enable_threats: boolean;
  enable_geofence: boolean;
}

export interface PresetDetail extends PresetSummary {
  waypoints: Vec3[];
  yaws_deg: number[];
  zones: ZonePayload[];
  enemies: EnemyPayload[];
}

export interface SimRequest {
  waypoints: Vec3[];
  yaws_deg: number[];
  zones?: ZonePayload[];
  enemies?: EnemyPayload[];
  friendlies?: FriendlyDronePayload[];
  duration_s?: number;
  dt?: number;
  seed?: number;
  initial_position?: Vec3;
  mass?: number;
  accept_radius?: number;
  enable_threats?: boolean;
  react_threats?: boolean;
  enable_replanning?: boolean;
  enable_geofence?: boolean;
  gains?: Partial<ControllerGains>;
  anti_air?: AntiAirConfig;
  defensive_evasion?: DefensiveEvasionConfig;
  faults?: FaultConfig;
}

export interface ControllerGains {
  kp_xy: number;
  ki_xy: number;
  kd_xy: number;
  kp_z: number;
  ki_z: number;
  kd_z: number;
  kp_att: number;
  kd_att: number;
  kp_yaw: number;
  kd_yaw: number;
  max_tilt_deg: number;
  max_accel_xy: number;
  max_speed_xy: number;
}

export interface DroneDynamicsConfig {
  mass: number;
  maxSpeedXY: number;
  maxAccelXY: number;
  maxTiltDeg: number;
}

export interface InterceptorBatteryPayload {
  name: string;
  x: number;
  y: number;
  z: number;
  launch_range: number;
  min_engage_alt: number;
  cooldown: number;
  max_active: number;
  max_total_shots: number;
  initial_speed: number;
  nav_constant: number;
  max_lateral_accel: number;
  boost_time: number;
  boost_accel: number;
  coast_drag: number;
  lethal_radius: number;
  arming_time: number;
  max_time: number;
  seeker_enabled: boolean;
  seeker_range: number;
  seeker_fov_deg: number;
  seeker_noise_std_deg: number;
  seeker_memory_time: number;
}

export interface AntiAirConfig {
  enabled: boolean;
  batteries: InterceptorBatteryPayload[];
}

export interface DefensiveEvasionConfig {
  enabled: boolean;
  mode: "beam" | "corridor";
  detect_range: number;
  trigger_tgo: number;
  hold_time: number;
  escape_distance: number;
  altitude_delta: number;
  emergency_max_tilt_deg: number;
  emergency_max_accel_xy: number;
  emergency_max_speed_xy: number;
}

export interface DefensiveSummary {
  n_evasions?: number;
  time_evasive?: number;
  escaped?: boolean;
  mode?: string;
}

export interface InterceptorSummary {
  n_launches?: number;
  n_hits?: number;
  n_misses?: number;
  n_seeker_locks?: number;
  n_seeker_losses?: number;
  min_miss_distance?: number;
}

export interface FriendlyTrack {
  name: string;
  initial_position: Vec3;
  route_mode: "formation" | "same";
  pos: Vec3[];
  vel?: Vec3[];
  euler?: Vec3[];
  waypoints_reached?: number;
  interceptor_killed?: boolean;
  interceptor_summary?: InterceptorSummary;
}

export type InterceptorEvent =
  | {
      type: "launch";
      t: number;
      frame: number;
      battery: number;
      battery_name?: string;
      origin: Vec3;
      target: Vec3;
    }
  | {
      type: "hit" | "miss";
      t: number;
      frame: number;
      battery: number;
      miss_distance: number;
      time_of_flight: number;
      position: Vec3;
      reason?: string;
    }
  | {
      type: "seeker_lock" | "seeker_lost";
      t: number;
      frame: number;
      battery: number;
      range: number;
      fov_error_deg: number;
      position: Vec3;
      target?: Vec3;
    };

export interface MotorFault {
  rotor: 0 | 1 | 2 | 3;
  t_start: number;
  t_end: number;
  severity: number;        // 0 = total loss, 1 = nominal
}

export interface WindowFault {
  t_start: number;
  t_end: number;
}

export interface FaultConfig {
  motor: MotorFault[];
  imu:   WindowFault[];
  gps:   WindowFault[];
}

export interface SimResponse {
  t: number[];
  pos: Vec3[];
  euler: Vec3[];
  vel: Vec3[];
  waypoint_active: Vec3[];
  thrust: number[];
  meas_pos: Vec3[];
  motor_cmd:    number[][];   // (N, 4)
  motor_actual: number[][];   // (N, 4)
  imu_dropout:  boolean[];    // (N,)
  gps_denied:   boolean[];    // (N,)
  reroute_active: boolean[];   // (N,)
  reroute_events: RerouteEvent[];
  replanned_waypoints: Vec3[];
  state_est: number[][];      // (N, 6)
  enemy_hist: number[][][];   // (N, M, 4)
  waypoints_total: number;
  waypoints_reached: number;
  rms_position_error: number;
  final_position_error: number;
  estimator_used: boolean;
  raw_pos_rms: number;
  ekf_pos_rms: number;

  // 15-state INS/GPS EKF outputs (empty when not used).
  estimator_kind?: "none" | "position" | "ins_gps";
  pos_cov_diag?: Vec3[];           // (N, 3) per-axis position variance
  est_euler?: Vec3[];              // (N, 3) filter attitude (rad)
  accel_bias_est?: Vec3[];         // (N, 3)
  gyro_bias_est?: Vec3[];          // (N, 3)
  nees?: number[];                 // (N,) navigation NEES
  nis?: (number | null)[];         // (N,) sparse — null where no GPS update
  nees_chi2_lo?: number;
  nees_chi2_hi?: number;
  nis_chi2_lo?: number;
  nis_chi2_hi?: number;

  interceptor_hist?: number[][][];   // (N, slots, 11): x,y,z,vx,vy,vz,status,seeker,target xyz
  interceptor_events?: InterceptorEvent[];
  interceptor_summary?: InterceptorSummary;
  interceptor_batteries?: InterceptorBatteryPayload[];
  interceptor_killed?: boolean;
  interceptor_kill_frame?: number;
  defensive_hist?: number[][];      // (N, 8): active,x,y,z,range,tgo,missile_x,missile_y
  defensive_events?: DefensiveEvent[];
  defensive_summary?: DefensiveSummary;
  friendly_tracks?: FriendlyTrack[];
}

export interface DefensiveEvent {
  type: "missile_evasion";
  t: number;
  frame: number;
  mode: "beam" | "corridor";
  message: string;
  threat_slot: number;
  missile_range: number;
  closing_speed: number;
  time_to_go: number;
  escape_target: Vec3;
  missile_position: Vec3;
}

export interface RerouteEvent {
  t: number;
  frame: number;
  threat_name: string;
  threat_kind: string;
  waypoint_index: number;
  original_target: Vec3;
  inserted_waypoint: Vec3;
  inserted_waypoints?: Vec3[];
  envelope_radius: number;
  clearance_score: number;
  planner_cost?: number;
  nodes_expanded?: number;
  cost_grid?: PlannerCostCell[];
  message: string;
}

export type PlannerCostCell = [
  x: number,
  y: number,
  cost: number,
  blocked: number,
  size: number,
];

export interface MonteCarloConfig {
  n_runs: number;
  seed_base: number;
  wind_mean_jitter: number;
  wind_extra_gust: number;
  mass_jitter: number;
  start_xy_jitter: number;
  imu_bias_std_deg: number;
  success_radius: number;
  trajectory_stride: number;
  survival_mode: boolean;
  missile_speed_jitter: number;
  seeker_noise_jitter: number;
  warning_delay_jitter: number;
}

export interface MonteCarloRun {
  index: number;
  total: number;
  trajectory: Vec3[];
  endpoint: Vec3;
  final_error: number;
  rms_error: number;
  waypoints_reached: number;
  mission_time: number;
  success: boolean;
  sam_launched?: boolean;
  sam_killed?: boolean;
  survived_sam?: boolean;
  min_miss_distance?: number | null;
  n_evasions?: number;
  n_seeker_locks?: number;
}

export interface MonteCarloResult {
  total: number;
  success_rate: number;
  success_count: number;
  final_error_mean: number;
  final_error_std: number;
  rms_error_mean: number;
  mission_time_mean: number;
  endpoints: Vec3[];
  final_errors: number[];
  rms_errors: number[];
  success_mask: boolean[];
  waypoints_reached: number[];
  mission_times: number[];
  waypoints: Vec3[];
  cep50_per_wp: number[];
  cep95_per_wp: number[];
  survival_rate?: number;
  sam_kill_rate?: number;
  sam_engagement_count?: number;
  mean_min_miss_distance?: number;
  min_miss_distances?: Array<number | null>;
  evasion_rate?: number;
  seeker_lock_mean?: number;
}

export type MonteCarloMessage =
  | { type: "started"; total: number; config: MonteCarloConfig }
  | ({ type: "run" } & MonteCarloRun)
  | ({ type: "complete" } & MonteCarloResult)
  | { type: "error"; message: string };
