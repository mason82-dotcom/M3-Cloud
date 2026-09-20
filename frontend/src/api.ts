import type {
  FlightDetail,
  FlightReplay,
  FlightSummary,
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
