import { useEffect, useState } from "react";

type BridgeValue = string | boolean | number | null | undefined;

interface DjiBridge {
  platformVerifyLicense(appId: string, appKey: string, license: string): BridgeValue;
  platformLoadComponent(name: string, param: string): BridgeValue;
  platformSetWorkspaceId(uuid: string): BridgeValue;
  platformSetInformation(
    platformName: string,
    workspaceName: string,
    desc: string,
  ): BridgeValue;
  platformGetRemoteControllerSN(): string;
  platformGetAircraftSN(): string;
  apiSetToken(token: string): BridgeValue;
  thingGetConnectState(): boolean;
  wsGetConnectState(): boolean;
}

declare global {
  interface Window {
    djiBridge?: DjiBridge;
    m3CloudThingConnectCallback?: (value: unknown) => void;
    m3CloudWsConnectCallback?: (value: unknown) => void;
    m3CloudLiveStatusCallback?: (value: unknown) => void;
  }
}

interface Bootstrap {
  ready: boolean;
  missing: string[];
  invalid: string[];
  license: {
    app_id: string;
    app_key: string;
    license: string;
  };
  workspace: {
    id: string;
    platform_name: string;
    name: string;
    description: string;
  };
  api: {
    host: string;
    token: string;
  };
  thing: {
    host: string;
    username: string;
    password: string;
  };
  ws: {
    host: string;
    token: string;
  };
  map: {
    user_name: string;
    element_pre_name: string;
  };
  media: {
    auto_upload_photo: boolean;
    auto_upload_photo_type: number;
    auto_upload_video: boolean;
  };
  liveshare: {
    video_publish_type: string;
  };
  components: {
    api: boolean;
    thing: boolean;
    liveshare: boolean;
    ws: boolean;
    map: boolean;
    tsa: boolean;
    media: boolean;
    mission: boolean;
  };
}

function bridgeResult(label: string, value: BridgeValue): void {
  if (value === undefined || value === null || value === "") return;
  if (typeof value === "boolean") {
    if (!value) throw new Error(`${label} returned false`);
    return;
  }
  if (typeof value !== "string") return;

  try {
    const parsed = JSON.parse(value) as { code?: number; message?: string };
    if (typeof parsed.code === "number" && parsed.code !== 0) {
      throw new Error(`${label}: ${parsed.message ?? `code ${parsed.code}`}`);
    }
  } catch (error) {
    if (error instanceof SyntaxError) return;
    throw error;
  }
}

function loadComponent(
  bridge: DjiBridge,
  name: string,
  params: Record<string, unknown>,
): void {
  bridgeResult(
    `platformLoadComponent(${name})`,
    bridge.platformLoadComponent(name, JSON.stringify(params)),
  );
}

function sleep(milliseconds: number): Promise<void> {
  return new Promise((resolve) => window.setTimeout(resolve, milliseconds));
}

async function waitForThing(bridge: DjiBridge): Promise<void> {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (bridge.thingGetConnectState()) return;
    await sleep(500);
  }
  throw new Error("DJI Pilot 2 MQTT connection did not become ready");
}

async function waitForWs(bridge: DjiBridge): Promise<void> {
  for (let attempt = 0; attempt < 40; attempt += 1) {
    if (bridge.wsGetConnectState()) return;
    await sleep(500);
  }
  throw new Error("DJI Pilot 2 WebSocket connection did not become ready");
}

async function waitForBackendDji(): Promise<void> {
  let lastStatus = "unknown";
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const response = await fetch("/api/v1/system/health", {
        cache: "no-store",
      });
      if (response.ok) {
        const value = (await response.json()) as {
          components?: {
            dji?: {
              ok?: boolean;
              status?: string;
              last_reason?: string;
            };
          };
        };
        const dji = value.components?.dji;
        if (dji?.ok === true) return;
        lastStatus = dji?.last_reason
          ? `${dji.status ?? "disconnected"}: ${dji.last_reason}`
          : dji?.status ?? "disconnected";
      } else {
        lastStatus = `HTTP ${response.status}`;
      }
    } catch (error) {
      lastStatus = error instanceof Error ? error.message : String(error);
    }
    await sleep(500);
  }
  throw new Error(
    `M3-Cloud DJI MQTT consumer did not become ready (${lastStatus})`,
  );
}

export function PilotBootstrap() {
  const [status, setStatus] = useState("Enter the M3-Cloud bootstrap token");
  const [detail, setDetail] = useState("");
  const [connected, setConnected] = useState(false);
  const [tokenInput, setTokenInput] = useState("");
  const [attempt, setAttempt] = useState<{ token: string; id: number } | null>(null);

  useEffect(() => {
    if (attempt === null) return;

    let cancelled = false;

    async function run() {
      const response = await fetch("/api/v1/dji/pilot/bootstrap", {
        method: "POST",
        headers: {
          "X-M3-Pilot-Bootstrap": attempt.token,
        },
        cache: "no-store",
      });
      if (!response.ok) {
        throw new Error(`Bootstrap request failed: HTTP ${response.status}`);
      }

      const config = (await response.json()) as Bootstrap;
      if (!config.ready) {
        const problems = [
          ...config.missing.map((item) => `missing: ${item}`),
          ...config.invalid.map((item) => `invalid: ${item}`),
        ];
        setStatus("DJI Pilot 2 integration is not configured");
        setDetail(problems.join(", "));
        return;
      }

      const bridge = window.djiBridge;
      if (!bridge) {
        setStatus("Open this page inside DJI Pilot 2");
        setDetail("window.djiBridge is unavailable in a normal browser.");
        return;
      }

      setStatus("Verifying DJI Cloud API license…");
      bridgeResult(
        "platformVerifyLicense",
        bridge.platformVerifyLicense(
          config.license.app_id,
          config.license.app_key,
          config.license.license,
        ),
      );

      if (config.components.api) {
        setStatus("Loading DJI HTTPS API module…");
        loadComponent(bridge, "api", {
          host: config.api.host,
          token: config.api.token,
        });
        bridgeResult("apiSetToken", bridge.apiSetToken(config.api.token));
      }

      window.m3CloudThingConnectCallback = (value: unknown) => {
        if (!cancelled) setDetail(`MQTT: ${String(value)}`);
      };
      window.m3CloudWsConnectCallback = (value: unknown) => {
        if (!cancelled) setDetail(`WebSocket: ${String(value)}`);
      };
      window.m3CloudLiveStatusCallback = (value: unknown) => {
        if (!cancelled) setDetail(`Live: ${String(value)}`);
      };

      if (config.components.thing) {
        setStatus("Connecting DJI Pilot 2 to M3-Cloud MQTT…");
        loadComponent(bridge, "thing", {
          host: config.thing.host,
          username: config.thing.username,
          password: config.thing.password,
          connectCallback: "m3CloudThingConnectCallback",
        });
        await waitForThing(bridge);
      }

      setStatus("Registering M3-Cloud workspace…");
      bridgeResult(
        "platformSetWorkspaceId",
        bridge.platformSetWorkspaceId(config.workspace.id),
      );
      bridgeResult(
        "platformSetInformation",
        bridge.platformSetInformation(
          config.workspace.platform_name,
          config.workspace.name,
          config.workspace.description,
        ),
      );

      if (config.components.ws) {
        setStatus("Connecting DJI Pilot 2 WebSocket…");
        loadComponent(bridge, "ws", {
          host: config.ws.host,
          token: config.ws.token,
          connectCallback: "m3CloudWsConnectCallback",
        });
        await waitForWs(bridge);
      }

      setStatus("Verifying M3-Cloud DJI MQTT consumer…");
      await waitForBackendDji();

      if (config.components.map) {
        setStatus("Loading DJI map elements…");
        loadComponent(bridge, "map", {
          userName: config.map.user_name,
          elementPreName: config.map.element_pre_name,
        });
      }

      if (config.components.tsa) {
        setStatus("Loading DJI situation awareness…");
        loadComponent(bridge, "tsa", {});
      }

      if (config.components.mission) {
        setStatus("Loading DJI mission library…");
        loadComponent(bridge, "mission", {});
      }

      if (config.components.media) {
        setStatus("Loading DJI media management…");
        loadComponent(bridge, "media", {
          autoUploadPhoto: config.media.auto_upload_photo,
          autoUploadPhotoType: config.media.auto_upload_photo_type,
          autoUploadVideo: config.media.auto_upload_video,
        });
      }

      if (config.components.liveshare) {
        loadComponent(bridge, "liveshare", {
          videoPublishType: config.liveshare.video_publish_type,
          statusCallback: "m3CloudLiveStatusCallback",
        });
      }

      if (!cancelled) {
        const rc = bridge.platformGetRemoteControllerSN?.() || "unknown";
        const aircraft = bridge.platformGetAircraftSN?.() || "not connected";
        setConnected(true);
        setStatus("M3-Cloud connected");
        setDetail(`RC: ${rc} · Aircraft: ${aircraft}`);
      }
    }

    void run().catch((error: unknown) => {
      if (cancelled) return;
      setConnected(false);
      setStatus("DJI Pilot 2 bootstrap failed");
      setDetail(error instanceof Error ? error.message : String(error));
    });

    return () => {
      cancelled = true;
      delete window.m3CloudThingConnectCallback;
      delete window.m3CloudWsConnectCallback;
      delete window.m3CloudLiveStatusCallback;
    };
  }, [attempt]);

  const connect = () => {
    const token = tokenInput.trim();
    if (!token) {
      setConnected(false);
      setStatus("Bootstrap token required");
      setDetail("Enter M3CLOUD_DJI_PILOT_BOOTSTRAP_TOKEN.");
      return;
    }
    setConnected(false);
    setStatus("Loading M3-Cloud configuration…");
    setDetail("");
    setAttempt({ token, id: Date.now() });
  };

  return (
    <main
      style={{
        minHeight: "100vh",
        display: "grid",
        placeItems: "center",
        padding: "24px",
        background: "#0b1117",
        color: "#e6edf3",
        fontFamily: "system-ui, sans-serif",
      }}
    >
      <section
        style={{
          width: "min(680px, 100%)",
          padding: "28px",
          border: "1px solid #30363d",
          borderRadius: "14px",
          background: "#161b22",
        }}
      >
        <div style={{ fontSize: "13px", opacity: 0.7 }}>DJI PILOT 2 · CLOUD API</div>
        <h1 style={{ margin: "8px 0 12px" }}>M3-Cloud</h1>
        <p style={{ fontSize: "18px", margin: "0 0 12px" }}>{status}</p>
        <p style={{ opacity: 0.75, overflowWrap: "anywhere" }}>{detail || " "}</p>
        {!connected && (
          <div style={{ display: "grid", gap: "10px", margin: "18px 0" }}>
            <input
              type="password"
              value={tokenInput}
              onChange={(event) => setTokenInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") connect();
              }}
              placeholder="M3CLOUD_DJI_PILOT_BOOTSTRAP_TOKEN"
              autoComplete="off"
              style={{
                width: "100%",
                boxSizing: "border-box",
                padding: "11px 12px",
                borderRadius: "8px",
                border: "1px solid #30363d",
                background: "#0d1117",
                color: "#e6edf3",
              }}
            />
            <button
              type="button"
              onClick={connect}
              style={{
                padding: "11px 14px",
                borderRadius: "8px",
                border: "1px solid #30363d",
                cursor: "pointer",
              }}
            >
              Connect Pilot 2
            </button>
          </div>
        )}
        <div
          style={{
            marginTop: "18px",
            padding: "10px 12px",
            borderRadius: "8px",
            background: connected ? "#12351f" : "#2b2220",
          }}
        >
          {connected ? "Cloud link ready" : "Cloud link not ready"}
        </div>
      </section>
    </main>
  );
}
