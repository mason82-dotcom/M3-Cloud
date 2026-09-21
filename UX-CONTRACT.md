# M3-Cloud UX Contract

## Product context

- Audience: DJI Enterprise operators and maintainers using fleet, mission, media, thermal and mapping workflows.
- Primary jobs: assess aircraft/RTK state, plan and audit missions, inspect recorded flights, catalogue source media, launch/track processing, and preserve project/survey lineage.
- Target market(s): deployment-neutral; no market-specific policy is inferred from locale.
- Active locales: de (current application document). Established DJI/aviation technical terms may remain English.
- Language/content register and native-review policy: concise operational German with stable domain terminology; review new flight-safety wording against maintained product/domain sources.
- Timezone/calendar policy: display local browser time for UI freshness unless an API/domain field defines another timezone; never reinterpret date-only or source capture timestamps silently.
- Accessibility target: WCAG 2.2 AA.

## Business-context sources

| Domain / scope | Authoritative source | Source type | Reviewed date |
|---|---|---|---|
| Product architecture and operational workflows | README.md | Product/architecture brief | 2026-09-21 |
| Mission handoff and upload verification | README.md, “Mission handoff upload” | Domain/API behavior | 2026-09-21 |
| M4T payload/thermal provenance | docs/m4t-rc-plus2.md | Platform/domain contract | 2026-09-21 |
| DJI Pilot 2 integration and security boundary | docs/dji-pilot2.md | Integration/security brief | 2026-09-21 |
| Permission model | No maintained frontend permission policy located | Unresolved; do not invent role behavior | 2026-09-21 |
| Deletion / retention | No destructive lifecycle contract located for current frontend workflows | Unresolved; no generic delete behavior may be added | 2026-09-21 |
| Billing / payment | Not present in current product scope | n/a | 2026-09-21 |
| Legal / regulatory copy | No legal copy source located | Unresolved; do not invent regulated claims | 2026-09-21 |

## Visual contract

- Project DESIGN.md: DESIGN.md.
- Token ownership model: existing runtime canonical (Model B).
- Runtime design-system/token source: frontend/src/styles.css plus frontend/src/premium.css.
- Mapping/export/adapters: DESIGN.md semantic roles map to existing CSS custom properties; premium.css adds focus/scroll/state tokens without duplicating feature-local values.
- Token drift gate: DESIGN.md lint plus review of CSS custom-property values when durable tokens change.
- Supported themes: dark.
- Design-context owner/review policy: system-level visual changes update DESIGN.md and runtime CSS in the same changeset.

## Canonical UI Map

| Capability | Canonical owner | Source of truth | Allowed variants | Verification |
|---|---|---|---|---|
| Select/Listbox | Native HTML select for current simple single-select fields | UX-CONTRACT.md + feature labels | native; authored only after an explicit popup-geometry requirement | keyboard + real popup |
| Scrollbar | frontend/src/premium.css application baseline | DESIGN.md | stable-gutter/compact geometry exceptions | computed style |
| CRUD | Feature API workflow + this flow ledger | README/API behavior + UX-CONTRACT.md | stay-in-context for current create/assign flows | full-flow E2E |
| Button/busy state | frontend/src/ui.tsx ActionButton for shared shell actions; global state baseline for legacy feature buttons | DESIGN.md + UX-CONTRACT.md | neutral/primary/warning/danger with emphasis | keyboard + busy geometry |
| Loading/status | frontend/src/ui.tsx LoadingBlock and persistent inline/context status | UX-CONTRACT.md | initial / refresh / mutation | state matrix |

Table selection, authored date pickers and a toast provider are not current canonical capabilities. They must be resolved before a feature introduces them.

## Component behavior

| Component | Default | Hover | Focus | Active | Disabled | Busy | Error |
|---|---|---|---|---|---|---|---|
| Button | semantic button, stable label | tonal/border change | visible 2 px focus ring | slight pressed contrast | non-interactive, dimmed | aria-busy, stable geometry, duplicate blocked | persistent inline recovery when action fails |
| Icon button | only when icon is universally understood; accessible name required | same | same | same | same | same | same |
| Input | labeled, semantic type | border emphasis | focus ring + border | n/a | dimmed/non-interactive | feature-specific | associated text; entered non-sensitive value preserved |
| Search | clear + 300 ms remote debounce when introduced | n/a | visible ring | n/a | dimmed | reserved adornment | retry/no-results distinct |
| Textarea | resize none when introduced | border emphasis | focus ring | n/a | dimmed | feature-specific | associated text |
| Table/list | bounded navigation strategy for unbounded data | row emphasis only when interactive | focused control visible | selection distinct from focus | n/a | stable frame | retry or persistent panel error |

## Dataset navigation

- Admin tables: use server pagination when an endpoint can grow without a known small bound; do not add client pagination over partial server results.
- Exploratory lists: explicit Load more unless the product intentionally becomes a continuous feed.
- URL state: top-level work area is URL-restorable now. New committed search/filter/sort/page state must also be URL-restorable unless sensitive or technically constrained.
- Page size: endpoint-specific; define before introducing pagination.
- Empty/no-results/error/loading treatment: empty explains what belongs in the region; no-results offers filter reset; error gives retry; loading preserves the frame.
- Back/scroll restoration: browser Back restores top-level view; feature routes must preserve committed list state when introduced.
- Selection scope: not yet used for bulk table selection; resolve before implementation.

## Flow ledger

| Operation | Trigger | Pending | Success destination | Success feedback | Failure recovery | Focus outcome | Source ref |
|---|---|---|---|---|---|---|---|
| Refresh fleet/system | Aktualisieren | stable busy button; existing data remains | same view | freshness timestamp/context state | context indicates stale/failure; retry remains available | trigger remains logical focus | README.md fleet dashboard |
| Create project/survey/mission | explicit create action | disable duplicate mutation | stay in owning workspace and select created object | updated object/list becomes visible | preserve entered values; persistent inline error | created object or owning list context | current API/workflow implementation |
| Assign flight/dataset | explicit assignment | block duplicate assignment | stay in survey context | updated lineage | preserve current selection; inline error + retry | assignment control | README.md Projects and surveys |
| Mission handoff upload | Upload | pessimistic; disable duplicate | stay in mission deployment | only report verified uploaded state after server/readback contract | retain deployment/error state; retry only when API makes outcome safe | upload control/deployment row | README.md Mission handoff upload |
| Processing job | explicit processing action | pessimistic job creation, then persistent job state | Processing workspace | server-confirmed job/state | retain source selection and show retryable failure | job/source context | README.md processing workflows |
| Cancel/back | Cancel/Back where present | none | originating context | none | unsaved guard when a true edit form is introduced | originating trigger/context | UX-CONTRACT.md |

No generic delete, hard-delete, permission-changing or billing flow is defined. Those remain blocked pending authoritative domain policy.

## Navigation and responsive behavior

- Route document title policy: “{Page} — M3-Cloud”; Operations uses “Operations — M3-Cloud”. Loading/error state may prefix the current page when it materially changes orientation.
- Route error / 403 page behavior: no permission model is currently defined. A future 403 must be distinct from 404 and must not expose hidden data.
- Breadcrumb/tab/route-state policy: top-level navigation uses hash routes without a routing dependency; active destination is aria-current=page. In-page tabs use proper tabs only when views are peers of one context.
- Sidebar/drawer/bottom-sheet transformation: persistent left sidebar on wide screens; horizontal scrollable labeled nav on narrow screens. No icon-only collapsed rail.
- Responsive table strategy: preserve comparison tables with obvious horizontal scroll; do not silently hide columns.
- Truncation/full-value access: identifiers may visually truncate only when full value remains reachable by focus/copy/detail.
- Focus restoration and sticky-obstruction policy: focus-visible must remain unobscured; use scroll-margin/padding rather than delayed focus hacks.

## Overlays and feedback

- Dialog primitive: none is currently canonical because the current web frontend has no confirmation flow. Before adding one, adopt a proven accessible dialog primitive and record the owner here.
- Destructive confirmation levels: unresolved until the domain defines reversible vs irreversible lifecycle.
- Toast placement/duration/deduplication: no toast provider is currently canonical. Persistent inline/context feedback is the supported mechanism until one shared provider is introduced.
- Alert/banner scope and persistence: connection/freshness belongs in the persistent context strip; scoped failures stay with the affected panel/action.
- Tooltip delay/dismissal: tooltips supplement icon-only/technical hints; never carry essential instructions.
- Unsaved-changes behavior: required before introducing a dirty edit form.
- Layer/z-index contract: map controls < map notices < authored popover < future dialog < future toast. A real dialog owner must formalize exact tokens.

## Async and resilience

- Mutation default: pessimistic for mission upload, processing creation, assignments and other externally meaningful work. Optimistic behavior requires an explicit idempotent rollback-safe contract.
- Idempotency and duplicate-submit policy: busy actions cannot be activated twice; mission upload follows server-side verification/idempotency behavior.
- Auto-save/draft recovery: not currently implemented; do not add silently.
- Offline/read-stale/write behavior: preserve readable stale data; do not claim live/saved state when requests fail. Writes are not queued.
- Retry/backoff/timeout behavior: explicit retry for user-triggered reads; background polling stays bounded by existing intervals and must not create overlapping refreshes.
- Version conflict and multi-tab behavior: not currently defined; do not silently overwrite server conflicts when versioning is introduced.
- Session expiry/re-authentication: no auth contract located; resolve before implementation.
- Long-running progress and return path: processing jobs expose persistent server state; do not fake percentages.
- Stale-request cancellation/invalidation and pending-state ownership: effects use cancellation/ignore guards; top-level refresh prevents overlap.
- Dialog/form preservation and retry after mutation failure: preserve non-sensitive user input and keep the actionable surface open.

## Validation

- Schema/validation layer: current simple controls use explicit client preconditions plus server validation.
- Trigger timing: validate on action, then on change for a field already in error when richer forms are introduced.
- Error summary/inline policy: concise inline/panel error; long forms require first-error focus and a summary.
- Server error mapping: translate to operator-facing text at the feature boundary; raw payloads/stack traces are not presentation copy.
- Sensitive-value handling: secrets never enter route state, toast/status text, analytics or persistent client storage without a security design.
- noValidate, first-invalid focus, duplicate-submit prevention, unsaved changes, and submit recovery: mandatory for future semantic form elements.

## Permission and clipboard

- Permission UI strategy: unresolved because no maintained permission policy was located. Do not infer hide/disable/403 behavior.
- Clipboard copy policy: technical identifiers may add an explicit copy action; do not put secrets in feedback text.
- Disabled-state explanation: explain non-obvious unavailability adjacent to the control or through an accessible tooltip.

## Migration status

- Migration ledger location: this section.
- Canonical primitives and owners: app shell/hash navigation, operations-context strip, global scrollbar/focus baseline, shared ActionButton/LoadingBlock.
- Current risk-prioritized slices: app shell and fleet/system refresh first; mission/processing actions retain business semantics while shared states are introduced incrementally.
- Legacy import/token enforcement: new work must use semantic CSS variables and the shared shell primitives; screen-local button state families are migration debt.
- Rollout/rollback and removal gates: migrate complete workflows; do not remove a legacy pattern until its callers and verification are complete.

| Surface | Current state | Canonical target | Risk | Status |
|---|---|---|---|---|
| App shell / Operations / Fleet | local-only nav, weak refresh state | URL-restorable shell + context strip + shared busy/loading | medium | migrating |
| Missions | strong domain safeguards, screen-local controls | preserve safeguards; migrate complete action/state patterns | high | inventoried |
| Processing | persistent jobs, mixed screen-local feedback | shared async/status vocabulary without weakening provenance | high | inventoried |
| Projects | create/assign flows, shared global busy flag | operation-scoped busy/error states | medium | inventoried |
| Media / Flights | read-heavy with map/list state | bounded loading/error/search/navigation contracts | medium | inventoried |

## Verification

- Required static commands: npm run typecheck; npm run build; premium static audit when a checkout with the installed skill is available.
- Browser/device/locale/theme matrix: desktop wide, small laptop, narrow tablet/phone; German; dark; reduced motion; slow/offline/failure states.
- Accessibility checks: keyboard-only navigation, visible focus, semantic names/current state, stable busy controls, contrast, narrow reflow.
- Native-language/domain review and target-user evidence: operational terminology is grounded in repository docs; new safety claims require domain review.
- Component-state/visual regression coverage: add when project test/story tooling is introduced.
- Canonical sibling flow used for comparison: existing Fleet/Flights read-state behavior and Missions/Processing long-running state behavior.
- Project audit command/result: pending until a complete checkout can run the premium skill auditor.
- CRUD full-flow evidence: existing project/mission endpoints plus CI build; browser E2E is not yet present in repository.
- Failure-path evidence: inline failure states and server job/deployment status are retained; automated browser failure-path tests are not yet present.
