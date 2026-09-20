import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map, StyleSpecification } from "maplibre-gl";
import type { FeatureCollection, LineString, Point, Position } from "geojson";

import { fetchFlightDetail, fetchFlights } from "./api";
import type { FlightDetail, FlightSummary } from "./types";

const LINE_SOURCE = "m3-history-line";
const LINE_LAYER = "m3-history-line-layer";
const POINT_SOURCE = "m3-history-points";
const POINT_LAYER = "m3-history-points-layer";

const PRIMARY_STYLE =
  import.meta.env.VITE_MAP_STYLE_URL ??
  "https://demotiles.maplibre.org/style.json";

const FALLBACK_TILE_URL =
  import.meta.env.VITE_MAP_FALLBACK_TILE_URL ??
  "https://tile.openstreetmap.org/{z}/{x}/{y}.png";

const FALLBACK_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    "fallback-raster": {
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
      source: "fallback-raster",
    },
  ],
};

function lineData(detail: FlightDetail | null): FeatureCollection<LineString> {
  return {
    type: "FeatureCollection",
    features: detail?.path
      ? [
          {
            type: "Feature",
            geometry: detail.path,
            properties: { flight_id: detail.id },
          },
        ]
      : [],
  };
}

function pointData(detail: FlightDetail | null): FeatureCollection<Point> {
  const features: FeatureCollection<Point>["features"] = [];
  if (detail?.takeoff_position) {
    features.push({
      type: "Feature",
      geometry: detail.takeoff_position,
      properties: { kind: "TAKEOFF" },
    });
  }
  if (detail?.landing_position) {
    features.push({
      type: "Feature",
      geometry: detail.landing_position,
      properties: { kind: "LANDING" },
    });
  }
  return { type: "FeatureCollection", features };
}

function ensureHistoryLayers(
  map: Map,
  line: FeatureCollection<LineString>,
  points: FeatureCollection<Point>,
): void {
  if (!map.getSource(LINE_SOURCE)) {
    map.addSource(LINE_SOURCE, { type: "geojson", data: line });
  }
  if (!map.getLayer(LINE_LAYER)) {
    map.addLayer({
      id: LINE_LAYER,
      type: "line",
      source: LINE_SOURCE,
      paint: {
        "line-width": 4,
        "line-opacity": 0.9,
        "line-color": "#4fc3b6",
      },
    });
  }

  if (!map.getSource(POINT_SOURCE)) {
    map.addSource(POINT_SOURCE, { type: "geojson", data: points });
  }
  if (!map.getLayer(POINT_LAYER)) {
    map.addLayer({
      id: POINT_LAYER,
      type: "circle",
      source: POINT_SOURCE,
      paint: {
        "circle-radius": 7,
        "circle-stroke-width": 2,
        "circle-stroke-color": "#ffffff",
        "circle-color": [
          "case",
          ["==", ["get", "kind"], "TAKEOFF"],
          "#55d58a",
          "#ef7272",
        ],
      },
    });
  }
}

function coordinate2d(position: Position): [number, number] | null {
  const [longitude, latitude] = position;
  return typeof longitude === "number" && typeof latitude === "number"
    ? [longitude, latitude]
    : null;
}

function fitHistory(map: Map, detail: FlightDetail | null): void {
  const coordinates: Array<[number, number]> = [];

  for (const position of detail?.path?.coordinates ?? []) {
    const value = coordinate2d(position);
    if (value) coordinates.push(value);
  }
  for (const point of [detail?.takeoff_position, detail?.landing_position]) {
    if (point) {
      const value = coordinate2d(point.coordinates);
      if (value) coordinates.push(value);
    }
  }

  if (coordinates.length === 0) return;
  if (coordinates.length === 1) {
    map.flyTo({ center: coordinates[0], zoom: 16, essential: true });
    return;
  }

  const bounds = coordinates.reduce(
    (result, coordinate) => result.extend(coordinate),
    new maplibregl.LngLatBounds(coordinates[0], coordinates[0]),
  );
  map.fitBounds(bounds, { padding: 50, maxZoom: 17, duration: 700 });
}

function HistoryMap({ detail }: { detail: FlightDetail | null }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const detailRef = useRef(detail);
  detailRef.current = detail;
  const [fallbackActive, setFallbackActive] = useState(false);

  const line = useMemo(() => lineData(detail), [detail]);
  const points = useMemo(() => pointData(detail), [detail]);
  const lineRef = useRef(line);
  const pointRef = useRef(points);
  lineRef.current = line;
  pointRef.current = points;

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
      ensureHistoryLayers(map, lineRef.current, pointRef.current);
      fitHistory(map, detailRef.current);
    });

    map.on("error", () => {
      if (styleLoaded || fallbackActivated) return;
      fallbackActivated = true;
      setFallbackActive(true);
      map.setStyle(FALLBACK_STYLE);
    });

    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;

    (map.getSource(LINE_SOURCE) as GeoJSONSource | undefined)?.setData(line);
    (map.getSource(POINT_SOURCE) as GeoJSONSource | undefined)?.setData(points);
    fitHistory(map, detail);
  }, [detail, line, points]);

  return (
    <div className="historyMapShell">
      {fallbackActive ? (
        <div className="map-fallback-badge">MAP FALLBACK</div>
      ) : null}
      <div className="historyMap" ref={containerRef} />
    </div>
  );
}

function duration(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const seconds = Math.max(0, Math.round(value));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const rest = seconds % 60;
  return hours > 0
    ? `${hours}h ${minutes}m ${rest}s`
    : `${minutes}m ${rest}s`;
}

function metric(value: number | null | undefined, suffix = "", digits = 1): string {
  return value == null || !Number.isFinite(value)
    ? "—"
    : `${value.toFixed(digits)}${suffix}`;
}

function startedAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

export function FlightHistoryView() {
  const [flights, setFlights] = useState<FlightSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<FlightDetail | null>(null);
  const [aircraftFilter, setAircraftFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const aircraft = useMemo(
    () => Array.from(new Set(flights.map((flight) => flight.aircraft_sn))).sort(),
    [flights],
  );

  const loadFlights = useCallback(async () => {
    setLoading(true);
    try {
      const result = await fetchFlights(aircraftFilter || undefined);
      setFlights(result);
      setSelectedId((current) =>
        current && result.some((flight) => flight.id === current)
          ? current
          : result[0]?.id ?? null,
      );
      setError(null);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }, [aircraftFilter]);

  useEffect(() => {
    void loadFlights();
  }, [loadFlights]);

  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }

    let cancelled = false;
    void fetchFlightDetail(selectedId)
      .then((value) => {
        if (!cancelled) {
          setDetail(value);
          setError(null);
        }
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(reason instanceof Error ? reason.message : String(reason));
        }
      });

    return () => {
      cancelled = true;
    };
  }, [selectedId]);

  return (
    <div className="historyLayout">
      <aside className="historyListPanel panel">
        <div className="panelHead">
          <div>
            <h2>Flight history</h2>
            <small>PostGIS sessions</small>
          </div>
          <button onClick={() => void loadFlights()} type="button">
            {loading ? "…" : "Refresh"}
          </button>
        </div>

        <div className="historyFilter">
          <label htmlFor="history-aircraft">Aircraft</label>
          <select
            id="history-aircraft"
            value={aircraftFilter}
            onChange={(event) => setAircraftFilter(event.target.value)}
          >
            <option value="">All aircraft</option>
            {aircraft.map((sn) => (
              <option key={sn} value={sn}>{sn}</option>
            ))}
          </select>
        </div>

        {error ? <div className="historyError">{error}</div> : null}

        <div className="historyList">
          {flights.length === 0 ? (
            <div className="empty">Noch keine gespeicherten Flüge.</div>
          ) : flights.map((flight) => (
            <button
              className={flight.id === selectedId ? "historyFlight selected" : "historyFlight"}
              key={flight.id}
              onClick={() => setSelectedId(flight.id)}
              type="button"
            >
              <div className="historyFlightHead">
                <strong>{flight.aircraft_sn}</strong>
                <span>{flight.status}</span>
              </div>
              <small>{startedAt(flight.started_at)}</small>
              <div className="historyFlightMetrics">
                <span>{metric(flight.distance_m, " m", 0)}</span>
                <span>{duration(flight.duration_s)}</span>
                <span>{metric(flight.rtk_converged_percent, "%", 0)} RTK</span>
              </div>
            </button>
          ))}
        </div>
      </aside>

      <section className="historyDetail">
        <HistoryMap detail={detail} />

        <div className="historyStats">
          <article className="panel">
            <span>Duration</span>
            <strong>{duration(detail?.duration_s)}</strong>
          </article>
          <article className="panel">
            <span>Distance</span>
            <strong>{metric(detail?.distance_m, " m", 0)}</strong>
          </article>
          <article className="panel">
            <span>Max altitude</span>
            <strong>{metric(detail?.max_relative_altitude_m, " m")}</strong>
          </article>
          <article className="panel">
            <span>Max speed</span>
            <strong>{metric(detail?.max_horizontal_speed_mps, " m/s")}</strong>
          </article>
          <article className="panel">
            <span>Min battery</span>
            <strong>{metric(detail?.min_battery_percent, "%", 0)}</strong>
          </article>
          <article className="panel">
            <span>RTK converged</span>
            <strong>{metric(detail?.rtk_converged_percent, "%", 1)}</strong>
          </article>
        </div>

        <section className="panel historyMetadata">
          <div className="panelHead">
            <div>
              <h2>{detail?.aircraft_sn ?? "Flight detail"}</h2>
              <small>{detail ? startedAt(detail.started_at) : "Flug auswählen"}</small>
            </div>
            <span>{detail?.status ?? "—"}</span>
          </div>
          <dl>
            <dt>Flight ID</dt><dd>{detail?.id ?? "—"}</dd>
            <dt>Gateway</dt><dd>{detail?.gateway_sn ?? "—"}</dd>
            <dt>DJI track</dt><dd>{detail?.dji_track_id ?? "—"}</dd>
            <dt>End reason</dt><dd>{detail?.end_reason ?? "—"}</dd>
            <dt>Started</dt><dd>{detail ? startedAt(detail.started_at) : "—"}</dd>
            <dt>Ended</dt><dd>{detail?.ended_at ? startedAt(detail.ended_at) : "—"}</dd>
          </dl>
        </section>
      </section>
    </div>
  );
}
