import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "maplibre-gl/dist/maplibre-gl.css";

import App from "./App";
import { PilotBootstrap } from "./PilotBootstrap";
import "./styles.css";

const pilotRoute =
  window.location.pathname === "/pilot" ||
  window.location.pathname.startsWith("/pilot/");

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    {pilotRoute ? <PilotBootstrap /> : <App />}
  </StrictMode>,
);
