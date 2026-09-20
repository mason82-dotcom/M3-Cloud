import { useCallback, useEffect, useMemo, useState } from "react";

import { fetchSystemHealth, fetchVehicles } from "./api";
import { FlightHistoryView } from "./FlightHistory";
import { useLiveEvents } from "./live";
import { MapView } from "./MapView";
import { MediaView } from "./MediaView";
import { ProcessingView } from "./ProcessingView";
import { ProjectsView } from "./ProjectsView";
import type {
  ComponentHealth,
  LiveEvent,
  SystemHealth,
  Telemetry,
  Vehicle,
} from "./types";

type ViewName =
  | "operations"
  | "projects"
  | "fleet"
  | "missions"
  | "live"
  | "flights"
  | "media"
  | "processing"
  | "system";

const NAV: Array<[ViewName, string, string]> = [
  ["operations", "Operations", "Fleet, RTK und Missionen im Überblick"],
  ["projects", "Projects", "Projects und Surveys mit Flight-, Media- und Processing-Lineage."],
  ["fleet", "Fleet", "Aircraft, Payloads, RTK und Verbindungsstatus."],
  ["missions", "Missions", "Waylines, Missionsplanung, Preflight und Ausführungsstatus."],
  ["live", "Live", "Aircraft, RTK, Controller, Gimbal und Payload in Echtzeit"],
  ["flights", "Flights", "Historische Flüge, PostGIS-Tracks und Flugstatistiken."],
  ["media", "Media", "Fotos, Videos, Thermal- und Multispektraldaten."],
  ["processing", "Processing", "Photogrammetrie, Thermogram und weitere Processing-Pipelines."],
  ["system", "System", "EMQX, PostgreSQL, MinIO, Backend und Integrationen."],
];

function mergeObjects(
  base: Record<string, unknown> | null | undefined,
  patch: Record<string, unknown> | null | undefined,
): Record<string, unknown> {
  const result: Record<string, unknown> = { ...(base ?? {}) };
  for (const [key, value] of Object.entries(patch ?? {})) {
    if (value === null || value === undefined) continue;
    const current = result[key];
    if (
      typeof current === "object" &&
      current !== null &&
      !Array.isArray(current) &&
      typeof value === "object" &&
      !Array.isArray(value)
    ) {
      result[key] = mergeObjects(
        current as Record<string, unknown>,
        value as Record<string, unknown>,
      );
    } else {
      result[key] = value;
    }
  }
  return result;
}

function mergeTelemetry(
  base: Telemetry | null | undefined,
  patch: Telemetry | null | undefined,
): Telemetry | null | undefined {
  if (!base) return patch;
  if (!patch) return base;
  return mergeObjects(base, patch) as Telemetry;
}

function mergeVehicle(current: Vehicle, incoming: Vehicle): Vehicle {
  return {
    ...current,
    ...incoming,
    sources: Array.from(
      new Set([
        ...(current.sources ?? [current.source]),
        ...(incoming.sources ?? [incoming.source]),
      ]),
    ),
    telemetry: mergeTelemetry(current.telemetry, incoming.telemetry),
  };
}

function sourceLabel(vehicle: Vehicle): string {
  return (vehicle.sources ?? [vehicle.source]).filter(Boolean).join(" + ");
}

function numberValue(value: unknown, digits = 1): string {
  return typeof value === "number" && Number.isFinite(value)
    ? value.toFixed(digits)
    : "—";
}

function textValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "yes" : "no";
  return String(value);
}

function positionStatus(vehicle: Vehicle): {
  label: string;
  className: string;
  usable: boolean;
} {
  const positioning = vehicle.telemetry?.aircraft_state?.positioning;
  const rtk = positioning?.rtk ?? vehicle.telemetry?.rtk;
  const fix = String(positioning?.fix ?? rtk?.fix ?? "UNKNOWN").toUpperCase();
  const stale = positioning?.rtk_stale === true || fix === "STALE";

  if (stale) return { label: "STALE", className: "warn", usable: false };
  if (fix === "FIXED") {
    return {
      label: "FIXED",
      className: rtk?.healthy === false ? "warn" : "fix",
      usable: rtk?.healthy !== false,
    };
  }
  if (fix === "FLOAT") {
    return {
      label: "FLOAT",
      className: rtk?.healthy === false ? "warn" : "float",
      usable: rtk?.healthy !== false,
    };
  }
  if (fix === "SINGLE") return { label: "SINGLE", className: "single", usable: false };
  return {
    label: fix === "NONE" ? "NONE" : "UNKNOWN",
    className: "",
    usable: false,
  };
}

function HealthValue({
  label,
  value,
}: {
  label: string;
  value: ComponentHealth | string | boolean | null | undefined;
}) {
  let text = "waiting";
  let ok = false;

  if (typeof value === "object" && value !== null) {
    text = value.status ?? (value.ok ? "online" : "unavailable");
    ok = value.ok === true || value.status === "enabled" || value.status === "ONLINE";
  } else if (value !== undefined && value !== null) {
    text = String(value);
    ok = Boolean(value);
  }

  return (
    <span>
      {label}
      <b className={ok ? "health-good" : ""}>{text}</b>
    </span>
  );
}

function PayloadPanel({ vehicle }: { vehicle: Vehicle | null }) {
  if (!vehicle) {
    return (
      <section className="panel payloadPanel">
        <div className="panelHead">
          <div>
            <h2>Payload</h2>
            <small>Aircraft auswählen</small>
          </div>
          <span>UNKNOWN</span>
        </div>
        <div className="empty">
          Ein Aircraft in der Fleet auswählen, um Payload-Daten anzuzeigen.
        </div>
      </section>
    );
  }

  const payload = vehicle.telemetry?.payload;
  const camera = payload?.camera;
  const platform = payload?.platform ?? vehicle.model ?? "UNKNOWN";

  return (
    <section className="panel payloadPanel">
      <div className="panelHead">
        <div>
          <h2>Payload</h2>
          <small>{vehicle.name} · {sourceLabel(vehicle)}</small>
        </div>
        <span>{platform}</span>
      </div>
      <div className="payloadBody">
        <article className="payloadCard">
          <h3>Camera identity</h3>
          <dl>
            <dt>Platform</dt><dd>{platform}</dd>
            <dt>MSDK CameraType</dt><dd>{textValue(camera?.camera_type)}</dd>
            <dt>Firmware</dt><dd>{textValue(camera?.firmware_version)}</dd>
            <dt>Mode</dt><dd>{textValue(camera?.camera_mode)}</dd>
            <dt>Live source</dt><dd>{textValue(camera?.live_view_source)}</dd>
          </dl>
        </article>

        <article className={`payloadCard accent-${String(platform).toLowerCase()}`}>
          <h3>{platform} capabilities</h3>
          <div className="chips">
            {payload?.rgb ? <span>RGB</span> : null}
            {payload?.wide ? <span>Wide</span> : null}
            {payload?.zoom ? <span>Zoom</span> : null}
            {payload?.thermal ? <span>Thermal</span> : null}
            {payload?.multispectral ? <span>Multispectral</span> : null}
            {payload?.lrf ? <span>LRF</span> : null}
          </div>
          <dl>
            <dt>Profiles</dt>
            <dd>{payload?.capture_profiles?.join(", ") || "—"}</dd>
            <dt>Stored sources</dt>
            <dd>{camera?.capture_stored_sources?.join(", ") || "—"}</dd>
          </dl>
        </article>
      </div>
    </section>
  );
}

function LiveView({ vehicle }: { vehicle: Vehicle | null }) {
  if (!vehicle) return <div className="empty">Noch keine Live-Telemetrie.</div>;

  const telemetry = vehicle.telemetry ?? {};
  const aircraft = telemetry.aircraft_state;
  const positioning = aircraft?.positioning;
  const rtk = positioning?.rtk ?? telemetry.rtk;
  const controller = telemetry.controller ?? {};
  const attitude = telemetry.attitude ?? {};
  const gimbal = telemetry.gimbal ?? {};
  const safety = telemetry.safety ?? {};
  const home = aircraft?.home ?? {};
  const payload = telemetry.payload ?? {};

  const metrics: Array<[string, unknown, string?]> = [
    ["Latitude", telemetry.latitude, ""],
    ["Longitude", telemetry.longitude, ""],
    ["Relative altitude", telemetry.relative_altitude_m, " m"],
    ["AMSL altitude", telemetry.amsl_altitude_m, " m"],
    ["Heading", telemetry.heading_deg, "°"],
    ["Battery", telemetry.battery?.capacity_percent, "%"],
  ];

  return (
    <div className="liveContent">
      <div className="liveHead">
        <div>
          <h2>{vehicle.name}</h2>
          <p>{vehicle.model} · {sourceLabel(vehicle)}</p>
        </div>
        <span className={vehicle.online ? "status good" : "status bad"}>
          {vehicle.online ? "ONLINE" : "OFFLINE"}
        </span>
      </div>

      <div className="liveGrid">
        <section className="panel liveSection">
          <div className="panelHead"><div><h2>Aircraft</h2><small>Position / motion</small></div></div>
          <div className="liveMetrics">
            {metrics.map(([label, value, unit]) => (
              <div className="liveMetric" key={label}>
                <span>{String(label)}</span>
                <strong>{textValue(value)}{value !== null && value !== undefined ? unit : ""}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="panel liveSection">
          <div className="panelHead"><div><h2>GNSS / RTK</h2><small>Fix and reference state</small></div></div>
          <div className="liveMetrics">
            {[
              ["Fix", positioning?.fix ?? rtk?.fix],
              ["Position source", positioning?.position_source],
              ["RTK raw fix", rtk?.raw_fix],
              ["RTK healthy", rtk?.healthy],
              ["RTK age", rtk?.age_ms],
              ["RTK source", rtk?.source],
              ["GNSS satellites", positioning?.gps_satellites ?? telemetry.gps_satellites],
              ["RTK satellites", rtk?.satellites ?? positioning?.rtk_satellites],
            ].map(([label, value]) => (
              <div className="liveMetric" key={String(label)}>
                <span>{String(label)}</span><strong>{textValue(value)}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="panel liveSection">
          <div className="panelHead"><div><h2>Controller / AirLink</h2><small>RC Pro / ground side</small></div></div>
          <div className="liveMetrics">
            {[
              ["AirLink RSSI", controller.airlink_rssi_raw],
              ["Wi-Fi RSSI", controller.wifi_rssi_dbm],
              ["Controller battery", controller.battery_percent],
              ["Controller lat", controller.latitude],
              ["Controller lon", controller.longitude],
              ["Controller heading", controller.heading_deg],
            ].map(([label, value]) => (
              <div className="liveMetric" key={String(label)}>
                <span>{String(label)}</span><strong>{textValue(value)}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="panel liveSection">
          <div className="panelHead"><div><h2>Attitude / Gimbal</h2><small>Aircraft and payload orientation</small></div></div>
          <div className="liveMetrics">
            {[
              ["Aircraft roll", attitude.roll_deg],
              ["Aircraft pitch", attitude.pitch_deg],
              ["Aircraft yaw", attitude.yaw_deg],
              ["Gimbal roll", gimbal.roll_deg ?? gimbal.joint_roll_deg],
              ["Gimbal pitch", gimbal.pitch_deg ?? gimbal.joint_pitch_deg],
              ["Gimbal yaw", gimbal.yaw_deg ?? gimbal.joint_yaw_deg],
            ].map(([label, value]) => (
              <div className="liveMetric" key={String(label)}>
                <span>{String(label)}</span><strong>{textValue(value)}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="panel liveSection">
          <div className="panelHead"><div><h2>{payload.platform ?? vehicle.model} Payload</h2><small>Model-specific sensors</small></div></div>
          <div className="liveMetrics">
            {[
              ["Thermal", payload.thermal],
              ["Multispectral", payload.multispectral],
              ["LRF", payload.lrf],
              ["Camera mode", payload.camera?.camera_mode],
              ["Live source", payload.camera?.live_view_source],
              ["Home lat", home.latitude],
            ].map(([label, value]) => (
              <div className="liveMetric" key={String(label)}>
                <span>{String(label)}</span><strong>{textValue(value)}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="panel liveSection">
          <div className="panelHead"><div><h2>Safety</h2><small>Operational state</small></div></div>
          <div className="liveMetrics">
            {[
              ["Ready to take off", safety.ready_to_takeoff],
              ["Manual override", safety.manual_override],
              ["Block reason", safety.takeoff_block_reason],
              ["Mode", aircraft?.mode],
              ["Armed", aircraft?.armed],
              ["Flying", aircraft?.is_flying],
            ].map(([label, value]) => (
              <div className="liveMetric" key={String(label)}>
                <span>{String(label)}</span><strong>{textValue(value)}</strong>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

export default function App() {
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [selectedSn, setSelectedSn] = useState<string | null>(null);
  const [activeView, setActiveView] = useState<ViewName>("operations");
  const [liveConnected, setLiveConnected] = useState(false);
  const [health, setHealth] = useState<SystemHealth | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    const [vehicleResult, healthResult] = await Promise.allSettled([
      fetchVehicles(),
      fetchSystemHealth(),
    ]);

    if (vehicleResult.status === "fulfilled") {
      setVehicles(vehicleResult.value);
      setSelectedSn((current) => current ?? vehicleResult.value[0]?.sn ?? null);
      setLoadError(null);
    } else {
      setLoadError(
        vehicleResult.reason instanceof Error
          ? vehicleResult.reason.message
          : String(vehicleResult.reason),
      );
    }

    if (healthResult.status === "fulfilled") setHealth(healthResult.value);
  }, []);

  useEffect(() => {
    void refresh();
    const timer = window.setInterval(() => void refresh(), 30_000);
    return () => window.clearInterval(timer);
  }, [refresh]);

  const upsertVehicle = useCallback((incoming: Vehicle) => {
    setVehicles((current) => {
      const index = current.findIndex((vehicle) => vehicle.sn === incoming.sn);
      if (index < 0) return [...current, incoming];

      const next = [...current];
      next[index] = mergeVehicle(next[index], incoming);
      return next;
    });
  }, []);

  const handleLiveEvent = useCallback(
    (event: LiveEvent) => {
      if (event.type === "vehicle_telemetry") {
        upsertVehicle(event.vehicle);
        return;
      }

      if (event.type === "telemetry") {
        setVehicles((current) => {
          const index = current.findIndex((vehicle) => vehicle.sn === event.device_sn);
          if (index < 0) {
            return [
              ...current,
              {
                id: `vehicle:${event.device_sn}`,
                sn: event.device_sn,
                name: event.device_sn,
                model: "DJI",
                source: "dji_cloud",
                sources: ["dji_cloud"],
                online: true,
                telemetry: event.state,
              },
            ];
          }
          const next = [...current];
          next[index] = {
            ...next[index],
            online: true,
            telemetry: mergeTelemetry(next[index].telemetry, event.state),
          };
          return next;
        });
        return;
      }

      if (event.type === "device_online" || event.type === "device_offline") {
        setVehicles((current) =>
          current.map((vehicle) =>
            vehicle.sn === event.device_sn
              ? { ...vehicle, online: event.type === "device_online" }
              : vehicle,
          ),
        );
        return;
      }

      if (event.type === "topology") void refresh();
    },
    [refresh, upsertVehicle],
  );

  useLiveEvents(handleLiveEvent, setLiveConnected);

  const telemetryBySn = useMemo(
    () =>
      Object.fromEntries(
        vehicles
          .filter((vehicle) => vehicle.telemetry)
          .map((vehicle) => [vehicle.sn, vehicle.telemetry as Telemetry]),
      ),
    [vehicles],
  );

  const selectedVehicle =
    vehicles.find((vehicle) => vehicle.sn === selectedSn) ?? vehicles[0] ?? null;

  const onlineCount = vehicles.filter((vehicle) => vehicle.online).length;
  const rtkCount = vehicles.filter((vehicle) => positionStatus(vehicle).usable).length;
  const nav = NAV.find(([name]) => name === activeView) ?? NAV[0];

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span className="brandMark">M3</span>
          <div><strong>M3-Cloud</strong><small>Enterprise Operations</small></div>
        </div>

        <nav>
          {NAV.map(([name, title]) => (
            <button
              className={activeView === name ? "navItem active" : "navItem"}
              data-view={name}
              key={name}
              onClick={() => setActiveView(name)}
              type="button"
            >
              {title}
            </button>
          ))}
        </nav>

        <div className="sourceLegend">
          <span><i className="dot cloud" />DJI Cloud API</span>
          <span><i className="dot lyrebird" />Lyrebird</span>
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div><h1>{nav[1]}</h1><p>{nav[2]}</p></div>
          <div className="topActions">
            <span className={liveConnected ? "status good" : "status warn"}>
              {liveConnected ? "Backend live" : "Backend wartet"}
            </span>
            <button onClick={() => void refresh()} type="button">Aktualisieren</button>
          </div>
        </header>

        {activeView === "operations" ? (
          <section className="view active">
            <div className="metrics summaryMetrics">
              <article><span>Aircraft</span><strong>{vehicles.length}</strong><small>{vehicles.length ? "telemetry active" : "keine Telemetrie"}</small></article>
              <article><span>Online</span><strong>{onlineCount}</strong><small>Cloud + Lyrebird</small></article>
              <article><span>RTK FIX</span><strong>{rtkCount}</strong><small>MSDK/MAVLink bestätigt</small></article>
              <article><span>Active missions</span><strong>0</strong><small>Wayline / external</small></article>
            </div>

            <div className="workspace">
              <section className="mapCard">
                {loadError ? <div className="error-banner">{loadError}</div> : null}
                <MapView
                  devices={vehicles}
                  telemetry={telemetryBySn}
                  selectedSn={selectedVehicle?.sn ?? null}
                />
              </section>

              <aside className="fleetPanel">
                <div className="panelHead">
                  <div><h2>Fleet</h2><small>M3E · M3T · M3M</small></div>
                  <span>{vehicles.length} devices</span>
                </div>
                <div className="fleetList">
                  {vehicles.length === 0 ? (
                    <div className="empty">Noch keine Aircraft-Telemetrie vom Backend.</div>
                  ) : vehicles.map((vehicle) => {
                    const telemetry = vehicle.telemetry;
                    const positioning = positionStatus(vehicle);
                    return (
                      <button
                        className={vehicle.sn === selectedVehicle?.sn ? "fleetItem selected" : "fleetItem"}
                        key={vehicle.sn}
                        onClick={() => setSelectedSn(vehicle.sn)}
                        type="button"
                      >
                        <div className="row">
                          <div>
                            <strong>{vehicle.name}</strong>
                            <small>{vehicle.model} · {sourceLabel(vehicle)}</small>
                          </div>
                          <span className={`badge ${positioning.className}`}>{positioning.label}</span>
                        </div>
                        <div className="telemetry">
                          <span>Battery<b>{textValue(telemetry?.battery?.capacity_percent)}{telemetry?.battery?.capacity_percent != null ? "%" : ""}</b></span>
                          <span>Altitude<b>{numberValue(telemetry?.relative_altitude_m)}{telemetry?.relative_altitude_m != null ? " m" : ""}</b></span>
                          <span>Satellites<b>{textValue(telemetry?.aircraft_state?.positioning?.gps_satellites ?? telemetry?.gps_satellites)}</b></span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              </aside>
            </div>

            <PayloadPanel vehicle={selectedVehicle} />

            <div className="bottomGrid">
              <section className="panel">
                <div className="panelHead"><div><h2>Mission activity</h2><small>Waylines und externe Missionen</small></div></div>
                <div className="empty">Keine aktive Mission.</div>
              </section>
              <section className="panel">
                <div className="panelHead"><div><h2>System links</h2><small>Datenpfade</small></div></div>
                <div className="links">
                  <HealthValue label="DJI Cloud API" value={health?.components.dji} />
                  <HealthValue label="Lyrebird" value={health?.components.lyrebird} />
                  <HealthValue label="MQTT / EMQX" value={health?.components.mqtt} />
                  <HealthValue label="Object storage" value={health?.components.storage} />
                </div>
              </section>
            </div>
          </section>
        ) : null}

        {activeView === "projects" ? (
          <section className="view active">
            <ProjectsView />
          </section>
        ) : null}

        {activeView === "live" ? (
          <section className="view active">
            <LiveView vehicle={selectedVehicle} />
          </section>
        ) : null}

        {activeView === "flights" ? (
          <section className="view active">
            <FlightHistoryView />
          </section>
        ) : null}

        {activeView === "media" ? (
          <section className="view active">
            <MediaView />
          </section>
        ) : null}

        {activeView === "processing" ? (
          <section className="view active">
            <ProcessingView />
          </section>
        ) : null}

        {activeView === "system" ? (
          <section className="view active">
            <div className="systemGrid">
              {Object.entries(health?.components ?? {}).map(([name, value]) => (
                <section className="panel systemCard" key={name}>
                  <div className="panelHead"><div><h2>{name}</h2><small>runtime component</small></div></div>
                  <pre>{JSON.stringify(value, null, 2)}</pre>
                </section>
              ))}
            </div>
          </section>
        ) : null}

        {!["operations", "projects", "live", "flights", "media", "processing", "system"].includes(activeView) ? (
          <section className="view active">
            <div className="placeholder">
              <h2>{nav[1]}</h2>
              <p>{nav[2]}</p>
            </div>
          </section>
        ) : null}
      </main>
    </div>
  );
}
