import { useCallback, useEffect, useMemo, useState } from "react";

import { fetchDevices, fetchTelemetry } from "./api";
import { FleetSidebar } from "./FleetSidebar";
import { useLiveEvents } from "./live";
import { MapView } from "./MapView";
import type { Device, LiveEvent, Telemetry } from "./types";

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

  const upsertDevice = useCallback((device: Device) => {
    setDevices((current) => {
      const index = current.findIndex((item) => item.sn === device.sn);
      if (index < 0) {
        return [...current, device];
      }

      const next = [...current];
      next[index] = {
        ...next[index],
        ...device,
      };
      return next;
    });
  }, []);

  const handleLiveEvent = useCallback(
    (event: LiveEvent) => {
      if (event.type === "telemetry") {
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
        return;
      }

      if (event.type === "device_online" || event.type === "device_offline") {
        upsertDevice(event.device);
        return;
      }

      if (event.type === "topology") {
        for (const device of event.devices) {
          upsertDevice(device);
        }
      }
    },
    [upsertDevice],
  );

  const handleConnection = useCallback((connected: boolean) => {
    setLiveConnected(connected);
  }, []);

  useLiveEvents(handleLiveEvent, handleConnection);

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
