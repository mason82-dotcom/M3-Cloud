import { useCallback, useEffect, useMemo, useState } from "react";

import {
  assignMediaDatasetFlight,
  fetchFlights,
  fetchMedia,
  fetchMediaDatasetManifest,
  fetchMediaDatasets,
  fetchMediaGroups,
  fetchMediaImportStatus,
  scanMediaImport,
} from "./api";
import type {
  MediaAsset,
  MediaDataset,
  MediaDatasetManifest,
  MediaGroup,
  MediaImportStatus,
  FlightSummary,
} from "./types";

function bytes(value: number): string {
  if (!Number.isFinite(value) || value < 0) return "—";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let index = 0;
  while (size >= 1024 && index < units.length - 1) {
    size /= 1024;
    index += 1;
  }
  return `${size.toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function platformClass(platform: string): string {
  const value = platform.toLowerCase();
  return ["m3e", "m3t", "m3m"].includes(value) ? value : "unknown";
}

export function MediaView() {
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [datasets, setDatasets] = useState<MediaDataset[]>([]);
  const [groups, setGroups] = useState<MediaGroup[]>([]);
  const [flights, setFlights] = useState<FlightSummary[]>([]);
  const [status, setStatus] = useState<MediaImportStatus | null>(null);
  const [platform, setPlatform] = useState("");
  const [mediaKind, setMediaKind] = useState("");
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const [manifest, setManifest] = useState<MediaDatasetManifest | null>(null);
  const [scanning, setScanning] = useState(false);
  const [assigningDataset, setAssigningDataset] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [nextAssets, nextDatasets, nextGroups, nextStatus, nextFlights] = await Promise.all([
        fetchMedia(platform || undefined, mediaKind || undefined),
        fetchMediaDatasets(platform || undefined),
        fetchMediaGroups(platform || undefined),
        fetchMediaImportStatus(),
        fetchFlights(undefined, 500),
      ]);
      setAssets(nextAssets);
      setDatasets(nextDatasets);
      setGroups(nextGroups);
      setStatus(nextStatus);
      setFlights(nextFlights);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [mediaKind, platform]);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const runScan = useCallback(async () => {
    setScanning(true);
    try {
      await scanMediaImport();
      await refresh();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setScanning(false);
    }
  }, [refresh]);

  const visibleAssets = useMemo(
    () =>
      selectedGroup
        ? assets.filter((asset) => asset.capture_group === selectedGroup)
        : assets,
    [assets, selectedGroup],
  );

  const totalBytes = assets.reduce((sum, asset) => sum + asset.size_bytes, 0);
  const duplicateCount = assets.filter((asset) => asset.duplicate_of).length;
  const platformCounts = Object.fromEntries(
    ["M3E", "M3T", "M3M", "UNKNOWN"].map((name) => [
      name,
      assets.filter((asset) => asset.platform === name).length,
    ]),
  );

  return (
    <div className="mediaView">
      <section className="mediaStatus panel">
        <div className="panelHead">
          <div>
            <h2>External media import</h2>
            <small>Read-only watch folder</small>
          </div>
          <button
            disabled={scanning || status?.enabled === false}
            onClick={() => void runScan()}
            type="button"
          >
            {scanning || status?.scan_running ? "Scanning…" : "Scan now"}
          </button>
        </div>

        <div className="mediaStatusGrid">
          <span>Root<b>{status?.root ?? "—"}</b></span>
          <span>Mount<b>{status?.exists && status?.readable ? "READY" : "UNAVAILABLE"}</b></span>
          <span>Catalog<b>{assets.length} files</b></span>
          <span>Size<b>{bytes(totalBytes)}</b></span>
          <span>Duplicates<b>{duplicateCount}</b></span>
          <span>Last scan<b>{status?.last_scan?.finished_at ? new Date(status.last_scan.finished_at).toLocaleString() : "—"}</b></span>
        </div>
        {status?.last_error ? (
          <div className="mediaWarning">{status.last_error}</div>
        ) : null}
        {error ? <div className="mediaWarning">{error}</div> : null}
      </section>

      <div className="mediaSummary">
        {["M3E", "M3T", "M3M", "UNKNOWN"].map((name) => (
          <button
            className={platform === name ? `mediaPlatform active ${platformClass(name)}` : `mediaPlatform ${platformClass(name)}`}
            key={name}
            onClick={() => {
              setPlatform(platform === name ? "" : name);
              setSelectedGroup(null);
            }}
            type="button"
          >
            <span>{name}</span>
            <strong>{platformCounts[name] ?? 0}</strong>
          </button>
        ))}
      </div>

      <section className="panel mediaDatasets">
        <div className="panelHead">
          <div>
            <h2>Workflow datasets</h2>
            <small>Server-side readiness from the external originals</small>
          </div>
          <span>{datasets.length} datasets</span>
        </div>
        <div className="mediaDatasetGrid">
          {datasets.length === 0 ? (
            <div className="empty">Noch kein workflowfähiges Dataset erkannt.</div>
          ) : datasets.map((dataset) => (
            <article className="mediaDataset" key={`${dataset.platform}:${dataset.prefix}`}>
              <div className="mediaDatasetHead">
                <div>
                  <strong>{dataset.prefix}</strong>
                  <small>{dataset.platform} · {dataset.asset_count} originals · {bytes(dataset.size_bytes)}</small>
                </div>
                <span>{dataset.capture_group_count} groups</span>
              </div>
              <div className="workflowBadges">
                {dataset.workflows.map((workflow) => (
                  <span
                    className={workflow.ready ? "workflowBadge ready" : "workflowBadge incomplete"}
                    key={workflow.key}
                    title={workflow.reason}
                  >
                    {workflow.key} {workflow.ready ? "READY" : "INCOMPLETE"}
                  </span>
                ))}
              </div>
              <small className="datasetKinds">
                {Object.entries(dataset.media_kinds)
                  .map(([kind, count]) => `${kind} ${count}`)
                  .join(" · ")}
              </small>
              <label className="datasetFlight">
                Flight
                <select
                  disabled={!dataset.id || assigningDataset === dataset.id}
                  value={dataset.flight_id ?? ""}
                  onChange={(event) => {
                    if (!dataset.id) return;
                    const flightId = event.target.value || null;
                    setAssigningDataset(dataset.id);
                    void assignMediaDatasetFlight(dataset.id, flightId)
                      .then(() => refresh())
                      .catch((reason: unknown) =>
                        setError(reason instanceof Error ? reason.message : String(reason)),
                      )
                      .finally(() => setAssigningDataset(null));
                  }}
                >
                  <option value="">Unassigned</option>
                  {flights.map((flight) => (
                    <option key={flight.id} value={flight.id}>
                      {flight.aircraft_sn} · {new Date(flight.started_at).toLocaleString()}
                    </option>
                  ))}
                </select>
              </label>
              {dataset.flight_id ? (
                <small className="datasetFlightLink">
                  Linked: {dataset.flight_aircraft_sn ?? "Aircraft"} · {
                    dataset.flight_started_at
                      ? new Date(dataset.flight_started_at).toLocaleString()
                      : dataset.flight_id
                  }
                </small>
              ) : null}
              <button
                className="datasetManifestButton"
                onClick={() => {
                  void fetchMediaDatasetManifest(dataset.prefix)
                    .then(setManifest)
                    .catch((reason: unknown) =>
                      setError(reason instanceof Error ? reason.message : String(reason)),
                    );
                }}
                type="button"
              >
                Handoff manifest
              </button>
            </article>
          ))}
        </div>
      </section>

      {manifest ? (
        <section className="panel mediaManifest">
          <div className="panelHead">
            <div>
              <h2>Dataset handoff</h2>
              <small>{manifest.platform} · originals remain external/read-only</small>
            </div>
            <button onClick={() => setManifest(null)} type="button">Close</button>
          </div>
          <div className="manifestPath">
            <span>External path</span>
            <code>{manifest.external_path}</code>
          </div>
          <div className="manifestGroups">
            {manifest.capture_groups.map((group) => (
              <article
                className={group.complete ? "manifestGroup complete" : "manifestGroup incomplete"}
                key={group.capture_group}
              >
                <strong>{group.capture_group.split("/").pop()}</strong>
                <span>{group.complete ? "COMPLETE" : "INCOMPLETE"}</span>
                <small>
                  {group.files.map((file) => `${file.media_kind}: ${file.filename}`).join(" · ")}
                </small>
              </article>
            ))}
          </div>
        </section>
      ) : null}

      <section className="panel mediaCatalog">
        <div className="panelHead">
          <div>
            <h2>Media catalog</h2>
            <small>Original filenames and capture groups are preserved</small>
          </div>
          <div className="mediaFilters">
            <select
              aria-label="Media kind"
              value={mediaKind}
              onChange={(event) => {
                setMediaKind(event.target.value);
                setSelectedGroup(null);
              }}
            >
              <option value="">All types</option>
              <option value="RGB">RGB</option>
              <option value="WIDE">Wide</option>
              <option value="ZOOM">Zoom</option>
              <option value="THERMAL">Thermal</option>
              <option value="MS_GREEN">MS Green</option>
              <option value="MS_RED">MS Red</option>
              <option value="MS_RED_EDGE">MS Red Edge</option>
              <option value="MS_NIR">MS NIR</option>
            </select>
            {selectedGroup ? (
              <button onClick={() => setSelectedGroup(null)} type="button">
                Clear group
              </button>
            ) : null}
          </div>
        </div>

        <div className="mediaCatalogGrid">
          <aside className="mediaGroups">
            {groups.length === 0 ? (
              <div className="empty">Noch keine Capture-Gruppen erkannt.</div>
            ) : groups.map((group) => (
              <button
                className={group.capture_group === selectedGroup ? "mediaGroup selected" : "mediaGroup"}
                key={`${group.platform}:${group.capture_group}`}
                onClick={() => setSelectedGroup(group.capture_group)}
                type="button"
              >
                <strong>{group.capture_group.split("/").pop()}</strong>
                <small>{group.platform} · {group.asset_count} files · {bytes(group.size_bytes)}</small>
              </button>
            ))}
          </aside>

          <div className="mediaTableWrap">
            <table className="mediaTable">
              <thead>
                <tr>
                  <th>File</th>
                  <th>Platform</th>
                  <th>Type</th>
                  <th>Size</th>
                  <th>State</th>
                </tr>
              </thead>
              <tbody>
                {visibleAssets.map((asset) => (
                  <tr key={asset.id}>
                    <td>
                      <strong>{asset.filename}</strong>
                      <small title={asset.relative_path}>{asset.relative_path}</small>
                    </td>
                    <td>{asset.platform}</td>
                    <td>{asset.media_kind}</td>
                    <td>{bytes(asset.size_bytes)}</td>
                    <td>
                      <span className={asset.present ? "mediaState present" : "mediaState missing"}>
                        {asset.present ? "present" : "missing"}
                      </span>
                      {asset.duplicate_of ? <small>duplicate</small> : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {visibleAssets.length === 0 ? (
              <div className="empty">Keine Medien für diesen Filter.</div>
            ) : null}
          </div>
        </div>
      </section>
    </div>
  );
}
