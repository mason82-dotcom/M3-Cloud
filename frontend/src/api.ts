import type {
  FlightDetail,
  FlightReplay,
  FlightSummary,
  MediaAsset,
  MediaGroup,
  MediaImportStatus,
  ProcessingJob,
  ProcessingProfile,
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
