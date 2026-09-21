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
}

declare global {
  interface Window {
    djiBridge?: DjiBridge;
    m3CloudThingConnectCallback?: (value: unknown) => void;
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

export function PilotBootstrap() {
  const [status, setStatus] = useState("Loading M3-Cloud configuration…");
  const [detail, setDetail] = useState("");
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let cancelled = false;

    async function run() {
      const response = await fetch("/api/v1/dji/pilot/bootstrap", {
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
      delete window.m3CloudLiveStatusCallback;
    };
  }, []);

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
