import { useCallback, useEffect, useMemo, useState } from "react";

import { fetchVehicles } from "./api";
import { FleetSidebar } from "./FleetSidebar";
import { useLiveEvents } from "./live";
import { MapView } from "./MapView";
import type { LiveEvent, Telemetry, Vehicle } from "./types";

export default function App() {
  const [devices, setDevices] = useState<Vehicle[]>([]);
  const [telemetry, setTelemetry] = useState<Record<string, Telemetry>>({});
  const [selectedSn, setSelectedSn] = useState<string | null>(null);
  const [liveConnected, setLiveConnected] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    const load = async () => {
      try {
        const loadedDevices = await fetchVehicles();
        if (cancelled) return;
        setDevices(loadedDevices);
        setTelemetry(Object.fromEntries(loadedDevices.filter((v) => v.telemetry).map((v) => [v.sn, v.telemetry as Telemetry])));
        setSelectedSn((current) => current ?? loadedDevices[0]?.sn ?? null);
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

  const upsertDevice = useCallback((device: Vehicle) => {
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

      if (event.type === "vehicle_telemetry") {
        upsertDevice(event.vehicle);
        if (event.vehicle.telemetry) {
          setTelemetry((current) => ({
            ...current,
            [event.vehicle.sn]: event.vehicle.telemetry as Telemetry,
          }));
        }
        return;
      }

      if (event.type === "device_online" || event.type === "device_offline") {
        setDevices((current) =>
          current.map((vehicle) =>
            vehicle.sn === event.device_sn
              ? { ...vehicle, online: event.type === "device_online" }
              : vehicle,
          ),
        );
        return;
      }

      // Topology is a reconciliation hint. The canonical vehicle list is /api/v1/vehicles;
      // do not inject DJI registry Device records into the cross-source Vehicle model here.
      if (event.type === "topology") {
        void fetchVehicles().then((vehicles) => {
          setDevices(vehicles);
          setTelemetry(Object.fromEntries(vehicles.filter((v) => v.telemetry).map((v) => [v.sn, v.telemetry as Telemetry])));
        });
      }
    },
    [upsertDevice],
  );

  const handleConnection = useCallback((connected: boolean) => {
    setLiveConnected(connected);
  }, []);

  useLiveEvents(handleLiveEvent, handleConnection);

  const aircraft = useMemo(() => devices, [devices]);

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
