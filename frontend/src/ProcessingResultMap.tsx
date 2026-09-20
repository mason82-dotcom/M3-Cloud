import { useEffect, useRef, useState } from "react";
import * as maplibregl from "maplibre-gl";
import type { Map, StyleSpecification } from "maplibre-gl";

import type { ProcessingMapInfo } from "./types";


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


function layerId(info: ProcessingMapInfo): string {
  return `processing-map-${info.result_id}`;
}


function addResultLayer(map: Map, info: ProcessingMapInfo): void {
  const id = layerId(info);
  if (!map.getSource(id)) {
    map.addSource(id, {
      type: "raster",
      tiles: [info.tile_url],
      tileSize: 256,
      minzoom: info.minzoom ?? undefined,
      maxzoom: info.maxzoom ?? undefined,
      attribution: info.attribution ?? undefined,
    });
  }

  if (!map.getLayer(id)) {
    map.addLayer({
      id,
      type: "raster",
      source: id,
      paint: {
        "raster-opacity": 0.9,
      },
    });
  }
}


function fitResult(map: Map, info: ProcessingMapInfo): void {
  if (!info.bounds) return;
  const [west, south, east, north] = info.bounds;
  map.fitBounds(
    [[west, south], [east, north]],
    { padding: 40, duration: 700, maxZoom: info.maxzoom ?? 20 },
  );
}


export function ProcessingResultMap({
  info,
  maps,
  onSelect,
  onClose,
}: {
  info: ProcessingMapInfo;
  maps: ProcessingMapInfo[];
  onSelect: (info: ProcessingMapInfo) => void;
  onClose: () => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const activeRef = useRef(info);
  const [fallbackActive, setFallbackActive] = useState(false);
  activeRef.current = info;

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    let primaryLoaded = false;
    let fallbackActivated = false;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: PRIMARY_STYLE,
      center: [8.5, 49.1],
      zoom: 7,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");

    map.on("style.load", () => {
      primaryLoaded = true;
      addResultLayer(map, activeRef.current);
      fitResult(map, activeRef.current);
    });

    map.on("error", () => {
      if (primaryLoaded || fallbackActivated) return;
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

    for (const item of maps) {
      const id = layerId(item);
      if (map.getLayer(id)) {
        map.removeLayer(id);
      }
      if (map.getSource(id)) {
        map.removeSource(id);
      }
    }

    addResultLayer(map, info);
    fitResult(map, info);
  }, [info, maps]);

  return (
    <div className="processingMapModal">
      <div className="processingMapToolbar">
        <div>
          <strong>WebODM Map Layers</strong>
          <small>
            {info.layer_type ?? "ORTHOPHOTO"} · {info.tile_count ?? "—"} tiles ·
            z{info.minzoom ?? "?"}–{info.maxzoom ?? "?"}
          </small>
        </div>
        <div className="processing3DActions">
          {maps.length > 1 ? (
            <select
              aria-label="Processing map layer"
              value={info.result_id}
              onChange={(event) => {
                const next = maps.find((item) => item.result_id === event.target.value);
                if (next) onSelect(next);
              }}
            >
              {maps.map((item) => (
                <option key={item.result_id} value={item.result_id}>
                  {item.layer_type ?? item.result_id}
                </option>
              ))}
            </select>
          ) : null}
          <button onClick={onClose} type="button">Close</button>
        </div>
      </div>
      {fallbackActive ? <div className="map-fallback-badge">MAP FALLBACK</div> : null}
      <div className="processingMap" ref={containerRef} />
    </div>
  );
}
