import type { Device, Telemetry } from "./types";

export async function fetchDevices(): Promise<Device[]> {
  const response = await fetch("/api/v1/devices");
  if (!response.ok) {
    throw new Error(`Device request failed: ${response.status}`);
  }
  return response.json() as Promise<Device[]>;
}

export async function fetchTelemetry(sn: string): Promise<Telemetry | null> {
  const response = await fetch(`/api/v1/devices/${encodeURIComponent(sn)}/telemetry`);
  if (response.status === 404) {
    return null;
  }
  if (!response.ok) {
    throw new Error(`Telemetry request failed for ${sn}: ${response.status}`);
  }
  return response.json() as Promise<Telemetry>;
}

export function liveWebSocketUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws/live`;
}
