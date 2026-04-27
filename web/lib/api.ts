import axios from "axios";
import type {
  MonteCarloConfig,
  PresetSummary,
  PresetDetail,
  SimRequest,
  SimResponse,
} from "./types";

const baseURL = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

const client = axios.create({
  baseURL,
  timeout: 120_000,
});

export const defaultMonteCarloConfig: MonteCarloConfig = {
  n_runs: 30,
  seed_base: 42,
  wind_mean_jitter: 0.4,
  wind_extra_gust: 0.5,
  mass_jitter: 0.05,
  start_xy_jitter: 0.3,
  imu_bias_std_deg: 0.5,
  success_radius: 1,
  trajectory_stride: 35,
  survival_mode: true,
  missile_speed_jitter: 0.12,
  seeker_noise_jitter: 0.35,
  warning_delay_jitter: 0.2,
};

export function monteCarloWsUrl() {
  const url = new URL(baseURL);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/api/monte-carlo/ws";
  url.search = "";
  return url.toString();
}

export const api = {
  listPresets: async (): Promise<PresetSummary[]> => {
    const { data } = await client.get<PresetSummary[]>("/api/presets");
    return data;
  },
  getPreset: async (label: string): Promise<PresetDetail> => {
    const { data } = await client.get<PresetDetail>(
      `/api/presets/${encodeURIComponent(label)}`,
    );
    return data;
  },
  simulate: async (req: SimRequest): Promise<SimResponse> => {
    const { data } = await client.post<SimResponse>("/api/simulate", req);
    return data;
  },
};
