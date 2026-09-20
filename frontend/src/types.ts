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
  rtk_fixed?: boolean | null;
  convergence?: string | null;
  quality?: number | null;
  rtk?: RtkState;
}

export interface AircraftState {
  source?: string;
  mode?: string | null;
  armed?: boolean | null;
  is_flying?: boolean | null;
  failsafe?: boolean | null;
  landed_state?: number | null;
  home?: {
    latitude?: number | null;
    longitude?: number | null;
    distance_m?: number | null;
  };
  positioning?: AircraftPositioning;
}

export interface PayloadState {
  platform?: string;
  rgb?: boolean;
  wide?: boolean;
  zoom?: boolean;
  thermal?: boolean;
  multispectral?: boolean;
  lrf?: boolean;
  capture_profiles?: string[];
  camera?: {
    camera_type?: string | null;
    firmware_version?: string | null;
    camera_mode?: string | number | null;
    live_view_source?: string | null;
    capture_stored_sources?: string[];
    [key: string]: unknown;
  };
}

export interface BatteryState {
  capacity_percent?: number | null;
  remain_flight_time_s?: number | null;
}

export interface Telemetry {
  aircraft_state?: AircraftState;
  source_sn?: string;
  gateway_sn?: string | null;
  source_timestamp_ms?: number;
  last_seen_ms?: number;
  source?: string;
  latitude?: number | null;
  longitude?: number | null;
  relative_altitude_m?: number | null;
  ellipsoid_height_m?: number | null;
  amsl_altitude_m?: number | null;
  horizontal_speed_mps?: number | null;
  vertical_speed_mps?: number | null;
  velocity_down_mps?: number | null;
  heading_deg?: number | null;
  mode_code?: number | null;
  gps_satellites?: number | null;
  position_state?: {
    code?: number | null;
    convergence?: string | null;
    quality?: number | null;
    gps_satellites?: number | null;
    rtk_satellites?: number | null;
  };
  battery?: BatteryState;
  attitude?: {
    yaw_deg?: number | null;
    roll_deg?: number | null;
    pitch_deg?: number | null;
  };
  gimbal?: Record<string, unknown>;
  controller?: Record<string, unknown>;
  safety?: Record<string, unknown>;
  payload?: PayloadState;
  lrf?: Record<string, unknown>;
  rtk?: RtkState;
  home_set?: boolean | null;
  [key: string]: unknown;
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

export interface FlightSummary {
  id: string;
  aircraft_sn: string;
  gateway_sn?: string | null;
  dji_track_id?: string | null;
  status: string;
  started_at: string;
  ended_at?: string | null;
  duration_s?: number | null;
  distance_m: number;
  max_relative_altitude_m?: number | null;
  max_horizontal_speed_mps?: number | null;
  min_battery_percent?: number | null;
  rtk_converged_percent?: number | null;
  end_reason?: string | null;
}

export interface FlightDetail extends FlightSummary {
  sources?: string[];
  takeoff_position?: import("geojson").Point | null;
  landing_position?: import("geojson").Point | null;
  path?: import("geojson").LineString | null;
}

export interface FlightSample {
  id: number;
  recorded_at: string;
  source_timestamp_ms: number;
  source: string;
  longitude?: number | null;
  latitude?: number | null;
  position_z_m?: number | null;
  relative_altitude_m?: number | null;
  ellipsoid_height_m?: number | null;
  horizontal_speed_mps?: number | null;
  vertical_speed_mps?: number | null;
  heading_deg?: number | null;
  mode_code?: number | null;
  battery_percent?: number | null;
  position_convergence?: string | null;
  gps_satellites?: number | null;
  rtk_satellites?: number | null;
}

export interface FlightReplay {
  flight_id: string;
  total: number;
  count: number;
  offset: number;
  truncated: boolean;
  samples: FlightSample[];
}

export interface ComponentHealth {
  ok?: boolean;
  status?: string;
  [key: string]: unknown;
}

export interface SystemHealth {
  ok: boolean;
  components: Record<string, ComponentHealth | string | boolean | null>;
}

export type LiveEvent =
  | TelemetryEvent
  | VehicleTelemetryEvent
  | DeviceStatusEvent
  | TopologyEvent;
