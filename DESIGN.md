---
version: alpha
name: "M3-Cloud"
description: "Dark, field-oriented DJI Enterprise operations interface for fleet, mission, media and processing work."
colors:
  background: "#090D13"
  surface: "#111821"
  surfaceElevated: "#17212C"
  surfaceInset: "#0E151E"
  border: "#263342"
  text: "#EDF3F8"
  muted: "#8796A7"
  primary: "#4FC3B6"
  info: "#69A9FF"
  warning: "#E7B34C"
  success: "#55D58A"
  danger: "#EF7272"
  focus: "#8BE8DD"
  scrollbarTrack: "#0B1118"
  scrollbarThumb: "#34495B"
typography:
  sans:
    fontFamily: "Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, \"Segoe UI\", sans-serif"
  mono:
    fontFamily: "ui-monospace, \"SFMono-Regular\", Consolas, \"Liberation Mono\", monospace"
rounded:
  sm: "0.375rem"
  DEFAULT: "0.5rem"
  md: "0.625rem"
  lg: "0.75rem"
spacing:
  control: "0.5rem"
  panel: "0.75rem"
  section: "1rem"
components:
  button:
    minHeight: "2.25rem"
  panel:
    borderWidth: "1px"
  status:
    radius: "999px"
---

# M3-Cloud Design System

## Overview

### Creative North Star

The interface takes its cues from an aircraft operations console: dark anti-glare surfaces, restrained instrument color, compact but readable status bands, and technical data that is easy to scan under time pressure. It must feel like an operational tool, not a consumer dashboard or a marketing control center.

### Product context and register

- **Audience and primary job:** Operators and maintainers working with DJI Enterprise aircraft, missions, telemetry, media, thermal data and mapping workflows.
- **Target market(s) and evidence:** The repository is self-hosted and deployment-oriented rather than market-branded. No country-specific business behavior is inferred from the German UI locale.
- **Locale(s) and language policy:** The application document uses German. Established aviation, DJI, RTK, payload and processing terminology may remain English where it is the product/domain term.
- **Usage scene:** Desktop and controller-adjacent browser use, often with dense live or historical data. Narrow tablet layouts remain supported.
- **Register:** Product.
- **Memorable signature:** A persistent operations-context strip directly below the page header keeps live connection, selected aircraft, positioning state and data freshness visible across work areas.
- **Restraint:** Maps, tables, mission controls and processing states remain visually quiet. Semantic colors are reserved for state and consequence.
- **Anti-references:** No marketing hero treatments, glassmorphism, decorative gradients, neon cyberpunk styling, oversized KPI typography, or card-heavy layouts without operational meaning.
- **Token ownership/runtime mapping:** Existing runtime CSS remains canonical (Model B). This file mirrors accepted values from frontend/src/styles.css and frontend/src/premium.css. Shared components consume the existing CSS variables and semantic additions; durable changes must update runtime CSS and this file together.

## Colors

The application is dark-only today. background is the document field; surface and surfaceElevated define the main depth steps; surfaceInset is for nested data regions. border separates without creating card noise. primary is the M3-Cloud data/system accent. info, warning, success and danger are semantic and must not be used as decoration. focus is intentionally brighter than primary so keyboard focus remains distinct from selection.

Semantic state must never rely on color alone: labels, icons or text state accompany color. Thermal imagery keeps its own scientific/display palette inside media content and does not redefine application semantics.

## Typography

sans is the interface family and preserves the existing runtime stack. mono is reserved for serials, hashes, coordinates, command identifiers, timestamps and other machine-readable values. Tabular numbers should be used for changing metrics.

Body and control text must remain readable at normal browser zoom; 8–10 px legacy labels are migration debt and new UI must not introduce them. Uppercase is limited to short technical state codes such as FIXED, RTK or ONLINE, never paragraphs or primary actions.

## Layout

The desktop shell uses persistent left navigation and one canonical application content scroller. The main work surface owns vertical scrolling through the view region; individual tables, rails, map overlays and menus may own bounded internal scrolling when their content model requires it.

The shell transforms to a horizontal, scrollable navigation band on narrow screens instead of collapsing labels into ambiguous icons. Maps keep explicit minimum geometry. Forms and long content remain reachable without inheriting table-specific height constraints. Scrollbar gutters are stable on primary scroll surfaces.

Spacing is compact but not microscopic: control spacing is 0.5rem, panel rhythm 0.75rem, and major section separation 1rem. Touch-important controls target roughly 40–44 px where layout permits; the absolute minimum interactive target is never below the WCAG 2.2 AA baseline.

## Elevation & Depth

Hierarchy is tonal and border-led. Static panels do not use decorative drop shadows. Selection may use an inset primary edge. Floating map notices and future dialogs may use shadow only to establish a true layer over content.

## Shapes

Controls use sm/DEFAULT radii; panels use md/lg. Status pills may use a full radius. Repeated arbitrary radii are not introduced at screen level. Borders remain one pixel unless focus or a selected edge requires stronger emphasis.

## Components

### Foundational visual states

Every interactive shared control has default, hover, focus-visible, active, disabled and busy states. Selection is separate from focus. Busy state preserves control dimensions and exposes aria-busy. The default loading treatment is a compact app-owned spinner in reserved space. Skeletons are not part of the current contract.

### Buttons and actions

Buttons combine emphasis and semantic intent. Safe primary actions may use the primary accent; routine utilities remain neutral. Warning and danger are reserved for real consequences. Busy controls retain their original label geometry and cannot be double-activated.

### Navigation and data display

Top-level navigation uses real anchors and URL hash state so browser Back/Forward and deep links work without adding a routing dependency. The current destination uses aria-current. Dense tabular content stays tabular when cross-row comparison matters and scrolls horizontally when necessary.

The operations-context strip is the signature shared data surface. It shows only facts that are meaningful across routes: connection, selected aircraft, positioning and refresh freshness.

### Forms and overlays

Simple single-select fields use native select ownership while platform popup geometry is acceptable. Fields keep visible labels or explicit accessible names. Product-native dialogs, not browser alert/confirm/prompt, are required when confirmation is introduced. Inline persistent alerts are preferred for recoverable screen failures.

### Iconography

No icon package is currently canonical. Text labels remain mandatory for primary operations. Small symbols may supplement state, but never become the sole accessible name.

### Motion

Motion is restrained and state-driven. Hover/focus transitions are short and subtle. Loading spinners communicate active work. Under prefers-reduced-motion, nonessential transitions stop and the spinner remains perceivable without decorative movement.

### Content and data visualization

Copy names the operator-visible action and outcome. Do not claim mission execution where the backend only uploads or verifies a handoff. Thermal capture-center data must not be described as pixel georeferencing. Raw server payloads are not user-facing error copy.

## Do's and Don'ts

- **Do:** Keep flight-critical and processing provenance visible near the data it qualifies.
- **Do:** Reuse semantic tokens and shared state vocabulary across Fleet, Missions, Media, Processing and Projects.
- **Don't:** Use primary, warning or danger color simply to make a panel more visually interesting.
- **Don't:** Hide navigation labels, scrollbars, focus rings or recovery controls for aesthetic minimalism.
