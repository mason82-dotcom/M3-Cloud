import { useEffect, useMemo, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map, StyleSpecification } from "maplibre-gl";
import type { FeatureCollection, Point } from "geojson";

import type { Telemetry, Vehicle } from "./types";

interface MapViewProps {
  devices: Vehicle[];
  telemetry: Record<string, Telemetry>;
  selectedSn: string | null;
}

const MAP_SOURCE_ID = "m3-aircraft";
const MAP_POINT_LAYER = "m3-aircraft-points";
const MAP_LABEL_LAYER = "m3-aircraft-labels";

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
      paint: {
        "background-color": "#151a20",
      },
    },
    {
      id: "fallback-raster",
      type: "raster",
      source: "fallback-raster",
    },
  ],
};

function featureCollection(
  devices: Vehicle[],
  telemetry: Record<string, Telemetry>,
): FeatureCollection<Point> {
  return {
    type: "FeatureCollection",
    features: devices.flatMap((device) => {
      const state = telemetry[device.sn];
      const latitude = state?.latitude;
      const longitude = state?.longitude;
      if (
        typeof latitude !== "number" ||
        typeof longitude !== "number" ||
        !Number.isFinite(latitude) ||
        !Number.isFinite(longitude)
      ) {
        return [];
      }

      return [
        {
          type: "Feature" as const,
          geometry: {
            type: "Point" as const,
            coordinates: [longitude, latitude],
          },
          properties: {
            sn: device.sn,
            model: device.model,
            online: device.online,
          },
        },
      ];
    }),
  };
}

function ensureAircraftLayers(
  map: Map,
  data: FeatureCollection<Point>,
): void {
  if (!map.getSource(MAP_SOURCE_ID)) {
    map.addSource(MAP_SOURCE_ID, {
      type: "geojson",
      data,
    });
  }

  if (!map.getLayer(MAP_POINT_LAYER)) {
    map.addLayer({
      id: MAP_POINT_LAYER,
      type: "circle",
      source: MAP_SOURCE_ID,
      paint: {
        "circle-radius": 8,
        "circle-stroke-width": 2,
        "circle-stroke-color": "#ffffff",
        "circle-color": [
          "case",
          ["boolean", ["get", "online"], false],
          "#28c76f",
          "#7f8791",
        ],
      },
    });
  }

  if (!map.getLayer(MAP_LABEL_LAYER)) {
    map.addLayer({
      id: MAP_LABEL_LAYER,
      type: "symbol",
      source: MAP_SOURCE_ID,
      layout: {
        "text-field": ["get", "model"],
        "text-size": 11,
        "text-offset": [0, 1.4],
        "text-anchor": "top",
      },
      paint: {
        "text-color": "#ffffff",
        "text-halo-color": "#101317",
        "text-halo-width": 1.5,
      },
    });
  }
}

export function MapView({
  devices,
  telemetry,
  selectedSn,
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const [fallbackActive, setFallbackActive] = useState(false);

  const data = useMemo(
    () => featureCollection(devices, telemetry),
    [devices, telemetry],
  );
  const dataRef = useRef(data);
  dataRef.current = data;

  useEffect(() => {
    if (!containerRef.current || mapRef.current) {
      return;
    }

    let fallbackActivated = false;
    let styleLoaded = false;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: PRIMARY_STYLE,
      center: [8.5, 49.1],
      zoom: 7,
    });

    map.addControl(new maplibregl.NavigationControl(), "top-right");

    map.on("style.load", () => {
      styleLoaded = true;
      ensureAircraftLayers(map, dataRef.current);
    });

    map.on("error", () => {
      if (styleLoaded || fallbackActivated) {
        return;
      }

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
    if (!map || !map.isStyleLoaded()) {
      return;
    }

    const source = map.getSource(MAP_SOURCE_ID) as GeoJSONSource | undefined;
    source?.setData(data);
  }, [data]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || selectedSn === null) {
      return;
    }

    const state = telemetry[selectedSn];
    const latitude = state?.latitude;
    const longitude = state?.longitude;
    if (
      typeof latitude !== "number" ||
      typeof longitude !== "number"
    ) {
      return;
    }

    map.flyTo({
      center: [longitude, latitude],
      zoom: Math.max(map.getZoom(), 15),
      essential: true,
    });
  }, [selectedSn, telemetry]);

  return (
    <>
      {fallbackActive ? (
        <div className="map-fallback-badge">MAP FALLBACK</div>
      ) : null}
      <div className="map" ref={containerRef} />
    </>
  );
}
