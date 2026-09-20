import { useEffect } from "react";

import { liveWebSocketUrl } from "./api";
import type { LiveEvent } from "./types";

const LIVE_EVENT_TYPES = new Set([
  "telemetry",
  "vehicle_telemetry",
  "device_online",
  "device_offline",
  "topology",
]);

export function useLiveEvents(
  onEvent: (event: LiveEvent) => void,
  onConnection: (connected: boolean) => void,
): void {
  useEffect(() => {
    let socket: WebSocket | null = null;
    let retryTimer: number | null = null;
    let stopped = false;

    const connect = () => {
      if (stopped) return;

      socket = new WebSocket(liveWebSocketUrl());

      socket.onopen = () => onConnection(true);

      socket.onmessage = (message) => {
        let payload: unknown;
        try {
          payload = JSON.parse(String(message.data));
        } catch {
          return;
        }

        if (
          typeof payload === "object" &&
          payload !== null &&
          "type" in payload &&
          typeof payload.type === "string" &&
          LIVE_EVENT_TYPES.has(payload.type)
        ) {
          onEvent(payload as LiveEvent);
        }
      };

      socket.onclose = () => {
        onConnection(false);
        if (!stopped) {
          retryTimer = window.setTimeout(connect, 1500);
        }
      };

      socket.onerror = () => socket?.close();
    };

    connect();

    return () => {
      stopped = true;
      if (retryTimer !== null) window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, [onConnection, onEvent]);
}
