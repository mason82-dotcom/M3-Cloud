import { useEffect, useMemo, useRef } from "react";
import maplibregl, { type GeoJSONSource, type Map } from "maplibre-gl";
import type { FeatureCollection, Point } from "geojson";

import type { Device, Telemetry } from "./types";

interface MapViewProps {
  devices: Device[];
  telemetry: Record<string, Telemetry>;
  selectedSn: string | null;
}

const MAP_SOURCE_ID = "m3-aircraft";
const MAP_POINT_LAYER = "m3-aircraft-points";
const MAP_LABEL_LAYER = "m3-aircraft-labels";

function featureCollection(
  devices: Device[],
  telemetry: Record<string, Telemetry>,
): FeatureCollection<Point> {
  return {
    type: "FeatureCollection",
    features: devices.flatMap((device) => {
      const state = telemetry[device.sn];
      if (
        state?.latitude === undefined ||
        state.longitude === undefined ||
        !Number.isFinite(state.latitude) ||
        !Number.isFinite(state.longitude)
      ) {
        return [];
      }

      return [
        {
          type: "Feature" as const,
          geometry: {
            type: "Point" as const,
            coordinates: [state.longitude, state.latitude],
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

export function MapView({
  devices,
  telemetry,
  selectedSn,
}: MapViewProps) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);

  const data = useMemo(
    () => featureCollection(devices, telemetry),
    [devices, telemetry],
  );

  useEffect(() => {
    if (!containerRef.current || mapRef.current) {
      return;
    }

    const map = new maplibregl.Map({
      container: containerRef.current,
      style:
        import.meta.env.VITE_MAP_STYLE_URL ??
        "https://demotiles.maplibre.org/style.json",
      center: [8.5, 49.1],
      zoom: 7,
      attributionControl: true,
    });

    map.addControl(new maplibregl.NavigationControl(), "top-right");

    map.on("load", () => {
      map.addSource(MAP_SOURCE_ID, {
        type: "geojson",
        data,
      });

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
    if (
      state?.latitude === undefined ||
      state.longitude === undefined
    ) {
      return;
    }

    map.flyTo({
      center: [state.longitude, state.latitude],
      zoom: Math.max(map.getZoom(), 15),
      essential: true,
    });
  }, [selectedSn, telemetry]);

  return <div className="map" ref={containerRef} />;
}
