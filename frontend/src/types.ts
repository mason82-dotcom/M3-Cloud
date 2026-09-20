export interface RtkState {
  enabled?: boolean | null;
  connected?: boolean | null;
  healthy?: boolean | null;
  fix?: string | null;
  raw_fix?: string | null;
  age_ms?: number | null;
  source?: string | null;
  satellites?: number | null;
  convergence?: string | null;
  quality?: number | null;
}

export interface AircraftPositioning {
  fix?: string | null;
  position_source?: string | null;
  gps_satellites?: number | null;
  rtk_satellites?: number | null;
  rtk_stale?: boolean;
  rtk?: RtkState;
}

export interface AircraftState {
  source?: string;
  mode?: string | null;
  armed?: boolean | null;
  is_flying?: boolean | null;
  failsafe?: boolean | null;
  positioning?: AircraftPositioning;
}

export interface Vehicle {
  id: string;
  sn: string;
  name: string;
  model: string;
  source: string;
  sources?: string[];
  online: boolean;
  gateway_sn?: string | null;
  updated_at_ms?: number | null;
  telemetry?: Telemetry | null;
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
  aircraft_state?: AircraftState;
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


export interface VehicleTelemetryEvent {
  type: "vehicle_telemetry";
  vehicle_id: string;
  device_sn?: string;
  source?: string;
  vehicle: Vehicle;
}

export interface DeviceStatusEvent {
  type: "device_online" | "device_offline";
  timestamp?: number;
  device_sn: string;
  device?: {
    sn: string;
    model?: string;
    online?: boolean;
    gateway_sn?: string | null;
    updated_at_ms?: number | null;
  };
}

export interface TopologyEvent {
  type: "topology";
  timestamp?: number;
  gateway_sn?: string;
  devices?: unknown[];
}

export type LiveEvent = TelemetryEvent | VehicleTelemetryEvent | DeviceStatusEvent | TopologyEvent;
