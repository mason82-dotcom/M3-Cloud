import type {
  FlightDetail,
  FlightReplay,
  FlightSummary,
  MediaAsset,
  MediaDataset,
  MediaDatasetManifest,
  MediaGroup,
  MediaImportStatus,
  ProcessingJob,
  ProcessingMapInfo,
  ProcessingProfile,
  ProcessingSceneInfo,
  ProcessingResult,
  SystemHealth,
  Vehicle,
} from "./types";

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
