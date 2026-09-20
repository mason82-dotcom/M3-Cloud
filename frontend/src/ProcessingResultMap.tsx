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


function addOrthophoto(map: Map, info: ProcessingMapInfo): void {
  if (!map.getSource("webodm-orthophoto")) {
    map.addSource("webodm-orthophoto", {
      type: "raster",
      tiles: [info.tile_url],
      tileSize: 256,
      minzoom: info.minzoom ?? undefined,
      maxzoom: info.maxzoom ?? undefined,
      attribution: info.attribution ?? undefined,
    });
  }

  if (!map.getLayer("webodm-orthophoto")) {
    map.addLayer({
      id: "webodm-orthophoto",
      type: "raster",
      source: "webodm-orthophoto",
      paint: {
        "raster-opacity": 0.9,
      },
    });
  }

  if (info.bounds) {
    const [west, south, east, north] = info.bounds;
    map.fitBounds(
      [[west, south], [east, north]],
      { padding: 40, duration: 700, maxZoom: info.maxzoom ?? 20 },
    );
  }
}


export function ProcessingResultMap({
  info,
  onClose,
}: {
  info: ProcessingMapInfo;
  onClose: () => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const [fallbackActive, setFallbackActive] = useState(false);

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
      addOrthophoto(map, info);
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
  }, [info]);

  return (
    <div className="processingMapModal">
      <div className="processingMapToolbar">
        <div>
          <strong>WebODM Orthophoto</strong>
          <small>
            {info.tile_count ?? "—"} tiles · z{info.minzoom ?? "?"}–{info.maxzoom ?? "?"}
          </small>
        </div>
        <button onClick={onClose} type="button">Close</button>
      </div>
      {fallbackActive ? <div className="map-fallback-badge">MAP FALLBACK</div> : null}
      <div className="processingMap" ref={containerRef} />
    </div>
  );
}
