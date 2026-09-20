import { useCallback, useEffect, useMemo, useState } from "react";

import {
  assignFlightSurvey,
  assignMediaDatasetSurvey,
  createProject,
  createSurvey,
  createSurveyFromDataset,
  fetchFlights,
  fetchMediaDatasets,
  fetchProcessingJobs,
  fetchProjects,
  fetchProjectSurveys,
  fetchSurveyLineage,
  processingResultDownloadUrl,
} from "./api";
import type {
  FlightSummary,
  MediaDataset,
  ProcessingJob,
  Project,
  Survey,
  SurveyLineage,
} from "./types";

function stamp(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function ProjectsView() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [surveys, setSurveys] = useState<Survey[]>([]);
  const [flights, setFlights] = useState<FlightSummary[]>([]);
  const [datasets, setDatasets] = useState<MediaDataset[]>([]);
  const [jobs, setJobs] = useState<ProcessingJob[]>([]);
  const [lineage, setLineage] = useState<SurveyLineage | null>(null);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [surveyId, setSurveyId] = useState<string | null>(null);
  const [projectName, setProjectName] = useState("");
  const [surveyName, setSurveyName] = useState("");
  const [surveyKind, setSurveyKind] = useState("MAPPING");
  const [datasetSeedId, setDatasetSeedId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const loadBase = useCallback(async () => {
    try {
      const [nextProjects, nextFlights, nextDatasets, nextJobs] =
        await Promise.all([
          fetchProjects(),
          fetchFlights(undefined, 500),
          fetchMediaDatasets(),
          fetchProcessingJobs(),
        ]);
      setProjects(nextProjects);
      setFlights(nextFlights);
      setDatasets(nextDatasets);
      setJobs(nextJobs);
      setProjectId((current) =>
        current && nextProjects.some((item) => item.id === current)
          ? current
          : nextProjects[0]?.id ?? null,
      );
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, []);

  useEffect(() => {
    void loadBase();
  }, [loadBase]);

  useEffect(() => {
    if (!projectId) {
      setSurveys([]);
      setSurveyId(null);
      return;
    }

    let cancelled = false;
    void fetchProjectSurveys(projectId)
      .then((next) => {
        if (cancelled) return;
        setSurveys(next);
        setSurveyId((current) =>
          current && next.some((item) => item.id === current)
            ? current
            : next[0]?.id ?? null,
        );
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [projectId]);

  const refreshSurveys = useCallback(async () => {
    if (!projectId) return;
    const next = await fetchProjectSurveys(projectId);
    setSurveys(next);
  }, [projectId]);

  const selectedSurvey =
    surveys.find((item) => item.id === surveyId) ?? null;

  useEffect(() => {
    if (!surveyId) {
      setLineage(null);
      return;
    }

    let cancelled = false;
    void fetchSurveyLineage(surveyId)
      .then((value) => {
        if (!cancelled) setLineage(value);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [surveyId]);

  const surveyFlights = useMemo(
    () => flights.filter((flight) => flight.survey_id === surveyId),
    [flights, surveyId],
  );
  const surveyDatasets = useMemo(
    () => datasets.filter((dataset) => dataset.survey_id === surveyId),
    [datasets, surveyId],
  );
  const surveyJobs = useMemo(
    () => jobs.filter((job) => job.survey_id === surveyId),
    [jobs, surveyId],
  );

  const unassignedFlights = useMemo(
    () => flights.filter((flight) => !flight.survey_id),
    [flights],
  );
  const unassignedDatasets = useMemo(
    () => datasets.filter((dataset) => dataset.id && !dataset.survey_id),
    [datasets],
  );

  const submitProject = async () => {
    const name = projectName.trim();
    if (!name) return;

    setBusy(true);
    try {
      const created = await createProject({ name });
      setProjectName("");
      await loadBase();
      setProjectId(created.id);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const submitSurveyFromDataset = async () => {
    if (!projectId || !datasetSeedId) return;

    setBusy(true);
    try {
      const created = await createSurveyFromDataset(projectId, datasetSeedId);
      setDatasetSeedId("");
      await Promise.all([loadBase(), refreshSurveys()]);
      setSurveyId(created.id);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const submitSurvey = async () => {
    if (!projectId) return;
    const name = surveyName.trim();
    if (!name) return;

    setBusy(true);
    try {
      const created = await createSurvey(projectId, {
        name,
        kind: surveyKind,
      });
      setSurveyName("");
      await refreshSurveys();
      setSurveyId(created.id);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const linkFlight = async (flightId: string, target: string | null) => {
    setBusy(true);
    try {
      await assignFlightSurvey(flightId, target);
      await Promise.all([loadBase(), refreshSurveys()]);
      if (surveyId) setLineage(await fetchSurveyLineage(surveyId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const linkDataset = async (datasetId: string, target: string | null) => {
    setBusy(true);
    try {
      await assignMediaDatasetSurvey(datasetId, target);
      await Promise.all([loadBase(), refreshSurveys()]);
      if (surveyId) setLineage(await fetchSurveyLineage(surveyId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="projectsView">
      {error ? <div className="projectsError">{error}</div> : null}

      <section className="projectsRail panel">
        <div className="panelHead">
          <div>
            <h2>Projects</h2>
            <small>Persistent operational workspaces</small>
          </div>
          <span>{projects.length}</span>
        </div>

        <div className="projectCreate">
          <input
            placeholder="New project"
            value={projectName}
            onChange={(event) => setProjectName(event.target.value)}
          />
          <button disabled={busy || !projectName.trim()} onClick={() => void submitProject()} type="button">
            Add
          </button>
        </div>

        <div className="projectList">
          {projects.map((project) => (
            <button
              className={project.id === projectId ? "projectItem selected" : "projectItem"}
              key={project.id}
              onClick={() => {
                setProjectId(project.id);
                setSurveyId(null);
              }}
              type="button"
            >
              <strong>{project.name}</strong>
              <small>{project.status} · {project.survey_count} surveys</small>
              <small>{stamp(project.updated_at)}</small>
            </button>
          ))}
          {projects.length === 0 ? (
            <div className="empty">Noch kein Project angelegt.</div>
          ) : null}
        </div>
      </section>

      <section className="surveysRail panel">
        <div className="panelHead">
          <div>
            <h2>Surveys</h2>
            <small>{projects.find((item) => item.id === projectId)?.name ?? "Project auswählen"}</small>
          </div>
          <span>{surveys.length}</span>
        </div>

        <div className="surveyCreate">
          <input
            disabled={!projectId}
            placeholder="New survey"
            value={surveyName}
            onChange={(event) => setSurveyName(event.target.value)}
          />
          <select
            disabled={!projectId}
            value={surveyKind}
            onChange={(event) => setSurveyKind(event.target.value)}
          >
            <option value="MAPPING">Mapping</option>
            <option value="THERMAL">Thermal</option>
            <option value="MULTISPECTRAL">Multispectral</option>
            <option value="INSPECTION">Inspection</option>
            <option value="GENERIC">Generic</option>
          </select>
          <button disabled={busy || !projectId || !surveyName.trim()} onClick={() => void submitSurvey()} type="button">
            Add
          </button>
        </div>

        <div className="surveyFromDataset">
          <label>
            Survey from dataset
            <select
              disabled={!projectId || busy || unassignedDatasets.length === 0}
              value={datasetSeedId}
              onChange={(event) => setDatasetSeedId(event.target.value)}
            >
              <option value="">Select unassigned dataset…</option>
              {unassignedDatasets.map((dataset) => (
                <option key={dataset.id as string} value={dataset.id as string}>
                  {dataset.platform} · {dataset.prefix}
                </option>
              ))}
            </select>
          </label>
          <button
            disabled={!projectId || !datasetSeedId || busy}
            onClick={() => void submitSurveyFromDataset()}
            type="button"
          >
            Create from dataset
          </button>
        </div>

        <div className="surveyList">
          {surveys.map((survey) => (
            <button
              className={survey.id === surveyId ? "surveyItem selected" : "surveyItem"}
              key={survey.id}
              onClick={() => setSurveyId(survey.id)}
              type="button"
            >
              <div>
                <strong>{survey.name}</strong>
                <span>{survey.kind}</span>
              </div>
              <small>
                {survey.flight_count} flights · {survey.dataset_count} datasets · {survey.processing_count} jobs
              </small>
            </button>
          ))}
        </div>
      </section>

      <section className="surveyWorkspace">
        {selectedSurvey ? (
          <>
            <div className="surveyTitle">
              <div>
                <h2>{selectedSurvey.name}</h2>
                <p>{selectedSurvey.kind} · {selectedSurvey.status}</p>
              </div>
              <span>{selectedSurvey.project_id}</span>
            </div>

            <div className="surveyLineageSummary">
              <span>Flights<b>{lineage?.flights.length ?? selectedSurvey.flight_count}</b></span>
              <span>Datasets<b>{lineage?.datasets.length ?? selectedSurvey.dataset_count}</b></span>
              <span>Processing<b>{lineage?.processing_jobs.length ?? selectedSurvey.processing_count}</b></span>
              <span>Results<b>{lineage?.processing_jobs.reduce((sum, job) => sum + job.results.length, 0) ?? 0}</b></span>
            </div>

            <div className="surveyColumns">
              <section className="panel surveyMemberPanel">
                <div className="panelHead">
                  <div><h2>Flights</h2><small>{surveyFlights.length} assigned</small></div>
                </div>
                <div className="surveyMembers">
                  {surveyFlights.map((flight) => (
                    <article key={flight.id}>
                      <div>
                        <strong>{flight.aircraft_sn}</strong>
                        <small>{stamp(flight.started_at)}</small>
                      </div>
                      <button disabled={busy} onClick={() => void linkFlight(flight.id, null)} type="button">Remove</button>
                    </article>
                  ))}
                </div>
                <label className="surveyAssign">
                  Add flight
                  <select
                    disabled={busy || unassignedFlights.length === 0}
                    defaultValue=""
                    onChange={(event) => {
                      const value = event.target.value;
                      if (value) void linkFlight(value, selectedSurvey.id);
                      event.currentTarget.value = "";
                    }}
                  >
                    <option value="">Select…</option>
                    {unassignedFlights.map((flight) => (
                      <option key={flight.id} value={flight.id}>
                        {flight.aircraft_sn} · {stamp(flight.started_at)}
                      </option>
                    ))}
                  </select>
                </label>
              </section>

              <section className="panel surveyMemberPanel">
                <div className="panelHead">
                  <div><h2>Media datasets</h2><small>{surveyDatasets.length} assigned</small></div>
                </div>
                <div className="surveyMembers">
                  {surveyDatasets.map((dataset) => (
                    <article key={dataset.id ?? dataset.prefix}>
                      <div>
                        <strong>{dataset.prefix}</strong>
                        <small>{dataset.platform} · {dataset.asset_count} assets</small>
                      </div>
                      {dataset.id ? (
                        <button disabled={busy} onClick={() => void linkDataset(dataset.id!, null)} type="button">Remove</button>
                      ) : null}
                    </article>
                  ))}
                </div>
                <label className="surveyAssign">
                  Add dataset
                  <select
                    disabled={busy || unassignedDatasets.length === 0}
                    defaultValue=""
                    onChange={(event) => {
                      const value = event.target.value;
                      if (value) void linkDataset(value, selectedSurvey.id);
                      event.currentTarget.value = "";
                    }}
                  >
                    <option value="">Select…</option>
                    {unassignedDatasets.map((dataset) => (
                      <option key={dataset.id as string} value={dataset.id as string}>
                        {dataset.platform} · {dataset.prefix}
                      </option>
                    ))}
                  </select>
                </label>
              </section>

              <section className="panel surveyMemberPanel">
                <div className="panelHead">
                  <div><h2>Processing</h2><small>{surveyJobs.length} inherited</small></div>
                </div>
                <div className="surveyMembers">
                  {(lineage?.processing_jobs ?? []).map((job) => (
                    <article className="surveyProcessingItem" key={job.id}>
                      <div>
                        <strong>{job.name}</strong>
                        <small>{job.kind} · {job.status}</small>
                        {job.results.length > 0 ? (
                          <div className="surveyResults">
                            {job.results.map((result) => (
                              <a
                                href={processingResultDownloadUrl(job.id, result.id)}
                                key={result.id}
                              >
                                {result.asset_name}
                              </a>
                            ))}
                          </div>
                        ) : null}
                      </div>
                      <span>{job.platform ?? "—"}</span>
                    </article>
                  ))}
                  {(lineage?.processing_jobs.length ?? 0) === 0 ? (
                    <div className="empty">Neue Jobs erben den Survey vom Dataset.</div>
                  ) : null}
                </div>
              </section>
            </div>
          </>
        ) : (
          <div className="placeholder">
            <h2>Survey auswählen</h2>
            <p>Flights, Media-Datasets und Processing-Jobs werden hier zusammengeführt.</p>
          </div>
        )}
      </section>
    </div>
  );
}
