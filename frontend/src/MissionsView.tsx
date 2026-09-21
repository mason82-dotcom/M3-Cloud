import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map, StyleSpecification } from "maplibre-gl";
import type { FeatureCollection, LineString, Point, Polygon } from "geojson";

import {
  createMission,
  createMissionDeployment,
  fetchMissionDeployments,
  fetchMissionPlannerProfiles,
  fetchMissionPreflight,
  fetchMissionRevisions,
  fetchMissions,
  fetchProjects,
  fetchProjectSurveys,
  fetchVehicles,
  updateMission,
  uploadMissionDeployment,
  missionDeploymentDownloadUrl,
  missionRevisionDownloadUrl,
  previewMissionGrid,
} from "./api";
import type {
  Mission,
  MissionDeployment,
  MissionGridPreview,
  MissionPlannerPoint,
  MissionPlannerProfile,
  MissionPlanningContext,
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
const PLANNER_AREA_SOURCE = "mission-planner-area";
const PLANNER_AREA_FILL = "mission-planner-area-fill";
const PLANNER_AREA_LINE = "mission-planner-area-line";
const PLANNER_POINT_SOURCE = "mission-planner-points";
const PLANNER_POINT_LAYER = "mission-planner-points-layer";
const PLANNER_REFERENCE_SOURCE = "mission-planner-reference";
const PLANNER_REFERENCE_LAYER = "mission-planner-reference-layer";
const PLANNER_TRANSIT_SOURCE = "mission-planner-transit";
const PLANNER_TRANSIT_LAYER = "mission-planner-transit-layer";

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

function plannerAreaData(
  points: MissionPlannerPoint[],
): FeatureCollection<Polygon> {
  if (points.length < 3) {
    return { type: "FeatureCollection", features: [] };
  }
  const coordinates = points.map((point) => [
    point.longitude_deg,
    point.latitude_deg,
  ]);
  coordinates.push([...coordinates[0]]);
  return {
    type: "FeatureCollection",
    features: [{
      type: "Feature",
      geometry: { type: "Polygon", coordinates: [coordinates] },
      properties: {},
    }],
  };
}

function plannerPointData(
  points: MissionPlannerPoint[],
): FeatureCollection<Point> {
  return {
    type: "FeatureCollection",
    features: points.map((point, index) => ({
      type: "Feature",
      geometry: {
        type: "Point",
        coordinates: [point.longitude_deg, point.latitude_deg],
      },
      properties: { index: index + 1 },
    })),
  };
}

function plannerReferenceData(
  reference: MissionPlannerPoint | null,
): FeatureCollection<Point> {
  return {
    type: "FeatureCollection",
    features: reference
      ? [{
          type: "Feature",
          geometry: {
            type: "Point",
            coordinates: [reference.longitude_deg, reference.latitude_deg],
          },
          properties: {},
        }]
      : [],
  };
}

function plannerTransitData(
  items: MissionPlanItem[],
  reference: MissionPlannerPoint | null,
  returnToReference: boolean,
): FeatureCollection<LineString> {
  if (!reference) return { type: "FeatureCollection", features: [] };
  const waypoints = items
    .filter((item) => item.command === 16)
    .map((item) => [item.longitude_deg, item.latitude_deg]);

  if (waypoints.length === 0) {
    return { type: "FeatureCollection", features: [] };
  }

  const origin = [reference.longitude_deg, reference.latitude_deg];
  const features: FeatureCollection<LineString>["features"] = [{
    type: "Feature",
    geometry: { type: "LineString", coordinates: [origin, waypoints[0]] },
    properties: { leg: "ingress" },
  }];
  if (returnToReference) {
    features.push({
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [waypoints[waypoints.length - 1], origin],
      },
      properties: { leg: "return" },
    });
  }
  return { type: "FeatureCollection", features };
}

function vehiclePlatform(vehicle: Vehicle | undefined): "M3E" | "M3T" | "M3M" | null {
  const payload = vehicle?.telemetry?.payload?.platform?.toUpperCase();
  if (payload === "M3E" || payload === "M3T" || payload === "M3M") return payload;
  const model = vehicle?.model?.trim().toUpperCase();
  if (model === "M3E" || model === "MAVIC 3E" || model === "MAVIC 3 ENTERPRISE") return "M3E";
  if (model === "M3T" || model === "MAVIC 3T" || model === "MAVIC 3 THERMAL") return "M3T";
  if (model === "M3M" || model === "MAVIC 3M" || model === "MAVIC 3 MULTISPECTRAL") return "M3M";
  return null;
}

function plannerStartReference(vehicle: Vehicle | undefined): MissionPlannerPoint | null {
  const validPoint = (
    latitude: number | null | undefined,
    longitude: number | null | undefined,
  ): MissionPlannerPoint | null =>
    typeof latitude === "number" &&
    Number.isFinite(latitude) &&
    latitude >= -90 &&
    latitude <= 90 &&
    typeof longitude === "number" &&
    Number.isFinite(longitude) &&
    longitude >= -180 &&
    longitude <= 180
      ? { latitude_deg: latitude, longitude_deg: longitude }
      : null;

  const home = vehicle?.telemetry?.aircraft_state?.home;
  return (
    validPoint(home?.latitude, home?.longitude) ??
    validPoint(vehicle?.telemetry?.latitude, vehicle?.telemetry?.longitude)
  );
}

function missionCommandLabel(command: number): string {
  const names: Record<number, string> = {
    16: "WAYPOINT",
    20: "RTL",
    21: "LAND",
    22: "TAKEOFF",
    178: "CHANGE_SPEED",
    206: "CAM_TRIGG_DIST",
    1000: "GIMBAL_PITCHYAW",
  };
  return names[command] ?? String(command);
}

function MissionMap({
  items,
  plannerPolygon,
  plannerDrawing,
  plannerReference,
  plannerReturnToReference,
  onPlannerClick,
}: {
  items: MissionPlanItem[];
  plannerPolygon: MissionPlannerPoint[];
  plannerDrawing: boolean;
  plannerReference: MissionPlannerPoint | null;
  plannerReturnToReference: boolean;
  onPlannerClick?: (point: MissionPlannerPoint) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const itemsRef = useRef(items);
  const plannerClickRef = useRef(onPlannerClick);
  const [fallback, setFallback] = useState(false);
  itemsRef.current = items;
  plannerClickRef.current = onPlannerClick;

  const route = useMemo(() => routeData(items), [items]);
  const points = useMemo(() => waypointData(items), [items]);
  const plannerArea = useMemo(() => plannerAreaData(plannerPolygon), [plannerPolygon]);
  const plannerPoints = useMemo(() => plannerPointData(plannerPolygon), [plannerPolygon]);
  const plannerReferencePoint = useMemo(
    () => plannerReferenceData(plannerReference),
    [plannerReference],
  );
  const plannerTransit = useMemo(
    () => plannerTransitData(items, plannerReference, plannerReturnToReference),
    [items, plannerReference, plannerReturnToReference],
  );
  const routeRef = useRef(route);
  const pointsRef = useRef(points);
  const plannerAreaRef = useRef(plannerArea);
  const plannerPointsRef = useRef(plannerPoints);
  const plannerReferenceRef = useRef(plannerReferencePoint);
  const plannerTransitRef = useRef(plannerTransit);
  const plannerReferenceValueRef = useRef(plannerReference);
  routeRef.current = route;
  pointsRef.current = points;
  plannerAreaRef.current = plannerArea;
  plannerPointsRef.current = plannerPoints;
  plannerReferenceRef.current = plannerReferencePoint;
  plannerTransitRef.current = plannerTransit;
  plannerReferenceValueRef.current = plannerReference;

  const fit = useCallback((
    map: Map,
    current: MissionPlanItem[],
    reference: MissionPlannerPoint | null,
  ) => {
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
    if (reference) {
      coordinates.push([reference.longitude_deg, reference.latitude_deg]);
    }

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
      map.addSource(PLANNER_AREA_SOURCE, {
        type: "geojson",
        data: plannerAreaRef.current,
      });
      map.addLayer({
        id: PLANNER_AREA_FILL,
        type: "fill",
        source: PLANNER_AREA_SOURCE,
        paint: {
          "fill-color": "#e8a93b",
          "fill-opacity": 0.14,
        },
      });
      map.addLayer({
        id: PLANNER_AREA_LINE,
        type: "line",
        source: PLANNER_AREA_SOURCE,
        paint: {
          "line-color": "#e8a93b",
          "line-width": 2,
          "line-dasharray": [2, 1.5],
        },
      });
      map.addSource(PLANNER_TRANSIT_SOURCE, {
        type: "geojson",
        data: plannerTransitRef.current,
      });
      map.addLayer({
        id: PLANNER_TRANSIT_LAYER,
        type: "line",
        source: PLANNER_TRANSIT_SOURCE,
        paint: {
          "line-width": 2,
          "line-opacity": 0.75,
          "line-color": "#b7c4d4",
          "line-dasharray": [2, 2],
        },
      });
      map.addSource(PLANNER_REFERENCE_SOURCE, {
        type: "geojson",
        data: plannerReferenceRef.current,
      });
      map.addLayer({
        id: PLANNER_REFERENCE_LAYER,
        type: "circle",
        source: PLANNER_REFERENCE_SOURCE,
        paint: {
          "circle-radius": 8,
          "circle-stroke-width": 2,
          "circle-stroke-color": "#ffffff",
          "circle-color": "#ffb74d",
        },
      });
      map.addSource(PLANNER_POINT_SOURCE, {
        type: "geojson",
        data: plannerPointsRef.current,
      });
      map.addLayer({
        id: PLANNER_POINT_LAYER,
        type: "circle",
        source: PLANNER_POINT_SOURCE,
        paint: {
          "circle-radius": 5,
          "circle-stroke-width": 1.5,
          "circle-stroke-color": "#1a1206",
          "circle-color": "#e8a93b",
        },
      });
      fit(map, itemsRef.current, plannerReferenceValueRef.current);
    });

    map.on("click", (event) => {
      plannerClickRef.current?.({
        latitude_deg: event.lngLat.lat,
        longitude_deg: event.lngLat.lng,
      });
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
    (map.getSource(PLANNER_AREA_SOURCE) as GeoJSONSource | undefined)?.setData(plannerArea);
    (map.getSource(PLANNER_POINT_SOURCE) as GeoJSONSource | undefined)?.setData(plannerPoints);
    (map.getSource(PLANNER_REFERENCE_SOURCE) as GeoJSONSource | undefined)?.setData(plannerReferencePoint);
    (map.getSource(PLANNER_TRANSIT_SOURCE) as GeoJSONSource | undefined)?.setData(plannerTransit);
    fit(map, items, plannerReference);
  }, [
    fit,
    items,
    plannerArea,
    plannerPoints,
    plannerReference,
    plannerReferencePoint,
    plannerTransit,
    points,
    route,
  ]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    map.getCanvas().style.cursor = plannerDrawing ? "crosshair" : "";
  }, [plannerDrawing]);

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
  const [draftPlanning, setDraftPlanning] = useState<MissionPlanningContext | null>(null);
  const [plannerProfiles, setPlannerProfiles] = useState<MissionPlannerProfile[]>([]);
  const [plannerPlatform, setPlannerPlatform] = useState<"M3E" | "M3T" | "M3M">("M3E");
  const [plannerProfile, setPlannerProfile] = useState("");
  const [plannerPoints, setPlannerPoints] = useState<MissionPlannerPoint[]>([]);
  const [plannerDrawing, setPlannerDrawing] = useState(false);
  const [plannerPreview, setPlannerPreview] = useState<MissionGridPreview | null>(null);
  const [plannerGsd, setPlannerGsd] = useState(2);
  const [plannerForwardOverlap, setPlannerForwardOverlap] = useState(80);
  const [plannerSideOverlap, setPlannerSideOverlap] = useState(70);
  const [plannerDirection, setPlannerDirection] = useState(0);
  const [plannerOptimizeDirection, setPlannerOptimizeDirection] = useState(true);
  const [plannerSpeed, setPlannerSpeed] = useState(8);
  const [plannerFinishAction, setPlannerFinishAction] =
    useState<"RTH" | "LAND" | "NONE">("RTH");
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

  useEffect(() => {
    let cancelled = false;
    void fetchMissionPlannerProfiles()
      .then((catalog) => {
        if (!cancelled) setPlannerProfiles(catalog.profiles);
      })
      .catch((reason) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const selected =
    missions.find((mission) => mission.id === selectedId) ?? null;

  useEffect(() => {
    setDraftItems(
      selected
        ? selected.plan.items.map((item) => ({ ...item, frame: item.frame ?? 6 }))
        : [],
    );
    const savedPlanning = selected?.plan.planning ?? null;
    setDraftPlanning(savedPlanning);
    setPlannerPreview(null);
    setPlannerDrawing(false);

    if (savedPlanning?.planner === "M3_CLOUD_GRID") {
      const savedPlatform = savedPlanning.platform?.toUpperCase();
      if (savedPlatform === "M3E" || savedPlatform === "M3T" || savedPlatform === "M3M") {
        setPlannerPlatform(savedPlatform);
      }
      setPlannerProfile(savedPlanning.capture_profile ?? "");
      setPlannerPoints(
        Array.isArray(savedPlanning.polygon)
          ? savedPlanning.polygon.filter(
              (point) =>
                Number.isFinite(point.latitude_deg) &&
                Number.isFinite(point.longitude_deg),
            )
          : [],
      );

      const parameters = savedPlanning.parameters ?? {};
      const numberParameter = (key: string, fallback: number) => {
        const value = parameters[key];
        return typeof value === "number" && Number.isFinite(value) ? value : fallback;
      };
      setPlannerGsd(numberParameter("gsd_cm", 2));
      setPlannerForwardOverlap(numberParameter("forward_overlap_pct", 80));
      setPlannerSideOverlap(numberParameter("side_overlap_pct", 70));
      setPlannerDirection(numberParameter("direction_deg", 0));
      setPlannerOptimizeDirection(parameters.optimize_direction === true);
      setPlannerSpeed(numberParameter("requested_speed_mps", 8));
      const finishAction = parameters.finish_action;
      setPlannerFinishAction(
        finishAction === "LAND" || finishAction === "NONE" ? finishAction : "RTH",
      );
    } else {
      setPlannerPoints([]);
      setPlannerGsd(2);
      setPlannerForwardOverlap(80);
      setPlannerSideOverlap(70);
      setPlannerDirection(0);
      setPlannerOptimizeDirection(true);
      setPlannerSpeed(8);
      setPlannerFinishAction("RTH");
    }

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
  const plannerReference = plannerStartReference(selectedVehicle);

  const availablePlannerProfiles = useMemo(
    () => plannerProfiles.filter((profile) => profile.platform === plannerPlatform),
    [plannerPlatform, plannerProfiles],
  );

  useEffect(() => {
    if (selected?.plan.planning?.planner === "M3_CLOUD_GRID") return;
    const assigned = vehiclePlatform(selectedVehicle);
    if (assigned) setPlannerPlatform(assigned);
  }, [
    selected?.plan.planning?.planner,
    selectedVehicle?.sn,
    selectedVehicle?.model,
    selectedVehicle?.telemetry?.payload?.platform,
  ]);

  useEffect(() => {
    if (!availablePlannerProfiles.some((profile) => profile.key === plannerProfile)) {
      setPlannerProfile(availablePlannerProfiles[0]?.key ?? "");
    }
  }, [availablePlannerProfiles, plannerProfile]);

  const editDraft = (
    update: (current: MissionPlanItem[]) => MissionPlanItem[],
  ) => {
    setDraftPlanning(null);
    setPlannerPreview(null);
    setDraftItems(update);
  };

  const buildSurveyGrid = async () => {
    if (plannerPoints.length < 3 || !plannerProfile) return;
    setBusy(true);
    try {
      const preview = await previewMissionGrid({
        platform: plannerPlatform,
        capture_profile: plannerProfile,
        polygon: plannerPoints,
        gsd_cm: plannerGsd,
        forward_overlap_pct: plannerForwardOverlap,
        side_overlap_pct: plannerSideOverlap,
        direction_deg: plannerDirection,
        speed_mps: plannerSpeed,
        gimbal_pitch_deg: -90,
        finish_action: plannerFinishAction,
        optimize_direction: plannerOptimizeDirection,
        start_reference: plannerReference,
      });
      setPlannerPreview(preview);
      setPlannerDirection(preview.input.direction_deg);
      setDraftItems(preview.plan.items);
      setDraftPlanning(preview.plan.planning);
      setPlannerDrawing(false);
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

  const uploadHandoff = async (deployment: MissionDeployment) => {
    if (!selected) return;
    setBusy(true);
    try {
      const updated = await uploadMissionDeployment(selected.id, deployment.id);
      setDeployments((current) =>
        current.map((item) => item.id === updated.id ? updated : item),
      );
      await load();
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy(false);
    }
  };

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
      const updated = await updateMission(selected.id, {
        items: renumber(draftItems),
        planning: draftPlanning,
        ...(draftPlanning?.planner === "M3_CLOUD_GRID"
          ? { preferred_executor: "DJI_NATIVE" as const }
          : {}),
      });
      setMissions((current) =>
        current.map((mission) => mission.id === updated.id ? updated : mission),
      );
      setDraftItems(updated.plan.items);
      setDraftPlanning(updated.plan.planning ?? null);
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
              <strong>Upload-only mission handoff</strong>
              <span>
                M3-Cloud can store a sealed plan in Lyrebird when explicitly enabled. Start,
                pause, resume, land, RTH and abort remain unavailable from M3-Cloud.
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
              <MissionMap
                items={draftItems}
                plannerPolygon={plannerPoints}
                plannerDrawing={plannerDrawing}
                onPlannerClick={plannerDrawing
                  ? (point) => {
                      setPlannerPoints((current) => [...current, point]);
                      setPlannerPreview(null);
                    }
                  : undefined}
              />

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
                  <div className="missionDeployments">
                    {deployments.map((deployment) => (
                      <div className="missionDeploymentRow" key={deployment.id}>
                        <a
                          href={missionDeploymentDownloadUrl(selected.id, deployment.id)}
                        >
                          v{deployment.revision_version} · {deployment.package_sha256.slice(0, 8)}
                          {deployment.package.wire ? ` · ${deployment.package.wire.items.length} wire items` : ""}
                        </a>
                        <span>{deployment.upload_status}</span>
                        <button
                          disabled={busy || !deployment.upload_action_available}
                          onClick={() => void uploadHandoff(deployment)}
                          type="button"
                        >
                          Upload to Lyrebird
                        </button>
                        {deployment.upload_status === "UPLOADED" ? (
                          <small className="missionUploadVerified">
                            verified · host {String(deployment.upload_details.host ?? "—")} ·
                            sys {String(deployment.upload_details.system_id ?? "—")} ·
                            executor {String(deployment.upload_details.executor ?? "—")} ·
                            read-back {String(deployment.upload_details.readback_item_count ?? "—")} items ·
                            fingerprint {String(deployment.upload_details.readback_runtime_mission_id ?? "—")}
                          </small>
                        ) : null}
                        {deployment.upload_status === "UPLOAD_UNVERIFIED" ? (
                          <small className="missionUploadUnverified">
                            Aircraft acknowledged the upload, but read-back verification failed.
                          </small>
                        ) : null}
                        {deployment.upload_error ? (
                          <small>{deployment.upload_error}</small>
                        ) : null}
                      </div>
                    ))}
                  </div>
                  <small>
                    Upload stores the exact sealed plan only. It never starts mission execution.
                    Old handoff packages sealed before upload support remain audit-only.
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

            <section className="panel missionPlanner">
              <div className="panelHead">
                <div>
                  <h2>Survey grid planner</h2>
                  <small>M3E / M3T / M3M camera-aware · DJI-native distance capture</small>
                </div>
                <span>{plannerPoints.length} vertices</span>
              </div>

              <div className="missionPlannerBody">
                <div className="missionPlannerFields">
                  <label>
                    Platform
                    <select
                      value={plannerPlatform}
                      onChange={(event) =>
                        setPlannerPlatform(event.target.value as "M3E" | "M3T" | "M3M")
                      }
                    >
                      <option value="M3E">M3E</option>
                      <option value="M3T">M3T</option>
                      <option value="M3M">M3M</option>
                    </select>
                  </label>
                  <label>
                    Capture profile
                    <select
                      value={plannerProfile}
                      onChange={(event) => setPlannerProfile(event.target.value)}
                    >
                      {availablePlannerProfiles.map((profile) => (
                        <option key={profile.key} value={profile.key}>
                          {profile.key}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label>
                    GSD cm/px
                    <input
                      min="0.1"
                      max="50"
                      step="0.1"
                      type="number"
                      value={plannerGsd}
                      onChange={(event) => setPlannerGsd(Number(event.target.value))}
                    />
                  </label>
                  <label>
                    Forward overlap %
                    <input
                      min="0"
                      max="95"
                      step="1"
                      type="number"
                      value={plannerForwardOverlap}
                      onChange={(event) => setPlannerForwardOverlap(Number(event.target.value))}
                    />
                  </label>
                  <label>
                    Side overlap %
                    <input
                      min="0"
                      max="95"
                      step="1"
                      type="number"
                      value={plannerSideOverlap}
                      onChange={(event) => setPlannerSideOverlap(Number(event.target.value))}
                    />
                  </label>
                  <label>
                    Grid heading °
                    <input
                      disabled={plannerOptimizeDirection}
                      min="0"
                      max="359.9"
                      step="1"
                      type="number"
                      value={plannerDirection}
                      onChange={(event) => setPlannerDirection(Number(event.target.value))}
                    />
                  </label>
                  <label>
                    Auto grid direction
                    <input
                      checked={plannerOptimizeDirection}
                      type="checkbox"
                      onChange={(event) => {
                        setPlannerOptimizeDirection(event.target.checked);
                        setPlannerPreview(null);
                      }}
                    />
                  </label>
                  <label>
                    Requested speed m/s
                    <input
                      min="0.1"
                      max="25"
                      step="0.1"
                      type="number"
                      value={plannerSpeed}
                      onChange={(event) => setPlannerSpeed(Number(event.target.value))}
                    />
                  </label>
                  <label>
                    End action
                    <select
                      value={plannerFinishAction}
                      onChange={(event) =>
                        setPlannerFinishAction(
                          event.target.value as "RTH" | "LAND" | "NONE",
                        )
                      }
                    >
                      <option value="RTH">Return to home</option>
                      <option value="LAND">Land at mission end</option>
                      <option value="NONE">No terminal action</option>
                    </select>
                  </label>
                </div>

                <div className="missionPlannerActions">
                  <button
                    className={plannerDrawing ? "active" : ""}
                    disabled={busy || selected.status === "ARCHIVED"}
                    onClick={() => setPlannerDrawing((value) => !value)}
                    type="button"
                  >
                    {plannerDrawing ? "Stop drawing" : "Draw polygon on map"}
                  </button>
                  <button
                    disabled={busy || plannerPoints.length === 0}
                    onClick={() => {
                      setPlannerPoints((current) => current.slice(0, -1));
                      setPlannerPreview(null);
                    }}
                    type="button"
                  >
                    Undo vertex
                  </button>
                  <button
                    disabled={busy || plannerPoints.length === 0}
                    onClick={() => {
                      setPlannerPoints([]);
                      setPlannerPreview(null);
                    }}
                    type="button"
                  >
                    Clear polygon
                  </button>
                  <button
                    disabled={
                      busy ||
                      selected.status === "ARCHIVED" ||
                      plannerPoints.length < 3 ||
                      !plannerProfile
                    }
                    onClick={() => void buildSurveyGrid()}
                    type="button"
                  >
                    Generate grid preview
                  </button>
                </div>

                <small className="missionPlannerHint">
                  Enable drawing, click at least three polygon vertices on the map, then generate.
                  The preview replaces the editable draft only; Save plan creates the immutable
                  revision. Auto direction minimizes planned travel and, when aircraft/home
                  telemetry is available, chooses the nearer grid entry. Camera-specific planner
                  context is stored with that revision and preflight blocks a later M3E/M3T/M3M mismatch.
                </small>

                {plannerPreview ? (
                  <div className="missionPlannerStats">
                    <span>Altitude <b>{plannerPreview.geometry.altitude_m.toFixed(1)} m</b></span>
                    <span>Line spacing <b>{plannerPreview.geometry.actual_line_spacing_m.toFixed(1)} m</b></span>
                    <span>Trigger <b>{plannerPreview.geometry.trigger_distance_m.toFixed(1)} m</b></span>
                    <span>Speed <b>{plannerPreview.cadence.effective_speed_mps.toFixed(1)} m/s</b></span>
                    <span>Segments <b>{plannerPreview.geometry.capture_segment_count}</b></span>
                    <span>Exposures ≤ <b>{plannerPreview.geometry.expected_photos_upper_bound}</b></span>
                    <span>Files ≤ <b>{plannerPreview.geometry.expected_media_assets_upper_bound}</b></span>
                    <span>Grid heading <b>{plannerPreview.optimization.selected_direction_deg.toFixed(1)}°</b></span>
                    <span>Grid time <b>{Math.ceil(plannerPreview.geometry.nominal_route_time_s / 60)} min</b></span>
                    <span>Total est. <b>{Math.ceil(plannerPreview.geometry.nominal_total_time_s / 60)} min</b></span>
                    <span>Ingress <b>{plannerPreview.geometry.ingress_distance_m.toFixed(0)} m</b></span>
                    <span>Return <b>{plannerPreview.geometry.return_distance_m.toFixed(0)} m</b></span>
                    <span>End action <b>{plannerPreview.input.finish_action}</b></span>
                    <span>Items <b>{plannerPreview.mission_item_count}</b></span>
                    <span>Area <b>{(plannerPreview.geometry.area_m2 / 10_000).toFixed(2)} ha</b></span>
                  </div>
                ) : null}

                {plannerPreview?.warnings.map((warning) => (
                  <div className="missionPlannerWarning" key={warning}>{warning}</div>
                ))}
                {availablePlannerProfiles.find((profile) => profile.key === plannerProfile)?.note ? (
                  <small className="missionPlannerNote">
                    {availablePlannerProfiles.find((profile) => profile.key === plannerProfile)?.note}
                  </small>
                ) : null}
              </div>
            </section>

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
                      editDraft((current) => [
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
                      <th>Command</th>
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
                          <span className="missionCommand">{missionCommandLabel(item.command)}</span>
                        </td>
                        <td>
                          <select
                            disabled={selected.status === "ARCHIVED" || item.command !== 16}
                            value={item.frame ?? 6}
                            onChange={(event) => {
                              const frame = Number(event.target.value);
                              editDraft((current) =>
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
                              disabled={selected.status === "ARCHIVED" || item.command !== 16}
                              step="any"
                              type="number"
                              value={value}
                              onChange={(event) => {
                                const raw = event.target.value;
                                editDraft((current) =>
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
                              editDraft((current) =>
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
