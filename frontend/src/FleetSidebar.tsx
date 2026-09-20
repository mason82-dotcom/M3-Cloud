import type { Telemetry, Vehicle } from "./types";

interface FleetSidebarProps {
  devices: Vehicle[];
  telemetry: Record<string, Telemetry>;
  selectedSn: string | null;
  liveConnected: boolean;
  onSelect: (sn: string) => void;
}

function value(value: number | null | undefined, suffix = ""): string {
  return value == null ? "—" : `${value.toFixed(1)}${suffix}`;
}

export function FleetSidebar({
  devices,
  telemetry,
  selectedSn,
  liveConnected,
  onSelect,
}: FleetSidebarProps) {
  return (
    <aside className="fleet">
      <header className="fleet-header">
        <div>
          <div className="eyebrow">M3 CLOUD</div>
          <h1>Fleet</h1>
        </div>
        <div className={liveConnected ? "live live-ok" : "live"}>
          <span />
          {liveConnected ? "LIVE" : "OFFLINE"}
        </div>
      </header>

      <div className="fleet-list">
        {devices.length === 0 ? (
          <div className="empty">No DJI devices registered yet.</div>
        ) : (
          devices.map((device) => {
            const state = telemetry[device.sn];
            const selected = device.sn === selectedSn;
            const positioning = state?.aircraft_state?.positioning;
            const convergence = positioning?.fix ?? state?.position_state?.convergence ?? "UNKNOWN";
            const battery = state?.battery?.capacity_percent;

            return (
              <button
                className={selected ? "device-card selected" : "device-card"}
                key={device.sn}
                onClick={() => onSelect(device.sn)}
                type="button"
              >
                <div className="device-title">
                  <div>
                    <strong>{device.model}</strong>
                    <small>{device.sn}</small>
                  </div>
                  <span className={device.online ? "status online" : "status"}>
                    {device.online ? "ONLINE" : "OFFLINE"}
                  </span>
                </div>

                <div className="metrics">
                  <div>
                    <span>ALT</span>
                    <b>{value(state?.relative_altitude_m, " m")}</b>
                  </div>
                  <div>
                    <span>SPD</span>
                    <b>{value(state?.horizontal_speed_mps, " m/s")}</b>
                  </div>
                  <div>
                    <span>BAT</span>
                    <b>{battery == null ? "—" : `${battery}%`}</b>
                  </div>
                  <div>
                    <span>POS</span>
                    <b>{convergence}</b>
                  </div>
                </div>
              </button>
            );
          })
        )}
      </div>
    </aside>
  );
}
