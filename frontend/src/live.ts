import { useEffect } from "react";

import { liveWebSocketUrl } from "./api";
import type { TelemetryEvent } from "./types";

export function useLiveTelemetry(
  onTelemetry: (event: TelemetryEvent) => void,
  onConnection: (connected: boolean) => void,
): void {
  useEffect(() => {
    let socket: WebSocket | null = null;
    let retryTimer: number | null = null;
    let stopped = false;

    const connect = () => {
      if (stopped) {
        return;
      }

      socket = new WebSocket(liveWebSocketUrl());

      socket.onopen = () => {
        onConnection(true);
      };

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
          payload.type === "telemetry"
        ) {
          onTelemetry(payload as TelemetryEvent);
        }
      };

      socket.onclose = () => {
        onConnection(false);
        if (!stopped) {
          retryTimer = window.setTimeout(connect, 2000);
        }
      };

      socket.onerror = () => {
        socket?.close();
      };
    };

    connect();

    return () => {
      stopped = true;
      if (retryTimer !== null) {
        window.clearTimeout(retryTimer);
      }
      socket?.close();
    };
  }, [onConnection, onTelemetry]);
}
