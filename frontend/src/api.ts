import type { Device, Telemetry, Vehicle } from "./types";

export async function fetchVehicles(): Promise<Vehicle[]> {\n  const response = await fetch("/api/v1/vehicles");\n  if (!response.ok) throw new Error(`Vehicle request failed: ${response.status}`);\n  const data = await response.json();\n  return Array.isArray(data) ? data : (data.items ?? data.vehicles ?? []);\n}\n\nexport function liveWebSocketUrl(): string {
  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  return `${scheme}://${window.location.host}/ws/live`;
}
