import type { Vehicle } from "./types";

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

export function liveWebSocketUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws/live`;
}
