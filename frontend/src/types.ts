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
  media_datasets?: Array<{
    id: string;
    platform: string;
    prefix: string;
    title?: string | null;
    present: boolean;
  }>;
  processing_jobs?: Array<{
    id: string;
    kind: string;
    status: string;
    name: string;
    platform?: string | null;
    input_prefix: string;
  }>;
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

export interface MediaAsset {
  id: string;
  relative_path: string;
  filename: string;
  extension: string;
  size_bytes: number;
  mtime_ns: number;
  sha256: string;
  platform: string;
  media_kind: string;
  capture_group?: string | null;
  storage_mode: string;
  external_root: string;
  present: boolean;
  duplicate_of?: string | null;
  discovered_at: string;
  last_seen_at: string;
}

export interface MediaGroup {
  capture_group: string;
  platform: string;
  asset_count: number;
  size_bytes: number;
}

export interface MediaWorkflowReadiness {
  key: "WEBODM" | "THERMOGRAM" | "MULTISPECTRAL" | string;
  ready: boolean;
  eligible_assets: number;
  complete_groups: number;
  incomplete_groups: number;
  reason: string;
}

export interface MediaDataset {
  id?: string | null;
  prefix: string;
  platform: string;
  flight_id?: string | null;
  flight_aircraft_sn?: string | null;
  flight_started_at?: string | null;
  asset_count: number;
  size_bytes: number;
  media_kinds: Record<string, number>;
  capture_group_count: number;
  workflows: MediaWorkflowReadiness[];
}

export interface MediaDatasetManifestFile {
  id: string;
  relative_path: string;
  filename: string;
  media_kind: string;
  size_bytes: number;
  sha256: string;
}

export interface MediaDatasetManifestGroup {
  capture_group: string;
  complete: boolean;
  required_kinds: string[];
  media_kinds: string[];
  files: MediaDatasetManifestFile[];
}

export interface MediaDatasetManifest {
  schema_version: number;
  prefix: string;
  platform: string;
  external_path: string;
  asset_count: number;
  size_bytes: number;
  media_kinds: Record<string, number>;
  workflows: MediaWorkflowReadiness[];
  capture_groups: MediaDatasetManifestGroup[];
  ungrouped_files: MediaDatasetManifestFile[];
}

export interface MediaImportStatus {
  enabled: boolean;
  status: string;
  root?: string;
  exists?: boolean;
  readable?: boolean;
  min_age_seconds?: number;
  scan_running?: boolean;
  last_error?: string | null;
  last_scan?: {
    scanned: number;
    added: number;
    updated: number;
    unchanged: number;
    duplicates: number;
    skipped_unstable: number;
    marked_missing: number;
    started_at: string;
    finished_at: string;
  } | null;
}

export interface ProcessingProfile {
  key: string;
  title: string;
  purpose: string;
  options: Array<{ name: string; value: unknown }>;
  platforms: string[];
  media_kinds: string[];
  workflow: string;
}

export interface ProcessingJob {
  id: string;
  kind: string;
  status: string;
  name: string;
  input_prefix: string;
  platform?: string | null;
  flight_id?: string | null;
  media_kinds: string[];
  options: Array<{ name: string; value: unknown }>;
  image_count: number;
  uploaded_count: number;
  progress: number;
  remote_project_id?: number | null;
  remote_task_id?: number | null;
  remote_status?: number | null;
  available_assets: string[];
  error?: string | null;
  created_at: string;
  started_at?: string | null;
  updated_at: string;
  finished_at?: string | null;
}

export interface ThermogramHandoffFile {
  id: string;
  relative_path: string;
  filename: string;
  media_kind: "WIDE" | "THERMAL" | string;
  size_bytes: number;
  sha256: string;
}

export interface ThermogramHandoffGroup {
  capture_group: string;
  files: ThermogramHandoffFile[];
}

export interface ThermogramHandoff {
  schema_version: number;
  workflow: "THERMOGRAM";
  platform: "M3T";
  job_id: string;
  flight_id?: string | null;
  input_prefix: string;
  external_path: string;
  required_media_kinds: string[];
  capture_group_count: number;
  asset_count: number;
  capture_groups: ThermogramHandoffGroup[];
}

export interface ExternalResultStatus {
  job_id: string;
  drop_path: string;
  mounted: boolean;
  job_folder_exists: boolean;
  file_count: number;
  files: string[];
}

export interface ProcessingResult {
  id: string;
  job_id: string;
  asset_name: string;
  bucket: string;
  object_key: string;
  size_bytes: number;
  sha256: string;
  content_type: string;
  details?: Record<string, unknown>;
  created_at: string;
}

export interface ProcessingSceneInfo {
  job_id: string;
  result_id: string;
  asset_name: string;
  scene_type?: string | null;
  tileset_url: string;
  bounds?: [number, number, number, number] | null;
  file_count?: number | null;
  published_bytes?: number | null;
  asset_version?: string | null;
}

export interface ProcessingMapInfo {
  job_id: string;
  result_id: string;
  kind: "RASTER_XYZ";
  layer_type?: string | null;
  tile_url: string;
  bounds?: [number, number, number, number] | null;
  minzoom?: number | null;
  maxzoom?: number | null;
  tile_count?: number | null;
  attribution?: string | null;
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
