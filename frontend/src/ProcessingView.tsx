import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createWebODMJob,
  fetchMedia,
  fetchProcessingMap,
  fetchProcessingResults,
  fetchProcessingScenes,
  fetchProcessingJobs,
  fetchProcessingProfiles,
  processingResultDownloadUrl,
} from "./api";
import type {
  MediaAsset,
  ProcessingJob,
  ProcessingProfile,
  ProcessingResult,
} from "./types";
import { Processing3DView } from "./Processing3DView";
import { ProcessingResultMap } from "./ProcessingResultMap";

const ACTIVE_STATUSES = new Set([
  "QUEUED",
  "UPLOADING",
  "SUBMITTED",
  "QUEUED_REMOTE",
  "RUNNING",
  "IMPORTING_RESULTS",
]);

function parentPath(relativePath: string): string {
  const index = relativePath.lastIndexOf("/");
  return index > 0 ? relativePath.slice(0, index) : "";
}

function percent(value: number): string {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

function statusClass(status: string): string {
  if (status === "COMPLETED") return "good";
  if (
    status === "FAILED" ||
    status === "CANCELED" ||
    status === "INTERRUPTED" ||
    status === "RESULT_IMPORT_FAILED"
  ) {
    return "bad";
  }
  return "warn";
}

function eligible(asset: MediaAsset): boolean {
  return (
    asset.present &&
    !asset.duplicate_of &&
    ["RGB", "WIDE"].includes(asset.media_kind)
  );
}

function datasets(assets: MediaAsset[]): Array<{
  prefix: string;
  platform: string;
  count: number;
  bytes: number;
}> {
  const grouped = new Map<string, {
    prefix: string;
    platform: string;
    count: number;
    bytes: number;
  }>();

  for (const asset of assets.filter(eligible)) {
    const prefix = parentPath(asset.relative_path);
    if (!prefix) continue;
    const key = `${asset.platform}:${prefix}`;
    const current = grouped.get(key) ?? {
      prefix,
      platform: asset.platform,
      count: 0,
      bytes: 0,
    };
    current.count += 1;
    current.bytes += asset.size_bytes;
    grouped.set(key, current);
  }

  return Array.from(grouped.values())
    .filter((item) => item.count >= 2)
    .sort((left, right) => left.prefix.localeCompare(right.prefix));
}

function bytes(value: number): string {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit === 0 ? 0 : 1)} ${units[unit]}`;
}

export function ProcessingView() {
  const [assets, setAssets] = useState<MediaAsset[]>([]);
  const [profiles, setProfiles] = useState<ProcessingProfile[]>([]);
  const [jobs, setJobs] = useState<ProcessingJob[]>([]);
  const [prefix, setPrefix] = useState("");
  const [profile, setProfile] = useState("m3e-ortho");
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [results, setResults] = useState<Record<string, ProcessingResult[]>>({});
  const [mapInfo, setMapInfo] = useState<Awaited<ReturnType<typeof fetchProcessingMap>>>(null);
  const [scenes, setScenes] = useState<Awaited<ReturnType<typeof fetchProcessingScenes>>>([]);
  const [scene, setScene] = useState<Awaited<ReturnType<typeof fetchProcessingScenes>>[number] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const loadResults = useCallback(async (jobId: string) => {
    try {
      const values = await fetchProcessingResults(jobId);
      setResults((current) => ({ ...current, [jobId]: values }));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, []);

  const openMap = useCallback(async (jobId: string) => {
    try {
      const value = await fetchProcessingMap(jobId);
      if (!value) {
        setError("Für diesen Job ist noch kein Orthophoto-Kartenlayer veröffentlicht.");
        return;
      }
      setMapInfo(value);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, []);

  const open3D = useCallback(async (jobId: string) => {
    try {
      const values = await fetchProcessingScenes(jobId);
      if (values.length === 0) {
        setError("Für diesen Job ist noch keine 3D-Tiles-Szene veröffentlicht.");
        return;
      }
      setScenes(values);
      setScene(values[0]);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [nextAssets, nextProfiles, nextJobs] = await Promise.all([
        fetchMedia(),
        fetchProcessingProfiles(),
        fetchProcessingJobs(),
      ]);
      setAssets(nextAssets);
      setProfiles(nextProfiles);
      setJobs(nextJobs);
      setProfile((current) =>
        nextProfiles.some((item) => item.key === current)
          ? current
          : nextProfiles[0]?.key ?? "",
      );
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  useEffect(() => {
    const hasActive = jobs.some((job) => ACTIVE_STATUSES.has(job.status));
    if (!hasActive) return;

    const timer = window.setInterval(() => {
      void fetchProcessingJobs()
        .then(setJobs)
        .catch(() => undefined);
    }, 3000);
    return () => window.clearInterval(timer);
  }, [jobs]);

  const availableDatasets = useMemo(() => datasets(assets), [assets]);
  const selectedDataset = availableDatasets.find((item) => item.prefix === prefix);
  const selectedProfile = profiles.find((item) => item.key === profile);

  useEffect(() => {
    if (!prefix && availableDatasets.length > 0) {
      setPrefix(availableDatasets[0].prefix);
    }
  }, [availableDatasets, prefix]);

  useEffect(() => {
    if (!prefix) return;
    if (!name || availableDatasets.some((item) => item.prefix.endsWith(name))) {
      setName(prefix.split("/").pop() ?? prefix);
    }
  }, [availableDatasets, name, prefix]);

  const submit = useCallback(async () => {
    if (!prefix || !profile || !selectedDataset) return;
    setSubmitting(true);
    try {
      const job = await createWebODMJob({
        name: name.trim() || prefix.split("/").pop() || "WebODM task",
        input_prefix: prefix,
        platform:
          selectedDataset.platform === "UNKNOWN"
            ? undefined
            : selectedDataset.platform,
        profile,
      });
      setJobs((current) => [job, ...current.filter((item) => item.id !== job.id)]);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSubmitting(false);
    }
  }, [name, prefix, profile, selectedDataset]);

  return (
    <div className="processingView">
      <section className="panel processingCreate">
        <div className="panelHead">
          <div>
            <h2>WebODM processing</h2>
            <small>External originals → streamed upload → persistent task</small>
          </div>
          <span>{availableDatasets.length} datasets</span>
        </div>

        <div className="processingForm">
          <label>
            Dataset
            <select value={prefix} onChange={(event) => setPrefix(event.target.value)}>
              {availableDatasets.length === 0 ? (
                <option value="">No eligible RGB/Wide dataset</option>
              ) : availableDatasets.map((item) => (
                <option key={`${item.platform}:${item.prefix}`} value={item.prefix}>
                  {item.prefix} · {item.platform} · {item.count} images
                </option>
              ))}
            </select>
          </label>

          <label>
            Task name
            <input
              maxLength={255}
              onChange={(event) => setName(event.target.value)}
              value={name}
            />
          </label>

          <label>
            Profile
            <select value={profile} onChange={(event) => setProfile(event.target.value)}>
              {profiles.map((item) => (
                <option key={item.key} value={item.key}>{item.title}</option>
              ))}
            </select>
          </label>

          <button
            disabled={submitting || !selectedDataset || !profile}
            onClick={() => void submit()}
            type="button"
          >
            {submitting ? "Queueing…" : "Start WebODM"}
          </button>
        </div>

        {selectedDataset ? (
          <div className="processingDataset">
            <span>Platform<b>{selectedDataset.platform}</b></span>
            <span>Images<b>{selectedDataset.count}</b></span>
            <span>Input size<b>{bytes(selectedDataset.bytes)}</b></span>
            <span>Media<b>RGB / Wide only</b></span>
          </div>
        ) : null}

        {selectedProfile ? (
          <div className="processingProfile">
            <strong>{selectedProfile.title}</strong>
            <span>{selectedProfile.purpose}</span>
          </div>
        ) : null}

        {error ? <div className="mediaWarning">{error}</div> : null}
      </section>

      <section className="panel processingJobs">
        <div className="panelHead">
          <div>
            <h2>Processing jobs</h2>
            <small>WebODM project/task state</small>
          </div>
          <button onClick={() => void refresh()} type="button">Refresh</button>
        </div>

        <div className="processingJobList">
          {jobs.length === 0 ? (
            <div className="empty">Noch keine Processing-Jobs.</div>
          ) : jobs.map((job) => (
            <article className="processingJob" key={job.id}>
              <div className="processingJobHead">
                <div>
                  <strong>{job.name}</strong>
                  <small>{job.input_prefix} · {job.platform ?? "AUTO"}</small>
                </div>
                <span className={`status ${statusClass(job.status)}`}>{job.status}</span>
              </div>

              <div className="processingProgress">
                <i style={{ width: percent(job.progress) }} />
              </div>

              <div className="processingMetrics">
                <span>Progress<b>{percent(job.progress)}</b></span>
                <span>Images<b>{job.uploaded_count}/{job.image_count}</b></span>
                <span>Project<b>{job.remote_project_id ?? "—"}</b></span>
                <span>Task<b>{job.remote_task_id ?? "—"}</b></span>
                <span>Remote<b>{job.remote_status ?? "—"}</b></span>
                <span>Assets<b>{job.available_assets.length}</b></span>
              </div>

              {job.available_assets.length > 0 ? (
                <div className="processingAssets">
                  {job.available_assets.map((asset) => <span key={asset}>{asset}</span>)}
                </div>
              ) : null}

              {["COMPLETED", "RESULT_IMPORT_FAILED"].includes(job.status) ? (
                <div className="processingStoredResults">
                  <button onClick={() => void loadResults(job.id)} type="button">
                    M3 results
                  </button>
                  <button onClick={() => void openMap(job.id)} type="button">
                    Orthophoto map
                  </button>
                  <button onClick={() => void open3D(job.id)} type="button">
                    3D viewer
                  </button>
                  {(results[job.id] ?? []).map((result) => (
                    <a
                      href={processingResultDownloadUrl(job.id, result.id)}
                      key={result.id}
                    >
                      {result.asset_name}
                    </a>
                  ))}
                </div>
              ) : null}

              {job.error ? <div className="processingError">{job.error}</div> : null}
            </article>
          ))}
        </div>
      </section>

      {mapInfo ? (
        <ProcessingResultMap
          info={mapInfo}
          onClose={() => setMapInfo(null)}
        />
      ) : null}

      {scene ? (
        <Processing3DView
          scene={scene}
          scenes={scenes}
          onSelect={setScene}
          onClose={() => {
            setScene(null);
            setScenes([]);
          }}
        />
      ) : null}
    </div>
  );
}
