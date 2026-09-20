import { useCallback, useEffect, useMemo, useState } from "react";

import { fetchDevices, fetchTelemetry } from "./api";
import { FleetSidebar } from "./FleetSidebar";
import { useLiveTelemetry } from "./live";
import { MapView } from "./MapView";
import type { Device, Telemetry, TelemetryEvent } from "./types";

export default function App() {
  const [devices, setDevices] = useState<Device[]>([]);
  const [telemetry, setTelemetry] = useState<Record<string, Telemetry>>({});
  const [selectedSn, setSelectedSn] = useState<string | null>(null);
  const [liveConnected, setLiveConnected] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const loadedDevices = await fetchDevices();
        const states = await Promise.all(
          loadedDevices.map(async (device) => [
            device.sn,
            await fetchTelemetry(device.sn),
          ] as const),
        );

        if (cancelled) {
          return;
        }

        setDevices(loadedDevices);
        setTelemetry(
          Object.fromEntries(
            states.filter(
              (entry): entry is readonly [string, Telemetry] =>
                entry[1] !== null,
            ),
          ),
        );

        const firstAircraft =
          loadedDevices.find((device) => device.role === "aircraft") ??
          loadedDevices[0];
        setSelectedSn((current) => current ?? firstAircraft?.sn ?? null);
      } catch (error) {
        if (!cancelled) {
          setLoadError(error instanceof Error ? error.message : String(error));
        }
      }
    };

    void load();

    return () => {
      cancelled = true;
    };
  }, []);

  const handleTelemetry = useCallback((event: TelemetryEvent) => {
    setTelemetry((current) => ({
      ...current,
      [event.device_sn]: event.state,
    }));

    setDevices((current) =>
      current.map((device) =>
        device.sn === event.device_sn
          ? { ...device, online: true }
          : device,
      ),
    );
  }, []);

  const handleConnection = useCallback((connected: boolean) => {
    setLiveConnected(connected);
  }, []);

  useLiveTelemetry(handleTelemetry, handleConnection);

  const aircraft = useMemo(
    () => devices.filter((device) => device.role === "aircraft"),
    [devices],
  );

  return (
    <main className="app-shell">
      <FleetSidebar
        devices={aircraft}
        telemetry={telemetry}
        selectedSn={selectedSn}
        liveConnected={liveConnected}
        onSelect={setSelectedSn}
      />

      <section className="map-shell">
        {loadError ? <div className="error-banner">{loadError}</div> : null}
        <MapView
          devices={aircraft}
          telemetry={telemetry}
          selectedSn={selectedSn}
        />
      </section>
    </main>
  );
}
