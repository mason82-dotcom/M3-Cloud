import { useCallback, useEffect, useMemo, useState } from "react";

import {
  createThermogramJob,
  createWebODMJob,
  fetchExternalResultStatus,
  fetchMediaDatasets,
  fetchProcessingMap,
  fetchProcessingMaps,
  fetchProcessingResults,
  fetchProcessingScenes,
  fetchProcessingJobs,
  fetchProcessingProfiles,
  fetchThermogramHandoff,
  importExternalResults,
  processingResultDownloadUrl,
  thermogramHandoffDownloadUrl,
  updateExternalProcessingJob,
} from "./api";
import type {
  MediaDataset,
  ProcessingJob,
  ExternalResultStatus,
  ProcessingProfile,
  ProcessingResult,
  ThermogramHandoff,
} from "./types";
import { Processing3DView } from "./Processing3DView";
import { ProcessingResultMap } from "./ProcessingResultMap";

const ACTIVE_STATUSES = new Set([
  "QUEUED",
  "UPLOADING",
  "SUBMITTED",
  "QUEUED_REMOTE",
  "RUNNING",
  "WAITING_EXTERNAL",
  "RUNNING_EXTERNAL",
  "IMPORTING_RESULTS",
]);

function percent(value: number): string {
  return `${Math.round(Math.max(0, Math.min(1, value)) * 100)}%`;
}

function statusClass(status: string): string {
  if (status === "COMPLETED" || status === "COMPLETED_EXTERNAL") return "good";
  if (
    status === "FAILED" ||
    status === "CANCELED" ||
    status === "INTERRUPTED" ||
    status === "RESULT_IMPORT_FAILED" ||
    status === "FAILED_EXTERNAL"
  ) {
    return "bad";
  }
  return "warn";
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
  const [datasets, setDatasets] = useState<MediaDataset[]>([]);
  const [profiles, setProfiles] = useState<ProcessingProfile[]>([]);
  const [jobs, setJobs] = useState<ProcessingJob[]>([]);
  const [prefix, setPrefix] = useState("");
  const [profile, setProfile] = useState("m3e-ortho");
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [thermogramPrefix, setThermogramPrefix] = useState("");
  const [thermogramName, setThermogramName] = useState("");
  const [thermogramSubmitting, setThermogramSubmitting] = useState(false);
  const [handoffs, setHandoffs] = useState<Record<string, ThermogramHandoff>>({});
  const [externalResults, setExternalResults] = useState<Record<string, ExternalResultStatus>>({});
  const [results, setResults] = useState<Record<string, ProcessingResult[]>>({});
  const [mapInfo, setMapInfo] = useState<Awaited<ReturnType<typeof fetchProcessingMap>>>(null);
  const [maps, setMaps] = useState<Awaited<ReturnType<typeof fetchProcessingMaps>>>([]);
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
      const values = await fetchProcessingMaps(jobId);
      if (values.length === 0) {
        const fallback = await fetchProcessingMap(jobId);
        if (!fallback) {
          setError("Für diesen Job ist noch kein Kartenlayer veröffentlicht.");
          return;
        }
        setMaps([fallback]);
        setMapInfo(fallback);
      } else {
        const preferred =
          values.find((item) => item.layer_type === "ORTHOPHOTO") ?? values[0];
        setMaps(values);
        setMapInfo(preferred);
      }
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
      const [nextDatasets, nextProfiles, nextJobs] = await Promise.all([
        fetchMediaDatasets(),
        fetchProcessingProfiles(),
        fetchProcessingJobs(),
      ]);
      setDatasets(nextDatasets);
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

  const availableDatasets = useMemo(
    () =>
      datasets.filter((dataset) =>
        profiles.some((candidate) => {
          const platformOk =
            candidate.platforms.length === 0 ||
            candidate.platforms.includes(dataset.platform);
          const workflow = dataset.workflows.find(
            (item) => item.key === candidate.workflow,
          );
          return platformOk && workflow?.ready === true;
        }),
      ),
    [datasets, profiles],
  );
  const selectedDataset = availableDatasets.find((item) => item.prefix === prefix);
  const thermogramDatasets = useMemo(
    () =>
      datasets.filter((dataset) =>
        dataset.platform === "M3T" &&
        dataset.workflows.some(
          (workflow) => workflow.key === "THERMOGRAM" && workflow.ready,
        ),
      ),
    [datasets],
  );
  const selectedThermogramDataset = thermogramDatasets.find(
    (item) => item.prefix === thermogramPrefix,
  );
  const selectedThermogramWorkflow = selectedThermogramDataset?.workflows.find(
    (item) => item.key === "THERMOGRAM",
  );

  const compatibleProfiles = useMemo(
    () =>
      profiles.filter((candidate) => {
        if (!selectedDataset) return false;
        const platformOk =
          candidate.platforms.length === 0 ||
          candidate.platforms.includes(selectedDataset.platform);
        const workflow = selectedDataset.workflows.find(
          (item) => item.key === candidate.workflow,
        );
        return platformOk && workflow?.ready === true;
      }),
    [profiles, selectedDataset],
  );
  const selectedProfile = compatibleProfiles.find((item) => item.key === profile);
  const selectedWorkflow = selectedProfile
    ? selectedDataset?.workflows.find(
        (item) => item.key === selectedProfile.workflow,
      )
    : undefined;

  useEffect(() => {
    if (!prefix && availableDatasets.length > 0) {
      setPrefix(availableDatasets[0].prefix);
    }
  }, [availableDatasets, prefix]);

  useEffect(() => {
    if (!thermogramPrefix && thermogramDatasets.length > 0) {
      setThermogramPrefix(thermogramDatasets[0].prefix);
    }
  }, [thermogramDatasets, thermogramPrefix]);

  useEffect(() => {
    if (!thermogramPrefix) return;
    if (
      !thermogramName ||
      thermogramDatasets.some((item) => item.prefix.endsWith(thermogramName))
    ) {
      setThermogramName(
        `${thermogramPrefix.split("/").pop() ?? thermogramPrefix} Thermogram`,
      );
    }
  }, [thermogramDatasets, thermogramName, thermogramPrefix]);

  useEffect(() => {
    if (!prefix) return;
    if (!name || availableDatasets.some((item) => item.prefix.endsWith(name))) {
      setName(prefix.split("/").pop() ?? prefix);
    }
  }, [availableDatasets, name, prefix]);

  useEffect(() => {
    if (compatibleProfiles.length === 0) {
      setProfile("");
      return;
    }
    if (!compatibleProfiles.some((item) => item.key === profile)) {
      setProfile(compatibleProfiles[0].key);
    }
  }, [compatibleProfiles, profile]);

  const submitThermogram = useCallback(async () => {
    if (!selectedThermogramDataset || !thermogramPrefix) return;
    setThermogramSubmitting(true);
    try {
      const job = await createThermogramJob({
        name:
          thermogramName.trim() ||
          `${thermogramPrefix.split("/").pop() ?? "M3T"} Thermogram`,
        input_prefix: thermogramPrefix,
      });
      const handoff = await fetchThermogramHandoff(job.id);
      setHandoffs((current) => ({ ...current, [job.id]: handoff }));
      setJobs((current) => [
        job,
        ...current.filter((item) => item.id !== job.id),
      ]);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setThermogramSubmitting(false);
    }
  }, [selectedThermogramDataset, thermogramName, thermogramPrefix]);

  const updateExternal = useCallback(
    async (
      job: ProcessingJob,
      nextStatus: "RUNNING_EXTERNAL" | "COMPLETED_EXTERNAL",
    ) => {
      try {
        const updated = await updateExternalProcessingJob(job.id, nextStatus);
        setJobs((current) =>
          current.map((item) => (item.id === updated.id ? updated : item)),
        );
        setError(null);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    },
    [],
  );

  const submit = useCallback(async () => {
    if (!prefix || !selectedProfile || !selectedDataset) return;
    setSubmitting(true);
    try {
      const job = await createWebODMJob({
        name: name.trim() || prefix.split("/").pop() || "WebODM task",
        input_prefix: prefix,
        platform:
          selectedDataset.platform === "UNKNOWN"
            ? undefined
            : selectedDataset.platform,
        profile: selectedProfile.key,
      });
      setJobs((current) => [job, ...current.filter((item) => item.id !== job.id)]);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setSubmitting(false);
    }
  }, [name, prefix, selectedDataset, selectedProfile]);

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
                  {item.prefix} · {item.platform} · {item.asset_count} originals
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
              {compatibleProfiles.map((item) => (
                <option key={item.key} value={item.key}>{item.title}</option>
              ))}
            </select>
          </label>

          <button
            disabled={submitting || !selectedDataset || !selectedProfile}
            onClick={() => void submit()}
            type="button"
          >
            {submitting ? "Queueing…" : "Start WebODM"}
          </button>
        </div>

        {selectedDataset ? (
          <div className="processingDataset">
            <span>Platform<b>{selectedDataset.platform}</b></span>
            <span>Images<b>{selectedWorkflow?.eligible_assets ?? 0}</b></span>
            <span>Input size<b>{bytes(selectedDataset.size_bytes)}</b></span>
            <span>Media<b>{selectedProfile?.media_kinds.join(" / ") ?? "—"}</b></span>
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

      <section className="panel thermogramCreate">
        <div className="panelHead">
          <div>
            <h2>M3T Thermogram</h2>
            <small>M3T radiometric R-JPEG processing · originals stay read-only</small>
          </div>
          <span>{thermogramDatasets.length} M3T datasets</span>
        </div>

        <div className="processingForm thermogramForm">
          <label>
            M3T dataset
            <select
              value={thermogramPrefix}
              onChange={(event) => setThermogramPrefix(event.target.value)}
            >
              {thermogramDatasets.length === 0 ? (
                <option value="">No complete M3T Wide/Thermal dataset</option>
              ) : thermogramDatasets.map((item) => (
                <option key={item.prefix} value={item.prefix}>
                  {item.prefix} · {item.asset_count} originals
                </option>
              ))}
            </select>
          </label>

          <label>
            Job name
            <input
              maxLength={255}
              onChange={(event) => setThermogramName(event.target.value)}
              value={thermogramName}
            />
          </label>

          <button
            disabled={thermogramSubmitting || !selectedThermogramDataset}
            onClick={() => void submitThermogram()}
            type="button"
          >
            {thermogramSubmitting ? "Creating…" : "Create M3T thermal job"}
          </button>
        </div>

        {selectedThermogramDataset ? (
          <div className="processingDataset">
            <span>Platform<b>M3T</b></span>
            <span>Complete pairs<b>{selectedThermogramWorkflow?.complete_groups ?? 0}</b></span>
            <span>Frozen files<b>{selectedThermogramWorkflow?.eligible_assets ?? 0}</b></span>
            <span>Media<b>WIDE / THERMAL</b></span>
          </div>
        ) : null}

        <div className="processingProfile thermogramProfile">
          <strong>M3T radiometric worker handoff</strong>
          <span>
            M3-Cloud freezes complete M3T Wide/Thermal pairs and SHA-256 hashes.
            The x86-64 thermal worker decodes the original DJI R-JPEG with DJI TSDK,
            writes Float32 °C TIFF + preview + provenance, and leaves all source
            images unchanged. The external/manual handoff remains usable as fallback.
          </span>
        </div>
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

              <div className="processingJobAudit">
                <a href={`/api/v1/processing/jobs/${encodeURIComponent(job.id)}/inputs/download`}>
                  Input manifest
                </a>
              </div>

              <div className="processingMetrics">
                <span>Progress<b>{percent(job.progress)}</b></span>
                <span>Images<b>{job.uploaded_count}/{job.image_count}</b></span>
                <span>Project<b>{job.remote_project_id ?? "—"}</b></span>
                <span>Task<b>{job.remote_task_id ?? "—"}</b></span>
                <span>Remote<b>{job.remote_status ?? "—"}</b></span>
                <span>Assets<b>{job.available_assets.length}</b></span>
              </div>

              {job.kind === "THERMOGRAM" ? (
                <div className="thermogramActions">
                  <a href={thermogramHandoffDownloadUrl(job.id)}>
                    Download worker handoff
                  </a>
                  <button
                    onClick={() => {
                      void fetchThermogramHandoff(job.id)
                        .then((handoff) =>
                          setHandoffs((current) => ({
                            ...current,
                            [job.id]: handoff,
                          })),
                        )
                        .catch((reason: unknown) =>
                          setError(
                            reason instanceof Error
                              ? reason.message
                              : String(reason),
                          ),
                        );
                    }}
                    type="button"
                  >
                    Show path
                  </button>
                  {job.status === "WAITING_EXTERNAL" ||
                  job.status === "FAILED_EXTERNAL" ? (
                    <button
                      onClick={() => void updateExternal(job, "RUNNING_EXTERNAL")}
                      type="button"
                    >
                      Mark running
                    </button>
                  ) : null}
                  {job.status === "RUNNING_EXTERNAL" ? (
                    <button
                      onClick={() => void updateExternal(job, "COMPLETED_EXTERNAL")}
                      type="button"
                    >
                      Mark completed
                    </button>
                  ) : null}
                  {["COMPLETED_EXTERNAL", "RESULT_IMPORT_FAILED"].includes(job.status) ? (
                    <>
                      <button
                        onClick={() => {
                          void fetchExternalResultStatus(job.id)
                            .then((value) =>
                              setExternalResults((current) => ({ ...current, [job.id]: value })),
                            )
                            .catch((reason: unknown) =>
                              setError(reason instanceof Error ? reason.message : String(reason)),
                            );
                        }}
                        type="button"
                      >
                        Result folder
                      </button>
                      <button
                        onClick={() => {
                          void importExternalResults(job.id)
                            .then((values) => {
                              setResults((current) => ({ ...current, [job.id]: values }));
                              return refresh();
                            })
                            .catch((reason: unknown) =>
                              setError(reason instanceof Error ? reason.message : String(reason)),
                            );
                        }}
                        type="button"
                      >
                        Import results
                      </button>
                    </>
                  ) : null}
                </div>
              ) : null}

              {externalResults[job.id] ? (
                <div className="thermogramPath">
                  <span>Result drop folder</span>
                  <code>{externalResults[job.id].drop_path}</code>
                  <small>
                    {externalResults[job.id].file_count} files detected
                  </small>
                </div>
              ) : null}

              {handoffs[job.id] ? (
                <div className="thermogramPath">
                  <span>M3T worker input</span>
                  <code>{handoffs[job.id].external_path}</code>
                  <small>
                    {handoffs[job.id].worker_contract} · {
                      handoffs[job.id].capture_group_count
                    } complete pairs · {handoffs[job.id].asset_count} frozen originals
                  </small>
                  <span>Result drop</span>
                  <code>{handoffs[job.id].result_drop_path}</code>
                </div>
              ) : null}

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
                    Map layers
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
          maps={maps}
          onSelect={setMapInfo}
          onClose={() => {
            setMapInfo(null);
            setMaps([]);
          }}
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
