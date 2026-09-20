export interface Device {
  sn: string;
  role: string;
  model: string;
  online: boolean;
  gateway_sn?: string | null;
  updated_at_ms?: number;
}

export interface PositionState {
  code: number | null;
  convergence: "NOT_STARTED" | "CONVERGING" | "CONVERGED" | "FAILED" | "UNKNOWN";
  quality: number | null;
  gps_satellites: number | null;
  rtk_satellites: number | null;
}

export interface BatteryState {
  capacity_percent?: number;
  remain_flight_time_s?: number;
}

export interface Telemetry {
  source_sn: string;
  gateway_sn?: string | null;
  last_seen_ms: number;
  source_timestamp_ms: number;
  latitude?: number;
  longitude?: number;
  relative_altitude_m?: number;
  ellipsoid_height_m?: number;
  horizontal_speed_mps?: number;
  vertical_speed_mps?: number;
  mode_code?: number;
  position_state?: PositionState;
  battery?: BatteryState;
  attitude?: {
    yaw_deg?: number;
    roll_deg?: number;
    pitch_deg?: number;
  };
}

export interface TelemetryEvent {
  type: "telemetry";
  device_sn: string;
  timestamp: number;
  state: Telemetry;
}
