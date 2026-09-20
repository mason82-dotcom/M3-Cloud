import { useCallback, useEffect, useMemo, useState } from "react";

import {
  assignMediaDatasetFlight,
  autoMatchMediaDatasetFlight,
  fetchFlights,
  fetchMedia,
  fetchMediaDatasetManifest,
  fetchMediaDatasets,
  fetchMediaGroups,
  fetchMediaImportStatus,
  fetchMediaPositions,
  mediaDatasetManifestDownloadUrl,
  scanMediaImport,
} from "./api";
import type {
  MediaAsset,
  MediaDataset,
  MediaDatasetManifest,
  MediaGroup,
  MediaImportStatus,
  MediaPositionCollection,
  FlightSummary,
} from "./types";
import { MediaCaptureMap } from "./MediaCaptureMap";

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
  const [positions, setPositions] = useState<MediaPositionCollection>({
    type: "FeatureCollection",
    features: [],
  });
  const [platform, setPlatform] = useState("");
  const [mediaKind, setMediaKind] = useState("");
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const [selectedAssetId, setSelectedAssetId] = useState<string | null>(null);
  const [manifest, setManifest] = useState<MediaDatasetManifest | null>(null);
  const [scanning, setScanning] = useState(false);
  const [assigningDataset, setAssigningDataset] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const [
        nextAssets,
        nextDatasets,
        nextGroups,
        nextStatus,
        nextFlights,
        nextPositions,
      ] = await Promise.all([
        fetchMedia(platform || undefined, mediaKind || undefined),
        fetchMediaDatasets(platform || undefined),
        fetchMediaGroups(platform || undefined),
        fetchMediaImportStatus(),
        fetchFlights(undefined, 500),
        fetchMediaPositions(
          platform || undefined,
          mediaKind || undefined,
          selectedGroup || undefined,
        ),
      ]);
      setAssets(nextAssets);
      setDatasets(nextDatasets);
      setGroups(nextGroups);
      setStatus(nextStatus);
      setFlights(nextFlights);
      setPositions(nextPositions);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [mediaKind, platform, selectedGroup]);

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

  const selectedAsset =
    assets.find((asset) => asset.id === selectedAssetId) ?? null;

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
                {" · "}
                GPS {dataset.gps_count ?? 0}/{dataset.asset_count}
                {" · "}
                metadata {dataset.metadata_ready_count ?? 0}/{dataset.asset_count}
              </small>
              <div className="datasetCaptureTime">
                <span>Capture</span>
                <b>{
                  dataset.capture_started_at
                    ? new Date(dataset.capture_started_at).toLocaleString()
                    : "No DJI filename timestamp"
                }</b>
                {dataset.capture_ended_at && dataset.capture_ended_at !== dataset.capture_started_at ? (
                  <small>to {new Date(dataset.capture_ended_at).toLocaleString()}</small>
                ) : null}
              </div>
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
              <div className="datasetMatchRow">
                <small className="datasetFlightLink">
                  {dataset.flight_id
                    ? `Linked: ${dataset.flight_aircraft_sn ?? "Aircraft"} · ${
                        dataset.flight_started_at
                          ? new Date(dataset.flight_started_at).toLocaleString()
                          : dataset.flight_id
                      }`
                    : `Match: ${dataset.flight_match_status ?? "NO_CAPTURE_TIME"}`}
                  {dataset.flight_assignment_source
                    ? ` · ${dataset.flight_assignment_source}`
                    : ""}
                </small>
                {dataset.id ? (
                  <button
                    disabled={assigningDataset === dataset.id}
                    onClick={() => {
                      if (!dataset.id) return;
                      setAssigningDataset(dataset.id);
                      void autoMatchMediaDatasetFlight(dataset.id)
                        .then(() => refresh())
                        .catch((reason: unknown) =>
                          setError(reason instanceof Error ? reason.message : String(reason)),
                        )
                        .finally(() => setAssigningDataset(null));
                    }}
                    type="button"
                  >
                    Auto match
                  </button>
                ) : null}
              </div>
              {dataset.flight_match_details?.validation ? (
                <div className="datasetMatchEvidence">
                  <span>
                    {dataset.flight_match_details.validation}
                    {dataset.flight_match_details.gps_points_available != null
                      ? ` · GPS ${dataset.flight_match_details.gps_points_sampled ?? 0}/${dataset.flight_match_details.gps_points_available}`
                      : ""}
                  </span>
                  {(dataset.flight_match_details.candidates ?? []).map((candidate) => (
                    <small key={candidate.flight_id}>
                      {candidate.aircraft_sn} · {candidate.spatial_status}
                      {candidate.gps_within_fraction != null
                        ? ` · ${Math.round(candidate.gps_within_fraction * 100)}% ≤ ${dataset.flight_match_details?.gps_max_distance_m ?? "?"} m`
                        : ""}
                      {candidate.median_distance_m != null
                        ? ` · median ${candidate.median_distance_m.toFixed(1)} m`
                        : ""}
                      {candidate.timed_points_sampled
                        ? ` · time-paired ${candidate.timed_points_paired ?? 0}/${candidate.timed_points_sampled}`
                        : ""}
                      {candidate.median_time_delta_s != null
                        ? ` · Δt ${candidate.median_time_delta_s.toFixed(1)} s`
                        : ""}
                    </small>
                  ))}
                </div>
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
            <div className="manifestActions">
              <a href={mediaDatasetManifestDownloadUrl(manifest.prefix)}>
                Download JSON
              </a>
              <button onClick={() => setManifest(null)} type="button">Close</button>
            </div>
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

      <section className="panel mediaGeoQa">
        <div className="panelHead">
          <div>
            <h2>Capture positions</h2>
            <small>EXIF GPS / DJI XMP geospatial QA before processing</small>
          </div>
          <span>{positions.features.length} geotagged</span>
        </div>
        <MediaCaptureMap
          data={positions}
          onSelect={(assetId) => setSelectedAssetId(assetId)}
        />
      </section>

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
                  <tr
                    className={asset.id === selectedAssetId ? "selected" : ""}
                    key={asset.id}
                    onClick={() => setSelectedAssetId(asset.id)}
                  >
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

      {selectedAsset ? (
        <section className="panel mediaMetadataPanel">
          <div className="panelHead">
            <div>
              <h2>EXIF / GPS / DJI metadata</h2>
              <small>{selectedAsset.filename}</small>
            </div>
            <span>{selectedAsset.metadata?.status ?? "PENDING"}</span>
          </div>
          <div className="mediaMetadataGrid">
            <article>
              <h3>Capture</h3>
              <dl>
                <dt>UTC time</dt><dd>{selectedAsset.capture_time_utc ? new Date(selectedAsset.capture_time_utc).toISOString() : "—"}</dd>
                <dt>Source</dt><dd>{selectedAsset.capture_time_source ?? "—"}</dd>
                <dt>Camera</dt><dd>{[selectedAsset.metadata?.camera.make, selectedAsset.metadata?.camera.model].filter(Boolean).join(" ") || "—"}</dd>
                <dt>Serial</dt><dd>{selectedAsset.metadata?.camera.serial ?? "—"}</dd>
                <dt>Lens</dt><dd>{selectedAsset.metadata?.camera.lens_model ?? "—"}</dd>
              </dl>
            </article>
            <article>
              <h3>GPS / altitude</h3>
              <dl>
                <dt>Latitude</dt><dd>{selectedAsset.metadata?.gps.latitude ?? "—"}</dd>
                <dt>Longitude</dt><dd>{selectedAsset.metadata?.gps.longitude ?? "—"}</dd>
                <dt>EXIF altitude</dt><dd>{selectedAsset.metadata?.gps.altitude_m ?? "—"} {selectedAsset.metadata?.gps.altitude_ref ?? ""}</dd>
                <dt>DJI absolute</dt><dd>{selectedAsset.metadata?.dji_altitude.absolute_ellipsoid_m ?? "—"} m</dd>
                <dt>DJI relative</dt><dd>{selectedAsset.metadata?.dji_altitude.relative_takeoff_m ?? "—"} m</dd>
              </dl>
            </article>
            <article>
              <h3>Exposure / optics</h3>
              <dl>
                <dt>Dimensions</dt><dd>{selectedAsset.metadata?.image.width ?? "—"} × {selectedAsset.metadata?.image.height ?? "—"}</dd>
                <dt>Exposure</dt><dd>{selectedAsset.metadata?.image.exposure_time_s ?? "—"} s</dd>
                <dt>Aperture</dt><dd>{selectedAsset.metadata?.image.f_number ? `f/${selectedAsset.metadata.image.f_number}` : "—"}</dd>
                <dt>ISO</dt><dd>{selectedAsset.metadata?.image.iso ?? "—"}</dd>
                <dt>Focal length</dt><dd>{selectedAsset.metadata?.image.focal_length_mm ?? "—"} mm</dd>
              </dl>
            </article>
            <article>
              <h3>Aircraft / gimbal</h3>
              <dl>
                <dt>Flight yaw</dt><dd>{selectedAsset.metadata?.flight_attitude.yaw_deg ?? "—"}°</dd>
                <dt>Flight pitch</dt><dd>{selectedAsset.metadata?.flight_attitude.pitch_deg ?? "—"}°</dd>
                <dt>Flight roll</dt><dd>{selectedAsset.metadata?.flight_attitude.roll_deg ?? "—"}°</dd>
                <dt>Gimbal yaw</dt><dd>{selectedAsset.metadata?.gimbal_attitude.yaw_deg ?? "—"}°</dd>
                <dt>Gimbal pitch</dt><dd>{selectedAsset.metadata?.gimbal_attitude.pitch_deg ?? "—"}°</dd>
              </dl>
            </article>
          </div>
          {selectedAsset.metadata?.error ? (
            <div className="mediaWarning">{selectedAsset.metadata.error}</div>
          ) : null}
          <details className="mediaRawMetadata">
            <summary>Raw normalized EXIF/XMP</summary>
            <pre>{JSON.stringify(selectedAsset.metadata?.raw ?? {}, null, 2)}</pre>
          </details>
        </section>
      ) : null}
    </div>
  );
}
