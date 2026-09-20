import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map, StyleSpecification } from "maplibre-gl";

import type { MediaPositionCollection } from "./types";

const SOURCE = "m3-media-captures";
const LAYER = "m3-media-captures-layer";

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

function fit(map: Map, data: MediaPositionCollection): void {
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

export function MediaCaptureMap({
  data,
  onSelect,
}: {
  data: MediaPositionCollection;
  onSelect: (assetId: string) => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const dataRef = useRef(data);
  dataRef.current = data;
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;
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
            "circle-radius": 5,
            "circle-stroke-width": 1.5,
            "circle-stroke-color": "#ffffff",
            "circle-opacity": 0.88,
            "circle-color": [
              "match",
              ["get", "media_kind"],
              "THERMAL", "#e7b34c",
              "MS_GREEN", "#55d58a",
              "MS_RED", "#ef7272",
              "MS_RED_EDGE", "#d86be5",
              "MS_NIR", "#9b8cff",
              "ZOOM", "#69a9ff",
              "WIDE", "#4fc3b6",
              "#edf3f8",
            ],
          },
        });
      }

      map.on("click", LAYER, (event) => {
        const id = event.features?.[0]?.properties?.id;
        if (typeof id === "string") onSelectRef.current(id);
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
    <div className="mediaCaptureMapShell">
      {fallbackActive ? (
        <div className="map-fallback-badge">MAP FALLBACK</div>
      ) : null}
      <div className="mediaCaptureMap" ref={containerRef} />
    </div>
  );
}
