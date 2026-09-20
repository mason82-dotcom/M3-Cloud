import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map, StyleSpecification } from "maplibre-gl";
import type { FeatureCollection, LineString, Point, Position } from "geojson";

import { fetchFlightDetail, fetchFlightSamples, fetchFlights } from "./api";
import type {
  FlightDetail,
  FlightSample,
  FlightSummary,
} from "./types";

const TRACK_SOURCE = "m3-history-track";
const TRACK_LAYER = "m3-history-track-layer";
const POINT_SOURCE = "m3-history-points";
const POINT_LAYER = "m3-history-points-layer";
const REPLAY_SOURCE = "m3-history-replay";
const REPLAY_LAYER = "m3-history-replay-layer";

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

function coordinate(sample: FlightSample | undefined): [number, number] | null {
  if (
    typeof sample?.longitude !== "number" ||
    typeof sample.latitude !== "number" ||
    !Number.isFinite(sample.longitude) ||
    !Number.isFinite(sample.latitude)
  ) {
    return null;
  }
  return [sample.longitude, sample.latitude];
}

function coordinate2d(position: Position): [number, number] | null {
  const [longitude, latitude] = position;
  return typeof longitude === "number" && typeof latitude === "number"
    ? [longitude, latitude]
    : null;
}

function quality(sample: FlightSample): string {
  return String(sample.position_convergence ?? "UNKNOWN").toUpperCase();
}

function trackData(
  detail: FlightDetail | null,
  samples: FlightSample[],
): FeatureCollection<LineString> {
  const features: FeatureCollection<LineString>["features"] = [];

  for (let index = 1; index < samples.length; index += 1) {
    const previous = coordinate(samples[index - 1]);
    const current = coordinate(samples[index]);
    if (!previous || !current) continue;

    features.push({
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [previous, current],
      },
      properties: {
        quality: quality(samples[index]),
        source: samples[index].source,
      },
    });
  }

  if (features.length === 0 && detail?.path) {
    features.push({
      type: "Feature",
      geometry: detail.path,
      properties: {
        quality: "UNKNOWN",
        source: "aggregate",
      },
    });
  }

  return { type: "FeatureCollection", features };
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

function replayData(sample: FlightSample | undefined): FeatureCollection<Point> {
  const value = coordinate(sample);
  return {
    type: "FeatureCollection",
    features: value
      ? [
          {
            type: "Feature",
            geometry: { type: "Point", coordinates: value },
            properties: {
              source: sample?.source ?? "unknown",
              quality: sample ? quality(sample) : "UNKNOWN",
            },
          },
        ]
      : [],
  };
}

function ensureHistoryLayers(
  map: Map,
  track: FeatureCollection<LineString>,
  points: FeatureCollection<Point>,
  replay: FeatureCollection<Point>,
): void {
  if (!map.getSource(TRACK_SOURCE)) {
    map.addSource(TRACK_SOURCE, { type: "geojson", data: track });
  }
  if (!map.getLayer(TRACK_LAYER)) {
    map.addLayer({
      id: TRACK_LAYER,
      type: "line",
      source: TRACK_SOURCE,
      paint: {
        "line-width": 4,
        "line-opacity": 0.9,
        "line-color": [
          "match",
          ["get", "quality"],
          "FIXED", "#55d58a",
          "FLOAT", "#69a9ff",
          "STALE", "#ef7272",
          "CONVERGED", "#4fc3b6",
          "CONVERGING", "#e7b34c",
          "FAILED", "#ef7272",
          "#7f8791",
        ],
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

  if (!map.getSource(REPLAY_SOURCE)) {
    map.addSource(REPLAY_SOURCE, { type: "geojson", data: replay });
  }
  if (!map.getLayer(REPLAY_LAYER)) {
    map.addLayer({
      id: REPLAY_LAYER,
      type: "circle",
      source: REPLAY_SOURCE,
      paint: {
        "circle-radius": 10,
        "circle-stroke-width": 3,
        "circle-stroke-color": "#ffffff",
        "circle-color": [
          "match",
          ["get", "source"],
          "lyrebird", "#4fc3b6",
          "dji_cloud", "#69a9ff",
          "#edf3f8",
        ],
      },
    });
  }
}

function fitHistory(
  map: Map,
  detail: FlightDetail | null,
  samples: FlightSample[],
): void {
  const coordinates: Array<[number, number]> = [];

  for (const sample of samples) {
    const value = coordinate(sample);
    if (value) coordinates.push(value);
  }

  if (coordinates.length === 0) {
    for (const position of detail?.path?.coordinates ?? []) {
      const value = coordinate2d(position);
      if (value) coordinates.push(value);
    }
  }

  if (coordinates.length === 0) return;
  if (coordinates.length === 1) {
    map.flyTo({ center: coordinates[0], zoom: 16, essential: true });
    return;
  }

  const bounds = coordinates.reduce(
    (result, current) => result.extend(current),
    new maplibregl.LngLatBounds(coordinates[0], coordinates[0]),
  );
  map.fitBounds(bounds, { padding: 50, maxZoom: 17, duration: 700 });
}

function HistoryMap({
  detail,
  samples,
  replayIndex,
}: {
  detail: FlightDetail | null;
  samples: FlightSample[];
  replayIndex: number;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const detailRef = useRef(detail);
  const samplesRef = useRef(samples);
  const [fallbackActive, setFallbackActive] = useState(false);

  detailRef.current = detail;
  samplesRef.current = samples;

  const track = useMemo(() => trackData(detail, samples), [detail, samples]);
  const points = useMemo(() => pointData(detail), [detail]);
  const replay = useMemo(
    () => replayData(samples[replayIndex]),
    [replayIndex, samples],
  );

  const trackRef = useRef(track);
  const pointRef = useRef(points);
  const replayRef = useRef(replay);
  trackRef.current = track;
  pointRef.current = points;
  replayRef.current = replay;

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
      ensureHistoryLayers(
        map,
        trackRef.current,
        pointRef.current,
        replayRef.current,
      );
      fitHistory(map, detailRef.current, samplesRef.current);
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

    (map.getSource(TRACK_SOURCE) as GeoJSONSource | undefined)?.setData(track);
    (map.getSource(POINT_SOURCE) as GeoJSONSource | undefined)?.setData(points);
    fitHistory(map, detail, samples);
  }, [detail, points, samples, track]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !map.isStyleLoaded()) return;
    (map.getSource(REPLAY_SOURCE) as GeoJSONSource | undefined)?.setData(replay);
  }, [replay]);

  return (
    <div className="historyMapShell">
      {fallbackActive ? (
        <div className="map-fallback-badge">MAP FALLBACK</div>
      ) : null}
      <div className="historyLegend">
        <span><i className="legend-fixed" />FIXED</span>
        <span><i className="legend-float" />FLOAT</span>
        <span><i className="legend-converged" />CONVERGED</span>
        <span><i className="legend-warn" />CONVERGING</span>
        <span><i className="legend-stale" />STALE/FAILED</span>
      </div>
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

function metric(
  value: number | null | undefined,
  suffix = "",
  digits = 1,
): string {
  return value == null || !Number.isFinite(value)
    ? "—"
    : `${value.toFixed(digits)}${suffix}`;
}

function startedAt(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function sampleTime(sample: FlightSample | undefined): string {
  if (!sample) return "—";
  return startedAt(sample.recorded_at);
}

function elapsed(samples: FlightSample[], index: number): string {
  if (samples.length === 0) return "—";
  const current = samples[Math.min(index, samples.length - 1)];
  const first = samples[0];
  return duration(
    Math.max(0, current.source_timestamp_ms - first.source_timestamp_ms) / 1000,
  );
}

function ReplayControls({
  samples,
  index,
  playing,
  speed,
  onIndex,
  onPlaying,
  onSpeed,
}: {
  samples: FlightSample[];
  index: number;
  playing: boolean;
  speed: number;
  onIndex: (index: number) => void;
  onPlaying: (playing: boolean) => void;
  onSpeed: (speed: number) => void;
}) {
  const current = samples[index];

  return (
    <section className="panel replayPanel">
      <div className="replayHead">
        <div>
          <h2>Replay</h2>
          <small>{sampleTime(current)} · +{elapsed(samples, index)}</small>
        </div>
        <div className="replayActions">
          <button
            disabled={samples.length < 2}
            onClick={() => onPlaying(!playing)}
            type="button"
          >
            {playing ? "Pause" : "Play"}
          </button>
          <button
            disabled={samples.length === 0}
            onClick={() => {
              onPlaying(false);
              onIndex(0);
            }}
            type="button"
          >
            Reset
          </button>
          <select
            aria-label="Replay speed"
            value={speed}
            onChange={(event) => onSpeed(Number(event.target.value))}
          >
            {[0.5, 1, 2, 4].map((value) => (
              <option key={value} value={value}>{value}×</option>
            ))}
          </select>
        </div>
      </div>

      <input
        aria-label="Flight replay timeline"
        disabled={samples.length === 0}
        max={Math.max(0, samples.length - 1)}
        min={0}
        onChange={(event) => {
          onPlaying(false);
          onIndex(Number(event.target.value));
        }}
        step={1}
        type="range"
        value={Math.min(index, Math.max(0, samples.length - 1))}
      />

      <div className="replayMetrics">
        <span>Source<b>{current?.source ?? "—"}</b></span>
        <span>Position<b>{current ? quality(current) : "—"}</b></span>
        <span>Altitude<b>{metric(current?.relative_altitude_m, " m")}</b></span>
        <span>Speed<b>{metric(current?.horizontal_speed_mps, " m/s")}</b></span>
        <span>Battery<b>{metric(current?.battery_percent, "%", 0)}</b></span>
        <span>GNSS / RTK<b>{current ? `${current.gps_satellites ?? "—"} / ${current.rtk_satellites ?? "—"}` : "—"}</b></span>
      </div>
    </section>
  );
}

export function FlightHistoryView() {
  const [flights, setFlights] = useState<FlightSummary[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<FlightDetail | null>(null);
  const [samples, setSamples] = useState<FlightSample[]>([]);
  const [replayIndex, setReplayIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
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
    setPlaying(false);
    setReplayIndex(0);
    setSamples([]);

    if (!selectedId) {
      setDetail(null);
      return;
    }

    let cancelled = false;
    void Promise.all([
      fetchFlightDetail(selectedId),
      fetchFlightSamples(selectedId),
    ])
      .then(([flight, replay]) => {
        if (cancelled) return;
        setDetail(flight);
        setSamples(replay.samples);
        setError(
          replay.truncated
            ? `Replay truncated: ${replay.count} of ${replay.total} samples`
            : null,
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
  }, [selectedId]);

  useEffect(() => {
    if (!playing || samples.length < 2) return;
    if (replayIndex >= samples.length - 1) {
      setPlaying(false);
      return;
    }

    const current = samples[replayIndex];
    const next = samples[replayIndex + 1];
    const sourceDelta = Math.max(
      50,
      next.source_timestamp_ms - current.source_timestamp_ms,
    );
    const delay = Math.min(5000, sourceDelta / speed);

    const timer = window.setTimeout(() => {
      setReplayIndex((value) => Math.min(value + 1, samples.length - 1));
    }, delay);

    return () => window.clearTimeout(timer);
  }, [playing, replayIndex, samples, speed]);

  const currentSample = samples[replayIndex];

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
        <HistoryMap
          detail={detail}
          replayIndex={replayIndex}
          samples={samples}
        />

        <ReplayControls
          index={replayIndex}
          onIndex={setReplayIndex}
          onPlaying={setPlaying}
          onSpeed={setSpeed}
          playing={playing}
          samples={samples}
          speed={speed}
        />

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
              <small>
                {currentSample
                  ? `${currentSample.source} · ${quality(currentSample)} · sample ${replayIndex + 1}/${samples.length}`
                  : detail
                    ? startedAt(detail.started_at)
                    : "Flug auswählen"}
              </small>
            </div>
            <span>{detail?.status ?? "—"}</span>
          </div>
          <dl>
            <dt>Flight ID</dt><dd>{detail?.id ?? "—"}</dd>
            <dt>Gateway</dt><dd>{detail?.gateway_sn ?? "—"}</dd>
            <dt>Sources</dt><dd>{detail?.sources?.join(" + ") || "—"}</dd>
            <dt>DJI track</dt><dd>{detail?.dji_track_id ?? "—"}</dd>
            <dt>End reason</dt><dd>{detail?.end_reason ?? "—"}</dd>
            <dt>Started</dt><dd>{detail ? startedAt(detail.started_at) : "—"}</dd>
            <dt>Ended</dt><dd>{detail?.ended_at ? startedAt(detail.ended_at) : "—"}</dd>
          </dl>

          <div className="flightRelations">
            <div>
              <h3>Media datasets</h3>
              {detail?.media_datasets?.length ? (
                detail.media_datasets.map((dataset) => (
                  <article key={dataset.id}>
                    <strong>{dataset.title || dataset.prefix}</strong>
                    <small>
                      {dataset.platform} · {dataset.present ? "present" : "missing"}
                    </small>
                  </article>
                ))
              ) : (
                <small>Keine SD-Datasets zugeordnet.</small>
              )}
            </div>

            <div>
              <h3>Processing</h3>
              {detail?.processing_jobs?.length ? (
                detail.processing_jobs.map((job) => (
                  <article key={job.id}>
                    <strong>{job.name}</strong>
                    <small>
                      {job.kind} · {job.status} · {job.platform ?? "AUTO"}
                    </small>
                  </article>
                ))
              ) : (
                <small>Noch keine Processing-Jobs für diesen Flug.</small>
              )}
            </div>
          </div>
        </section>
      </section>
    </div>
  );
}
