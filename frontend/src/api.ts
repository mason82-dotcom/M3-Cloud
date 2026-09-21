import type {
  FlightDetail,
  ExternalResultStatus,
  FlightReplay,
  FlightSummary,
  MediaAsset,
  MediaDataset,
  MediaDatasetManifest,
  MediaGroup,
  MediaImportStatus,
  MediaPositionCollection,
  Mission,
  MissionDeployment,
  MissionGridPreview,
  MissionPlannerPoint,
  MissionPlannerProfile,
  MissionPlanningContext,
  MissionPlanItem,
  MissionPreflight,
  MissionRevision,
  ProcessingJob,
  ProcessingMapInfo,
  ProcessingProfile,
  ProcessingSceneInfo,
  ProcessingResult,
  Project,
  Survey,
  SurveyLineage,
  ThermogramHandoff,
  SystemHealth,
  Vehicle,
} from "./types";

export async function fetchProjects(): Promise<Project[]> {
  const response = await fetch("/api/v1/projects");
  if (!response.ok) {
    throw new Error(`Projects request failed: ${response.status}`);
  }
  return response.json() as Promise<Project[]>;
}

export async function createProject(input: {
  name: string;
  description?: string;
}): Promise<Project> {
  const response = await fetch("/api/v1/projects", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Project create failed: ${response.status}`);
  }
  return response.json() as Promise<Project>;
}

export async function fetchProjectSurveys(projectId: string): Promise<Survey[]> {
  const response = await fetch(
    `/api/v1/projects/${encodeURIComponent(projectId)}/surveys`,
  );
  if (!response.ok) {
    throw new Error(`Surveys request failed: ${response.status}`);
  }
  return response.json() as Promise<Survey[]>;
}

export async function createSurvey(
  projectId: string,
  input: {
    name: string;
    kind: string;
    description?: string;
  },
): Promise<Survey> {
  const response = await fetch(
    `/api/v1/projects/${encodeURIComponent(projectId)}/surveys`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Survey create failed: ${response.status}`);
  }
  return response.json() as Promise<Survey>;
}

export async function createSurveyFromDataset(
  projectId: string,
  datasetId: string,
  input: { name?: string; description?: string } = {},
): Promise<Survey> {
  const response = await fetch(
    `/api/v1/projects/${encodeURIComponent(projectId)}/surveys/from-dataset/${encodeURIComponent(datasetId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Survey from dataset failed: ${response.status}`);
  }
  return response.json() as Promise<Survey>;
}

export function surveyManifestDownloadUrl(surveyId: string): string {
  return `/api/v1/surveys/${encodeURIComponent(surveyId)}/manifest/download`;
}

export async function fetchSurveyLineage(
  surveyId: string,
): Promise<SurveyLineage> {
  const response = await fetch(
    `/api/v1/surveys/${encodeURIComponent(surveyId)}/lineage`,
  );
  if (!response.ok) {
    throw new Error(`Survey lineage request failed: ${response.status}`);
  }
  return response.json() as Promise<SurveyLineage>;
}

export async function assignFlightSurvey(
  flightId: string,
  surveyId: string | null,
): Promise<Record<string, unknown>> {
  const response = await fetch(
    `/api/v1/flights/${encodeURIComponent(flightId)}/survey`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ survey_id: surveyId }),
    },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Flight survey assignment failed: ${response.status}`);
  }
  return response.json() as Promise<Record<string, unknown>>;
}

export async function assignMediaDatasetSurvey(
  datasetId: string,
  surveyId: string | null,
): Promise<Record<string, unknown>> {
  const response = await fetch(
    `/api/v1/media/datasets/${encodeURIComponent(datasetId)}/survey`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ survey_id: surveyId }),
    },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Dataset survey assignment failed: ${response.status}`);
  }
  return response.json() as Promise<Record<string, unknown>>;
}

export async function fetchMissions(input: {
  surveyId?: string;
  aircraftSn?: string;
  includeArchived?: boolean;
} = {}): Promise<Mission[]> {
  const params = new URLSearchParams({ limit: "500" });
  if (input.surveyId) params.set("survey_id", input.surveyId);
  if (input.aircraftSn) params.set("aircraft_sn", input.aircraftSn);
  if (input.includeArchived) params.set("include_archived", "true");

  const response = await fetch(`/api/v1/missions?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Missions request failed: ${response.status}`);
  }
  return response.json() as Promise<Mission[]>;
}

export async function fetchMissionPlannerProfiles(): Promise<{
  schema_version: number;
  profiles: MissionPlannerProfile[];
  note: string;
}> {
  const response = await fetch("/api/v1/missions/planner/profiles");
  if (!response.ok) {
    throw new Error(`Mission planner profiles failed: ${response.status}`);
  }
  return response.json();
}

export async function previewMissionGrid(input: {
  platform: "M3E" | "M3T" | "M3M";
  capture_profile?: string | null;
  polygon: MissionPlannerPoint[];
  gsd_cm: number;
  forward_overlap_pct: number;
  side_overlap_pct: number;
  direction_deg: number;
  speed_mps: number;
  gimbal_pitch_deg?: number;
  overshoot_m?: number | null;
  finish_action?: "RTH" | "LAND" | "NONE";
  optimize_direction?: boolean;
  start_reference?: MissionPlannerPoint | null;
  home_reference?: MissionPlannerPoint | null;
}): Promise<MissionGridPreview> {
  const response = await fetch("/api/v1/missions/planner/grid-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Grid planner failed: ${response.status}`);
  }
  return response.json() as Promise<MissionGridPreview>;
}

export async function fetchMissionPreflight(
  missionId: string,
): Promise<MissionPreflight> {
  const response = await fetch(
    `/api/v1/missions/${encodeURIComponent(missionId)}/preflight`,
  );
  if (!response.ok) {
    throw new Error(`Mission preflight request failed: ${response.status}`);
  }
  return response.json() as Promise<MissionPreflight>;
}

export async function fetchMissionRevisions(
  missionId: string,
): Promise<MissionRevision[]> {
  const response = await fetch(
    `/api/v1/missions/${encodeURIComponent(missionId)}/revisions`,
  );
  if (!response.ok) {
    throw new Error(`Mission revisions request failed: ${response.status}`);
  }
  return response.json() as Promise<MissionRevision[]>;
}

export async function fetchMissionDeployments(
  missionId: string,
): Promise<MissionDeployment[]> {
  const response = await fetch(
    `/api/v1/missions/${encodeURIComponent(missionId)}/deployments`,
  );
  if (!response.ok) {
    throw new Error(`Mission deployments request failed: ${response.status}`);
  }
  return response.json() as Promise<MissionDeployment[]>;
}

export async function createMissionDeployment(
  missionId: string,
): Promise<MissionDeployment> {
  const response = await fetch(
    `/api/v1/missions/${encodeURIComponent(missionId)}/deployments`,
    { method: "POST" },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null) as {
      detail?: string | { message?: string };
    } | null;
    const detail =
      typeof body?.detail === "string"
        ? body.detail
        : body?.detail?.message;
    throw new Error(detail ?? `Mission handoff failed: ${response.status}`);
  }
  return response.json() as Promise<MissionDeployment>;
}

export async function uploadMissionDeployment(
  missionId: string,
  deploymentId: string,
): Promise<MissionDeployment> {
  const response = await fetch(
    `/api/v1/missions/${encodeURIComponent(missionId)}/deployments/${encodeURIComponent(deploymentId)}/upload`,
    { method: "POST" },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null) as {
      detail?: string | { message?: string };
    } | null;
    const detail =
      typeof body?.detail === "string"
        ? body.detail
        : body?.detail?.message;
    throw new Error(detail ?? `Mission upload failed: ${response.status}`);
  }
  return response.json() as Promise<MissionDeployment>;
}

export function missionDeploymentDownloadUrl(
  missionId: string,
  deploymentId: string,
): string {
  return `/api/v1/missions/${encodeURIComponent(missionId)}/deployments/${encodeURIComponent(deploymentId)}/download`;
}

export function missionRevisionDownloadUrl(
  missionId: string,
  version: number,
): string {
  return `/api/v1/missions/${encodeURIComponent(missionId)}/revisions/${version}/download`;
}

export async function createMission(input: {
  name: string;
  survey_id?: string | null;
  aircraft_sn?: string | null;
  preferred_executor?: "DJI_NATIVE" | "ONBOARD" | null;
  items?: MissionPlanItem[];
  planning?: MissionPlanningContext | null;
}): Promise<Mission> {
  const response = await fetch("/api/v1/missions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Mission create failed: ${response.status}`);
  }
  return response.json() as Promise<Mission>;
}

export async function updateMission(
  missionId: string,
  input: {
    name?: string;
    survey_id?: string | null;
    aircraft_sn?: string | null;
    preferred_executor?: "DJI_NATIVE" | "ONBOARD" | null;
    status?: "DRAFT" | "READY" | "ARCHIVED";
    items?: MissionPlanItem[];
    planning?: MissionPlanningContext | null;
  },
): Promise<Mission> {
  const response = await fetch(
    `/api/v1/missions/${encodeURIComponent(missionId)}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(input),
    },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Mission update failed: ${response.status}`);
  }
  return response.json() as Promise<Mission>;
}

export async function fetchVehicles(): Promise<Vehicle[]> {
  const response = await fetch("/api/v1/vehicles");
  if (!response.ok) {
    throw new Error(`Vehicle request failed: ${response.status}`);
  }
  const data: unknown = await response.json();
  if (Array.isArray(data)) return data as Vehicle[];
  if (data && typeof data === "object") {
    const envelope = data as { items?: Vehicle[]; vehicles?: Vehicle[] };
    return envelope.items ?? envelope.vehicles ?? [];
  }
  return [];
}

export async function fetchFlights(
  aircraftSn?: string,
  limit = 100,
): Promise<FlightSummary[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  if (aircraftSn) params.set("aircraft_sn", aircraftSn);

  const response = await fetch(`/api/v1/flights?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Flight request failed: ${response.status}`);
  }
  return response.json() as Promise<FlightSummary[]>;
}

export async function fetchFlightDetail(flightId: string): Promise<FlightDetail> {
  const response = await fetch(`/api/v1/flights/${encodeURIComponent(flightId)}`);
  if (!response.ok) {
    throw new Error(`Flight detail request failed: ${response.status}`);
  }
  return response.json() as Promise<FlightDetail>;
}

export async function fetchFlightSamples(
  flightId: string,
): Promise<FlightReplay> {
  const response = await fetch(
    `/api/v1/flights/${encodeURIComponent(flightId)}/samples?limit=10000`,
  );
  if (!response.ok) {
    throw new Error(`Flight samples request failed: ${response.status}`);
  }
  return response.json() as Promise<FlightReplay>;
}

export async function fetchMedia(
  platform?: string,
  mediaKind?: string,
): Promise<MediaAsset[]> {
  const params = new URLSearchParams({ limit: "5000" });
  if (platform) params.set("platform", platform);
  if (mediaKind) params.set("media_kind", mediaKind);

  const response = await fetch(`/api/v1/media?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Media request failed: ${response.status}`);
  }
  return response.json() as Promise<MediaAsset[]>;
}

export async function fetchMediaDatasets(
  platform?: string,
): Promise<MediaDataset[]> {
  const params = new URLSearchParams();
  if (platform) params.set("platform", platform);
  const suffix = params.toString() ? `?${params.toString()}` : "";

  const response = await fetch(`/api/v1/media/datasets${suffix}`);
  if (!response.ok) {
    throw new Error(`Media datasets request failed: ${response.status}`);
  }
  return response.json() as Promise<MediaDataset[]>;
}

export async function assignMediaDatasetFlight(
  datasetId: string,
  flightId: string | null,
): Promise<Record<string, unknown>> {
  const response = await fetch(
    `/api/v1/media/datasets/${encodeURIComponent(datasetId)}/flight`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ flight_id: flightId }),
    },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Dataset assignment failed: ${response.status}`);
  }
  return response.json() as Promise<Record<string, unknown>>;
}

export async function autoMatchMediaDatasetFlight(
  datasetId: string,
): Promise<Record<string, unknown>> {
  const response = await fetch(
    `/api/v1/media/datasets/${encodeURIComponent(datasetId)}/auto-match`,
    { method: "POST" },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Dataset auto-match failed: ${response.status}`);
  }
  return response.json() as Promise<Record<string, unknown>>;
}

export function mediaDatasetManifestDownloadUrl(prefix: string): string {
  const params = new URLSearchParams({ prefix });
  return `/api/v1/media/datasets/manifest/download?${params.toString()}`;
}

export async function fetchMediaDatasetManifest(
  prefix: string,
): Promise<MediaDatasetManifest> {
  const params = new URLSearchParams({ prefix });
  const response = await fetch(
    `/api/v1/media/datasets/manifest?${params.toString()}`,
  );
  if (!response.ok) {
    throw new Error(`Media dataset manifest failed: ${response.status}`);
  }
  return response.json() as Promise<MediaDatasetManifest>;
}

export async function fetchMediaPositions(
  platform?: string,
  mediaKind?: string,
  captureGroup?: string,
): Promise<MediaPositionCollection> {
  const params = new URLSearchParams({ limit: "50000" });
  if (platform) params.set("platform", platform);
  if (mediaKind) params.set("media_kind", mediaKind);
  if (captureGroup) params.set("capture_group", captureGroup);

  const response = await fetch(`/api/v1/media/positions?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Media positions request failed: ${response.status}`);
  }
  return response.json() as Promise<MediaPositionCollection>;
}

export async function fetchMediaGroups(
  platform?: string,
): Promise<MediaGroup[]> {
  const params = new URLSearchParams({ limit: "5000" });
  if (platform) params.set("platform", platform);

  const response = await fetch(`/api/v1/media/groups?${params.toString()}`);
  if (!response.ok) {
    throw new Error(`Media groups request failed: ${response.status}`);
  }
  return response.json() as Promise<MediaGroup[]>;
}

export async function fetchMediaImportStatus(): Promise<MediaImportStatus> {
  const response = await fetch("/api/v1/media/import/status");
  if (!response.ok) {
    throw new Error(`Media import status failed: ${response.status}`);
  }
  return response.json() as Promise<MediaImportStatus>;
}

export async function scanMediaImport(): Promise<Record<string, unknown>> {
  const response = await fetch("/api/v1/media/import/scan", { method: "POST" });
  if (!response.ok) {
    throw new Error(`Media import scan failed: ${response.status}`);
  }
  return response.json() as Promise<Record<string, unknown>>;
}

export async function fetchProcessingProfiles(): Promise<ProcessingProfile[]> {
  const response = await fetch("/api/v1/processing/profiles");
  if (!response.ok) {
    throw new Error(`Processing profile request failed: ${response.status}`);
  }
  return response.json() as Promise<ProcessingProfile[]>;
}

export async function fetchProcessingJobs(): Promise<ProcessingJob[]> {
  const response = await fetch("/api/v1/processing/jobs");
  if (!response.ok) {
    throw new Error(`Processing jobs request failed: ${response.status}`);
  }
  return response.json() as Promise<ProcessingJob[]>;
}

export async function createWebODMJob(input: {
  name: string;
  input_prefix: string;
  platform?: string;
  profile: string;
}): Promise<ProcessingJob> {
  const response = await fetch("/api/v1/processing/webodm", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `WebODM job request failed: ${response.status}`);
  }
  return response.json() as Promise<ProcessingJob>;
}

export async function createDroneDBJob(input: {
  name: string;
  input_prefix: string;
}): Promise<ProcessingJob> {
  const response = await fetch("/api/v1/processing/dronedb", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `DroneDB handoff request failed: ${response.status}`);
  }
  return response.json() as Promise<ProcessingJob>;
}

export function dronedbHandoffDownloadUrl(jobId: string): string {
  return `/api/v1/processing/jobs/${encodeURIComponent(jobId)}/dronedb-handoff/download`;
}

export async function createThermogramJob(input: {
  name: string;
  input_prefix: string;
}): Promise<ProcessingJob> {
  const response = await fetch("/api/v1/processing/thermogram", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Thermogram job request failed: ${response.status}`);
  }
  return response.json() as Promise<ProcessingJob>;
}

export async function fetchThermogramHandoff(
  jobId: string,
): Promise<ThermogramHandoff> {
  const response = await fetch(
    `/api/v1/processing/jobs/${encodeURIComponent(jobId)}/handoff`,
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `Thermogram handoff failed: ${response.status}`);
  }
  return response.json() as Promise<ThermogramHandoff>;
}

export function thermogramHandoffDownloadUrl(jobId: string): string {
  return `/api/v1/processing/jobs/${encodeURIComponent(jobId)}/handoff/download`;
}

export async function updateExternalProcessingJob(
  jobId: string,
  status: "RUNNING_EXTERNAL" | "COMPLETED_EXTERNAL" | "FAILED_EXTERNAL",
  error?: string,
): Promise<ProcessingJob> {
  const response = await fetch(
    `/api/v1/processing/jobs/${encodeURIComponent(jobId)}/external-status`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status, error }),
    },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `External job update failed: ${response.status}`);
  }
  return response.json() as Promise<ProcessingJob>;
}

export async function fetchExternalResultStatus(
  jobId: string,
): Promise<ExternalResultStatus> {
  const response = await fetch(
    `/api/v1/processing/jobs/${encodeURIComponent(jobId)}/external-results/status`,
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `External result status failed: ${response.status}`);
  }
  return response.json() as Promise<ExternalResultStatus>;
}

export async function importExternalResults(
  jobId: string,
): Promise<ProcessingResult[]> {
  const response = await fetch(
    `/api/v1/processing/jobs/${encodeURIComponent(jobId)}/external-results/import`,
    { method: "POST" },
  );
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `External result import failed: ${response.status}`);
  }
  return response.json() as Promise<ProcessingResult[]>;
}

export async function fetchProcessingResults(
  jobId: string,
): Promise<ProcessingResult[]> {
  const response = await fetch(
    `/api/v1/processing/jobs/${encodeURIComponent(jobId)}/results`,
  );
  if (!response.ok) {
    throw new Error(`Processing results request failed: ${response.status}`);
  }
  return response.json() as Promise<ProcessingResult[]>;
}

export async function fetchProcessingMaps(
  jobId: string,
): Promise<ProcessingMapInfo[]> {
  const response = await fetch(
    `/api/v1/processing/jobs/${encodeURIComponent(jobId)}/maps`,
  );
  if (!response.ok) {
    throw new Error(`Processing maps request failed: ${response.status}`);
  }
  return response.json() as Promise<ProcessingMapInfo[]>;
}

export async function fetchProcessingMap(
  jobId: string,
): Promise<ProcessingMapInfo | null> {
  const response = await fetch(
    `/api/v1/processing/jobs/${encodeURIComponent(jobId)}/map`,
  );
  if (response.status === 404) return null;
  if (!response.ok) {
    throw new Error(`Processing map request failed: ${response.status}`);
  }
  return response.json() as Promise<ProcessingMapInfo>;
}

export async function fetchProcessingScenes(
  jobId: string,
): Promise<ProcessingSceneInfo[]> {
  const response = await fetch(
    `/api/v1/processing/jobs/${encodeURIComponent(jobId)}/scenes`,
  );
  if (!response.ok) {
    throw new Error(`Processing scenes request failed: ${response.status}`);
  }
  return response.json() as Promise<ProcessingSceneInfo[]>;
}

export function processingResultDownloadUrl(
  jobId: string,
  resultId: string,
): string {
  return `/api/v1/processing/jobs/${encodeURIComponent(jobId)}/results/${encodeURIComponent(resultId)}/download`;
}

export async function fetchSystemHealth(): Promise<SystemHealth> {
  const response = await fetch("/api/v1/system/health");
  if (!response.ok) {
    throw new Error(`Health request failed: ${response.status}`);
  }
  return response.json() as Promise<SystemHealth>;
}

export function liveWebSocketUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws/live`;
}
