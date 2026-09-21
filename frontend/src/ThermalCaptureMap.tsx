import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map, StyleSpecification } from "maplibre-gl";

import type { ThermalCapturePointCollection } from "./types";

const SOURCE = "m3-thermal-capture-points";
const LAYER = "m3-thermal-capture-points-layer";

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

function fit(map: Map, data: ThermalCapturePointCollection): void {
  const coordinates: [number, number][] = [];
  for (const feature of data.features) {
    const [longitude, latitude] = feature.geometry.coordinates;
    if (
      typeof longitude === "number" &&
      typeof latitude === "number" &&
      Number.isFinite(longitude) &&
      Number.isFinite(latitude)
    ) {
      coordinates.push([longitude, latitude]);
    }
  }

  if (coordinates.length === 0) return;
  if (coordinates.length === 1) {
    map.flyTo({ center: coordinates[0], zoom: 17, essential: true });
    return;
  }

  const bounds = coordinates.reduce(
    (current, coordinate) => current.extend(coordinate),
    new maplibregl.LngLatBounds(coordinates[0], coordinates[0]),
  );
  map.fitBounds(bounds, { padding: 45, maxZoom: 18, duration: 500 });
}

function summary(properties: Record<string, unknown>): string {
  const capture =
    typeof properties.capture_group === "string"
      ? properties.capture_group.split("/").pop()
      : "DJI thermal capture";
  const max =
    typeof properties.max_c === "number"
      ? `${properties.max_c.toFixed(1)} °C max`
      : "max n/a";
  const count =
    typeof properties.hotspot_component_count === "number"
      ? `${properties.hotspot_component_count} hotspot candidates`
      : "hotspots n/a";
  const delta =
    typeof properties.hotspot_peak_delta_c === "number"
      ? `peak ΔT ${properties.hotspot_peak_delta_c.toFixed(1)} °C`
      : null;
  return [capture, max, count, delta, "Capture-center GPS only"]
    .filter(Boolean)
    .join(" · ");
}

export function ThermalCaptureMap({
  data,
}: {
  data: ThermalCapturePointCollection;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const dataRef = useRef(data);
  dataRef.current = data;
  const [fallbackActive, setFallbackActive] = useState(false);

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
      if (!map.getSource(SOURCE)) {
        map.addSource(SOURCE, {
          type: "geojson",
          data: dataRef.current,
        });
      }
      if (!map.getLayer(LAYER)) {
        map.addLayer({
          id: LAYER,
          type: "circle",
          source: SOURCE,
          paint: {
            "circle-radius": [
              "interpolate",
              ["linear"],
              ["coalesce", ["get", "hotspot_component_count"], 0],
              0, 5,
              1, 7,
              5, 11,
            ],
            "circle-stroke-width": 1.5,
            "circle-stroke-color": "#ffffff",
            "circle-opacity": 0.9,
            "circle-color": [
              "case",
              [">", ["coalesce", ["get", "hotspot_component_count"], 0], 0],
              "#ff7043",
              "#4fc3b6",
            ],
          },
        });
      }

      map.on("click", LAYER, (event) => {
        const feature = event.features?.[0];
        if (!feature || feature.geometry.type !== "Point") return;
        const coordinates = feature.geometry.coordinates as [number, number];
        new maplibregl.Popup({ closeButton: true })
          .setLngLat(coordinates)
          .setText(summary(feature.properties ?? {}))
          .addTo(map);
      });
      map.on("mouseenter", LAYER, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", LAYER, () => {
        map.getCanvas().style.cursor = "";
      });

      fit(map, dataRef.current);
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
    (map.getSource(SOURCE) as GeoJSONSource | undefined)?.setData(data);
    fit(map, data);
  }, [data]);

  return (
    <div className="mediaCaptureMapShell thermalCaptureMapShell">
      {fallbackActive ? (
        <div className="map-fallback-badge">MAP FALLBACK</div>
      ) : null}
      <div className="mediaCaptureMap thermalCaptureMap" ref={containerRef} />
      <small className="thermalCaptureMapNote">
        Capture-center GPS only · thermal pixels and hotspot masks are not georeferenced.
      </small>
    </div>
  );
}
