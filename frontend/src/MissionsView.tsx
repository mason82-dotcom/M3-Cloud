import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map, StyleSpecification } from "maplibre-gl";
import type { FeatureCollection, LineString, Point } from "geojson";

import {
  createMission,
  createMissionDeployment,
  fetchMissionDeployments,
  fetchMissionPreflight,
  fetchMissionRevisions,
  fetchMissions,
  fetchProjects,
  fetchProjectSurveys,
  fetchVehicles,
  updateMission,
  missionDeploymentDownloadUrl,
  missionRevisionDownloadUrl,
} from "./api";
import type {
  Mission,
  MissionDeployment,
  MissionPlanItem,
  MissionPreflight,
  MissionRevision,
  Project,
  Survey,
  Vehicle,
} from "./types";

const ROUTE_SOURCE = "mission-route";
const ROUTE_LAYER = "mission-route-line";
const POINT_SOURCE = "mission-waypoints";
const POINT_LAYER = "mission-waypoints-layer";

const PRIMARY_STYLE =
  import.meta.env.VITE_MAP_STYLE_URL ??
  "https://demotiles.maplibre.org/style.json";

const FALLBACK_TILE_URL =
  import.meta.env.VITE_MAP_FALLBACK_TILE_URL ??
  "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

const FALLBACK_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    fallback: {
      type: "raster",
      tiles: [FALLBACK_TILE_URL],
      tileSize: 256,
      attribution: "© OpenStreetMap contributors",
      maxzoom: 19,
    },
  },
  layers: [
    {
      id: "fallback-background",
      type: "background",
      paint: { "background-color": "#151a20" },
    },
    {
      id: "fallback-raster",
      type: "raster",
      source: "fallback",
    },
  ],
};

function routeData(items: MissionPlanItem[]): FeatureCollection<LineString> {
  const coordinates = items
    .filter((item) => item.command === 16)
    .map((item) => [item.longitude_deg, item.latitude_deg]);

  return {
    type: "FeatureCollection",
    features:
      coordinates.length >= 2
        ? [{
            type: "Feature",
            geometry: { type: "LineString", coordinates },
            properties: {},
          }]
        : [],
  };
}

function waypointData(items: MissionPlanItem[]): FeatureCollection<Point> {
  return {
    type: "FeatureCollection",
    features: items
      .filter((item) => item.command === 16)
      .map((item) => ({
        type: "Feature",
        geometry: {
          type: "Point",
          coordinates: [item.longitude_deg, item.latitude_deg],
        },
        properties: {
          seq: item.seq,
          altitude_m: item.altitude_m,
        },
      })),
  };
}

function MissionMap({ items }: { items: MissionPlanItem[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const itemsRef = useRef(items);
  const [fallback, setFallback] = useState(false);
  itemsRef.current = items;

  const route = useMemo(() => routeData(items), [items]);
  const points = useMemo(() => waypointData(items), [items]);
  const routeRef = useRef(route);
  const pointsRef = useRef(points);
  routeRef.current = route;
  pointsRef.current = points;

  const fit = useCallback((map: Map, current: MissionPlanItem[]) => {
    const coordinates = current
      .filter((item) => item.command === 16)
      .map((item) => [item.longitude_deg, item.latitude_deg] as [number, number])
      .filter(([lon, lat]) =>
        Number.isFinite(lon) &&
        Number.isFinite(lat) &&
        lon >= -180 &&
        lon <= 180 &&
        lat >= -90 &&
        lat <= 90 &&
        !(lon === 0 && lat === 0),
      );

    if (coordinates.length === 0) return;
    if (coordinates.length === 1) {
      map.flyTo({ center: coordinates[0], zoom: 16, essential: true });
      return;
    }

    const bounds = coordinates.reduce(
      (value, coordinate) => value.extend(coordinate),
      new maplibregl.LngLatBounds(coordinates[0], coordinates[0]),
    );
    map.fitBounds(bounds, { padding: 45, maxZoom: 17, duration: 500 });
  }, []);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    let styleLoaded = false;
    let fallbackActivated = false;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: PRIMARY_STYLE,
      center: [8.5, 49.1],
      zoom: 7,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");

    map.on("style.load", () => {
      styleLoaded = true;
      map.addSource(ROUTE_SOURCE, {
        type: "geojson",
        data: routeRef.current,
      });
      map.addLayer({
        id: ROUTE_LAYER,
        type: "line",
        source: ROUTE_SOURCE,
        paint: {
          "line-width": 4,
          "line-opacity": 0.9,
          "line-color": "#4fc3b6",
        },
      });
      map.addSource(POINT_SOURCE, {
        type: "geojson",
        data: pointsRef.current,
      });
      map.addLayer({
        id: POINT_LAYER,
        type: "circle",
        source: POINT_SOURCE,
        paint: {
          "circle-radius": 7,
          "circle-stroke-width": 2,
          "circle-stroke-color": "#ffffff",
          "circle-color": "#69a9ff",
        },
      });
      fit(map, itemsRef.current);
    });

    map.on("error", () => {
      if (styleLoaded || fallbackActivated) return;
      fallbackActivated = true;
      setFallback(true);
      map.setStyle(FALLBACK_STYLE);
    });

    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, [fit]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    (map.getSource(ROUTE_SOURCE) as GeoJSONSource | undefined)?.setData(route);
    (map.getSource(POINT_SOURCE) as GeoJSONSource | undefined)?.setData(points);
    fit(map, items);
  }, [fit, items, points, route]);

  return (
    <div className="missionMapShell">
      {fallback ? <div className="map-fallback-badge">MAP FALLBACK</div> : null}
      <div className="missionMap" ref={containerRef} />
    </div>
  );
}

function nextWaypoint(
  items: MissionPlanItem[],
  vehicle: Vehicle | undefined,
): MissionPlanItem {
  const latitude = vehicle?.telemetry?.latitude;
  const longitude = vehicle?.telemetry?.longitude;

  return {
    seq: items.length,
    frame: 6,
    command: 16,
    param1: 0,
    param2: null,
    param3: 0,
    param4: null,
    latitude_deg: typeof latitude === "number" ? latitude : 0,
    longitude_deg: typeof longitude === "number" ? longitude : 0,
    altitude_m: 50,
    autocontinue: true,
  };
}

function renumber(items: MissionPlanItem[]): MissionPlanItem[] {
  return items.map((item, seq) => ({ ...item, seq }));
}

export function MissionsView() {
  const [missions, setMissions] = useState<Mission[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [surveys, setSurveys] = useState<Survey[]>([]);
  const [vehicles, setVehicles] = useState<Vehicle[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [revisions, setRevisions] = useState<MissionRevision[]>([]);
  const [deployments, setDeployments] = useState<MissionDeployment[]>([]);
  const [preflight, setPreflight] = useState<MissionPreflight | null>(null);
  const [draftItems, setDraftItems] = useState<MissionPlanItem[]>([]);
  const [newName, setNewName] = useState("");
  const [newSurveyId, setNewSurveyId] = useState("");
  const [newAircraftSn, setNewAircraftSn] = useState("");
  const [newExecutor, setNewExecutor] =
    useState<"DJI_NATIVE" | "ONBOARD" | "">("DJI_NATIVE");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [nextMissions, nextProjects, nextVehicles] = await Promise.all([
        fetchMissions(),
        fetchProjects(),
        fetchVehicles(),
      ]);
      const surveyLists = await Promise.all(
        nextProjects.map((project) => fetchProjectSurveys(project.id)),
      );
      const nextSurveys = surveyLists.flat();

      setMissions(nextMissions);
      setProjects(nextProjects);
      setSurveys(nextSurveys);
      setVehicles(nextVehicles);
      setSelectedId((current) =>
        current && nextMissions.some((mission) => mission.id === current)
          ? current
          : nextMissions[0]?.id ?? null,
      );
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const selected =
    missions.find((mission) => mission.id === selectedId) ?? null;

  useEffect(() => {
    setDraftItems(
      selected
        ? selected.plan.items.map((item) => ({ ...item, frame: item.frame ?? 6 }))
        : [],
    );
    if (!selectedId) {
      setRevisions([]);
      setDeployments([]);
      setPreflight(null);
      return;
    }
    let cancelled = false;
    void Promise.all([
      fetchMissionRevisions(selectedId),
      fetchMissionDeployments(selectedId),
      fetchMissionPreflight(selectedId),
    ])
      .then(([items, sealed, report]) => {
        if (!cancelled) {
          setRevisions(items);
          setDeployments(sealed);
          setPreflight(report);
        }
      })
      .catch(() => {
        if (!cancelled) {
          setRevisions([]);
          setDeployments([]);
          setPreflight(null);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [selectedId, selected?.plan_version]);

  const surveyProject = useMemo(
    () =>
      Object.fromEntries(
        surveys.map((survey) => [
          survey.id,
          projects.find((project) => project.id === survey.project_id)?.name ?? "Project",
        ]),
      ),
    [projects, surveys],
  );

  const selectedVehicle = vehicles.find(
    (vehicle) => vehicle.sn === selected?.aircraft_sn,
  );

  const sealHandoff = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      const created = await createMissionDeployment(selected.id);
      setDeployments((current) => [...current, created]);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const create = async () => {
    const name = newName.trim();
    if (!name) return;
    setBusy(true);
    try {
      const mission = await createMission({
        name,
        survey_id: newSurveyId || null,
        aircraft_sn: newAircraftSn || null,
        preferred_executor: newExecutor || null,
        items: [],
      });
      setNewName("");
      setMissions((current) => [mission, ...current]);
      setSelectedId(mission.id);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const savePlan = async () => {
    if (!selected) return;
    setBusy(true);
    try {
      const updated = await updateMission(selected.id, { items: renumber(draftItems) });
      setMissions((current) =>
        current.map((mission) => mission.id === updated.id ? updated : mission),
      );
      setDraftItems(updated.plan.items);
      const [nextRevisions, nextPreflight] = await Promise.all([
        fetchMissionRevisions(updated.id),
        fetchMissionPreflight(updated.id),
      ]);
      setRevisions(nextRevisions);
      setPreflight(nextPreflight);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const patchMission = async (
    input: Parameters<typeof updateMission>[1],
  ) => {
    if (!selected) return;
    setBusy(true);
    try {
      const updated = await updateMission(selected.id, input);
      setMissions((current) =>
        current.map((mission) => mission.id === updated.id ? updated : mission),
      );
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="missionsView">
      {error ? <div className="missionsError">{error}</div> : null}

      <aside className="missionRail panel">
        <div className="panelHead">
          <div>
            <h2>Mission plans</h2>
            <small>Persistent planning only</small>
          </div>
          <span>{missions.length}</span>
        </div>

        <div className="missionCreate">
          <input
            placeholder="Mission name"
            value={newName}
            onChange={(event) => setNewName(event.target.value)}
          />
          <select
            value={newSurveyId}
            onChange={(event) => setNewSurveyId(event.target.value)}
          >
            <option value="">No survey</option>
            {surveys.map((survey) => (
              <option key={survey.id} value={survey.id}>
                {surveyProject[survey.id]} · {survey.name}
              </option>
            ))}
          </select>
          <select
            value={newAircraftSn}
            onChange={(event) => setNewAircraftSn(event.target.value)}
          >
            <option value="">No aircraft</option>
            {vehicles.map((vehicle) => (
              <option key={vehicle.sn} value={vehicle.sn}>
                {vehicle.model} · {vehicle.sn}
              </option>
            ))}
          </select>
          <select
            value={newExecutor}
            onChange={(event) =>
              setNewExecutor(event.target.value as "DJI_NATIVE" | "ONBOARD" | "")
            }
          >
            <option value="">Executor unspecified</option>
            <option value="DJI_NATIVE">DJI native preference</option>
            <option value="ONBOARD">Lyrebird onboard preference</option>
          </select>
          <button disabled={busy || !newName.trim()} onClick={() => void create()} type="button">
            Create mission
          </button>
        </div>

        <div className="missionList">
          {missions.map((mission) => (
            <button
              className={mission.id === selectedId ? "missionItem selected" : "missionItem"}
              key={mission.id}
              onClick={() => setSelectedId(mission.id)}
              type="button"
            >
              <div>
                <strong>{mission.name}</strong>
                <span>{mission.status}</span>
              </div>
              <small>
                {mission.item_count} items · v{mission.plan_version} · {mission.aircraft_sn ?? "no aircraft"}
              </small>
              {mission.runtime?.available ? (
                <small className="missionRuntimeSmall">
                  Aircraft runtime: {mission.runtime.state} · seq {mission.runtime.current_seq ?? "—"}
                </small>
              ) : null}
            </button>
          ))}
          {missions.length === 0 ? <div className="empty">Noch keine Mission angelegt.</div> : null}
        </div>
      </aside>

      <section className="missionWorkspace">
        {selected ? (
          <>
            <div className="missionSafetyBanner">
              <strong>Planning / observation only</strong>
              <span>
                M3-Cloud exposes no upload, start, pause, resume, land or abort action in R6.1.
              </span>
            </div>

            <div className="missionHeader">
              <div>
                <h2>{selected.name}</h2>
                <p>
                  {selected.kind} · {selected.status} · SHA {selected.plan_sha256.slice(0, 12)}…
                </p>
              </div>
              <div className="missionHeaderActions">
                <button
                  disabled={busy || selected.status === "ARCHIVED"}
                  onClick={() => void patchMission({ status: "ARCHIVED" })}
                  type="button"
                >
                  Archive
                </button>
              </div>
            </div>

            <div className="missionGrid">
              <MissionMap items={draftItems} />

              <aside className="panel missionInspector">
                <div className="panelHead">
                  <div><h2>Plan</h2><small>Association and compatibility</small></div>
                </div>

                <label>
                  Survey
                  <select
                    disabled={busy}
                    value={selected.survey_id ?? ""}
                    onChange={(event) =>
                      void patchMission({ survey_id: event.target.value || null })
                    }
                  >
                    <option value="">Unassigned</option>
                    {surveys.map((survey) => (
                      <option key={survey.id} value={survey.id}>
                        {surveyProject[survey.id]} · {survey.name}
                      </option>
                    ))}
                  </select>
                </label>

                <label>
                  Aircraft
                  <select
                    disabled={busy}
                    value={selected.aircraft_sn ?? ""}
                    onChange={(event) =>
                      void patchMission({ aircraft_sn: event.target.value || null })
                    }
                  >
                    <option value="">Unassigned</option>
                    {vehicles.map((vehicle) => (
                      <option key={vehicle.sn} value={vehicle.sn}>
                        {vehicle.model} · {vehicle.sn}
                      </option>
                    ))}
                  </select>
                </label>

                <label>
                  Executor preference
                  <select
                    disabled={busy}
                    value={selected.preferred_executor ?? ""}
                    onChange={(event) =>
                      void patchMission({
                        preferred_executor:
                          (event.target.value || null) as "DJI_NATIVE" | "ONBOARD" | null,
                      })
                    }
                  >
                    <option value="">Unspecified</option>
                    <option value="DJI_NATIVE">DJI native</option>
                    <option value="ONBOARD">Lyrebird onboard</option>
                  </select>
                </label>

                <dl className="missionFacts">
                  <dt>Stored plan</dt><dd>{selected.item_count} items</dd>
                  <dt>Plan version</dt><dd>{selected.plan_version}</dd>
                  <dt>Lyrebird upload shape</dt>
                  <dd>
                    {selected.compatibility.lyrebird_mavlink_upload_compatible
                      ? "wire-ready"
                      : "not wire-ready"}
                  </dd>
                  <dt>MAVLink frame</dt>
                  <dd>
                    {selected.compatibility.wire_ready
                      ? "explicit per item"
                      : "missing/unsupported"}
                  </dd>
                  <dt>M3-Cloud execute</dt><dd>disabled</dd>
                  <dt>DJI-native execution</dt><dd>not asserted</dd>
                </dl>

                <div className="missionRevisionBox">
                  <strong>Immutable revisions</strong>
                  <div>
                    {revisions.map((revision) => (
                      <a
                        href={missionRevisionDownloadUrl(selected.id, revision.version)}
                        key={revision.version}
                      >
                        v{revision.version} · {revision.plan_sha256.slice(0, 8)}
                      </a>
                    ))}
                  </div>
                </div>

                <div className="missionRevisionBox">
                  <div className="missionHandoffHead">
                    <strong>Sealed handoff packages</strong>
                    <button
                      disabled={
                        busy ||
                        selected.status !== "READY" ||
                        preflight?.checks_passed !== true ||
                        !selected.compatibility.lyrebird_mavlink_upload_compatible
                      }
                      onClick={() => void sealHandoff()}
                      type="button"
                    >
                      Seal current revision
                    </button>
                  </div>
                  <div>
                    {deployments.map((deployment) => (
                      <a
                        href={missionDeploymentDownloadUrl(selected.id, deployment.id)}
                        key={deployment.id}
                      >
                        v{deployment.revision_version} · {deployment.package_sha256.slice(0, 8)}
                        {deployment.package.wire ? ` · ${deployment.package.wire.items.length} wire items` : ""}
                      </a>
                    ))}
                  </div>
                  <small>
                    Audit/handoff only: package creation never uploads or starts the aircraft.
                  </small>
                </div>

                <div className="missionPreflightBox">
                  <div>
                    <strong>Preflight report</strong>
                    <span className={preflight?.checks_passed ? "preflightPass" : "preflightBlock"}>
                      {preflight ? (preflight.checks_passed ? "CHECKS PASS" : "BLOCKED") : "UNAVAILABLE"}
                    </span>
                  </div>
                  {preflight?.checks.map((check) => (
                    <article className={`preflightCheck ${check.level.toLowerCase()}`} key={check.code}>
                      <b>{check.level}</b>
                      <span>{check.message}</span>
                    </article>
                  ))}
                  <small>Execution from M3-Cloud remains disabled regardless of this report.</small>
                </div>

                <div className="missionRuntimeBox">
                  <strong>Observed aircraft runtime</strong>
                  {selected.runtime ? (
                    <>
                      <span>State <b>{selected.runtime.state}</b></span>
                      <span>Current seq <b>{selected.runtime.current_seq ?? "—"}</b></span>
                      <span>Mission ID <b>{selected.runtime.mission_id ?? "—"}</b></span>
                      <span>Reached seq <b>{selected.runtime.waypoint_reached_seq ?? "—"}</b></span>
                      <small>
                        Runtime plan identity is {selected.runtime.runtime_plan_identity}
                        {selected.runtime.linked_to_persisted_plan
                          ? ` · sealed v${selected.runtime.revision_version ?? "?"}`
                          : " · not matched to a sealed handoff"}.
                      </small>
                    </>
                  ) : (
                    <small>
                      No mission runtime currently observed for the assigned aircraft.
                    </small>
                  )}
                </div>

                {selectedVehicle ? (
                  <small className="missionVehicleHint">
                    {selectedVehicle.online ? "Aircraft online" : "Aircraft offline"} · {selectedVehicle.model}
                  </small>
                ) : null}
              </aside>
            </div>

            <section className="panel missionEditor">
              <div className="panelHead">
                <div>
                  <h2>Waypoint editor</h2>
                  <small>MAV_CMD_NAV_WAYPOINT only in this UI</small>
                </div>
                <div className="missionEditorActions">
                  <button
                    disabled={busy || selected.status === "ARCHIVED"}
                    onClick={() =>
                      setDraftItems((current) => [
                        ...current,
                        nextWaypoint(current, selectedVehicle),
                      ])
                    }
                    type="button"
                  >
                    Add waypoint
                  </button>
                  <button
                    disabled={busy || selected.status === "ARCHIVED"}
                    onClick={() => void savePlan()}
                    type="button"
                  >
                    Save plan
                  </button>
                </div>
              </div>

              <div className="missionTableWrap">
                <table className="missionTable">
                  <thead>
                    <tr>
                      <th>#</th>
                      <th>Frame</th>
                      <th>Latitude</th>
                      <th>Longitude</th>
                      <th>Altitude m</th>
                      <th>Yaw °</th>
                      <th>Hold s</th>
                      <th />
                    </tr>
                  </thead>
                  <tbody>
                    {draftItems.map((item, index) => (
                      <tr key={`${index}:${item.seq}`}>
                        <td>{index}</td>
                        <td>
                          <select
                            disabled={selected.status === "ARCHIVED"}
                            value={item.frame ?? 6}
                            onChange={(event) => {
                              const frame = Number(event.target.value);
                              setDraftItems((current) =>
                                current.map((candidate, candidateIndex) =>
                                  candidateIndex === index
                                    ? { ...candidate, frame }
                                    : candidate,
                                ),
                              );
                            }}
                          >
                            <option value={6}>REL_ALT_INT (6)</option>
                            <option value={3}>REL_ALT (3)</option>
                          </select>
                        </td>
                        {([
                          ["latitude_deg", item.latitude_deg],
                          ["longitude_deg", item.longitude_deg],
                          ["altitude_m", item.altitude_m],
                          ["param4", item.param4 ?? ""],
                          ["param1", item.param1 ?? 0],
                        ] as const).map(([field, value]) => (
                          <td key={field}>
                            <input
                              disabled={selected.status === "ARCHIVED"}
                              step="any"
                              type="number"
                              value={value}
                              onChange={(event) => {
                                const raw = event.target.value;
                                setDraftItems((current) =>
                                  current.map((candidate, candidateIndex) =>
                                    candidateIndex === index
                                      ? {
                                          ...candidate,
                                          [field]:
                                            raw === "" && field === "param4"
                                              ? null
                                              : Number(raw),
                                        }
                                      : candidate,
                                  ),
                                );
                              }}
                            />
                          </td>
                        ))}
                        <td>
                          <button
                            disabled={busy || selected.status === "ARCHIVED"}
                            onClick={() =>
                              setDraftItems((current) =>
                                renumber(current.filter((_, currentIndex) => currentIndex !== index)),
                              )
                            }
                            type="button"
                          >
                            Remove
                          </button>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {draftItems.length === 0 ? (
                  <div className="empty">Add waypoints to make the mission READY.</div>
                ) : null}
              </div>
            </section>
          </>
        ) : (
          <div className="placeholder">
            <h2>Mission auswählen</h2>
            <p>Persistente Wayline-Planung und passive Aircraft-Runtime-Anzeige.</p>
          </div>
        )}
      </section>
    </div>
  );
}
