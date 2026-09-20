import { useEffect, useRef, useState } from "react";
import { Tile3DLayer } from "@deck.gl/geo-layers";
import { MapLibreOverlay } from "@deck.gl/maplibre";
import { Tiles3DLoader } from "@loaders.gl/3d-tiles";
import * as maplibregl from "maplibre-gl";
import type { Map, StyleSpecification } from "maplibre-gl";

import type { ProcessingSceneInfo } from "./types";


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


export function Processing3DView({
  scene,
  scenes,
  onSelect,
  onClose,
}: {
  scene: ProcessingSceneInfo;
  scenes: ProcessingSceneInfo[];
  onSelect: (scene: ProcessingSceneInfo) => void;
  onClose: () => void;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<Map | null>(null);
  const overlayRef = useRef<MapLibreOverlay | null>(null);
  const [fallbackActive, setFallbackActive] = useState(false);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    let primaryLoaded = false;
    let fallbackActivated = false;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: PRIMARY_STYLE,
      center: scene.bounds
        ? [
            (scene.bounds[0] + scene.bounds[2]) / 2,
            (scene.bounds[1] + scene.bounds[3]) / 2,
          ]
        : [8.5, 49.1],
      zoom: scene.bounds ? 16 : 7,
      pitch: 60,
      bearing: -20,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");

    const overlay = new MapLibreOverlay({
      interleaved: true,
      layers: [],
    });
    overlayRef.current = overlay;
    map.addControl(overlay);

    map.on("style.load", () => {
      primaryLoaded = true;
    });

    map.on("error", () => {
      if (primaryLoaded || fallbackActivated) return;
      fallbackActivated = true;
      setFallbackActive(true);
      map.setStyle(FALLBACK_STYLE);
    });

    mapRef.current = map;
    return () => {
      overlayRef.current = null;
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const overlay = overlayRef.current;
    const map = mapRef.current;
    if (!overlay || !map) return;

    overlay.setProps({
      layers: [
        new Tile3DLayer({
          id: `webodm-3d-${scene.result_id}`,
          data: scene.tileset_url,
          loader: Tiles3DLoader,
          pointSize: 2,
          onTilesetLoad: (tileset) => {
            const value = tileset as unknown as {
              cartographicCenter?: [number, number, number];
              zoom?: number;
            };
            const center = value.cartographicCenter;
            if (center) {
              map.jumpTo({
                center: [center[0], center[1]],
                zoom: Math.max(14, value.zoom ?? 16),
                pitch: 60,
              });
            }
          },
        }),
      ],
    });

    if (scene.bounds) {
      map.fitBounds(
        [
          [scene.bounds[0], scene.bounds[1]],
          [scene.bounds[2], scene.bounds[3]],
        ],
        { padding: 50, maxZoom: 18, duration: 700 },
      );
    }
  }, [scene]);

  return (
    <div className="processingMapModal processing3DModal">
      <div className="processingMapToolbar">
        <div>
          <strong>WebODM 3D Tiles</strong>
          <small>
            {scene.scene_type ?? scene.asset_name} · {scene.file_count ?? "—"} files
          </small>
        </div>
        <div className="processing3DActions">
          {scenes.length > 1 ? (
            <select
              aria-label="3D scene"
              value={scene.result_id}
              onChange={(event) => {
                const next = scenes.find((item) => item.result_id === event.target.value);
                if (next) onSelect(next);
              }}
            >
              {scenes.map((item) => (
                <option key={item.result_id} value={item.result_id}>
                  {item.scene_type ?? item.asset_name}
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
