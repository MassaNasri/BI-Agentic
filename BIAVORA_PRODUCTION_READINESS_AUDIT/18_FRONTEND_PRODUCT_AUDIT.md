# 18 — Frontend and Product Audit

## Verdict

The React/Vite frontend supports authentication, workspace navigation, data-source management, subscription screens, voice/report interactions and visualization flows. It is a functional prototype with material product breadth, but not a production-ready surface for the Week-14 public scope. The build passes; the main chunk is **671.84 kB** (194.57 kB gzip), tests cover only 19 cases across three files, and Arabic/RTL, accessibility, robust payment and long-running job UX are missing.

## Architecture

- Routing and most feature orchestration are centralized in large components. `DashboardShell.jsx` exceeds 1,200 lines; `DatabaseManagement.jsx` is about 969, `Profile.jsx` about 790, and `VoiceReportManager.jsx` about 787.
- API access patterns and error/loading behavior are duplicated across components rather than expressed as a typed, consistent client/query layer.
- No dynamic imports were found for route-level splitting. The production build warns about a chunk over 500 kB.
- Workspace context exists, but every request should bind workspace through one tested API layer and clear workspace-scoped caches on switching.
- Polling is used for some asynchronous behavior. Future ingestion/analysis/action jobs need a common job-status model; SSE can be considered for progress after the gateway supports streaming.

Recommended target: feature folders with route-level boundaries, a single typed API client, server-state/query cache keyed by workspace and resource, small accessible components, and a common `JobProgress`/error contract. This is a refactor, not a framework rewrite.

## Authentication and security

Access/refresh tokens are stored in `localStorage`, exposing them to XSS. Move toward memory-held access tokens and rotated `HttpOnly` refresh cookies with a CSRF design. Add a restrictive CSP and explicitly review every place that could render report/model/document content. Do not collect payment card, CVV or bank details in BIAVORA components; redirect/embed a provider-hosted, PCI-scoped checkout.

Frontend authorization is presentation only. Backend services must enforce workspace/role/entitlement checks. Physical ClickHouse identifiers should not be serialized to ordinary clients.

## UX state audit

| Area | Current/observed | Needed |
|---|---|---|
| Loading/errors | Implemented inconsistently per component | Shared recoverable error boundary, retry policy, trace ID and actionable empty states |
| Long tasks | Polling/request-oriented | Durable job timeline, cancel/retry, background notification and reconnect behavior |
| Data sources | Snapshot flows exist | Persistent source inventory, secret-reference state, connection test, CDC mode/lag/schema history |
| Reports | Voice-owned workflow exposed through report proxy | Unified report ownership, paginated results, provenance/freshness/trust panel |
| Subscription | Simulated card/bank form | Hosted checkout, verified status, invoices, entitlements, usage ledger and cost explanation |
| Workspace | Core selection exists | Strong cache isolation, role/permission visibility and invite/admin journeys |
| Accessibility | Not demonstrated | Keyboard/focus, semantic landmarks, labels, contrast, screen reader and automated/manual WCAG checks |
| Responsive | Unverified | Mobile/tablet layouts for core view/read workflows; constrain complex modeling on small screens |

## Arabic and localization

The root UI declares English (`lang="en"`) and no production i18n/RTL framework was found. Generic Whisper language support is not equivalent to an Arabic product. Add locale routing and translation catalogs, `dir="rtl"`, logical CSS properties, mirrored directional icons where appropriate, Arabic plural/number/date/currency formatting, bidi-safe SQL/identifiers, mixed Arabic-English input, and localized validation/errors. Test Syrian/Levantine plus Modern Standard Arabic business terminology and code switching with native reviewers.

## Week-14 production screens

Minimum new or redesigned surfaces:

1. **Integration/source detail:** ownership, transport, credentials reference, tested status, tables, snapshot/CDC state, lag and errors.
2. **Semantic model studio:** entities, joins, metrics/dimensions, proposal diff/explanation, approve/version/publish/rollback.
3. **Analyst workspace:** question, plan/tool status, result, visualization and a trust drawer containing SQL/metric/source/freshness/citations.
4. **Knowledge library:** upload/scan/index status, document permissions/version/deletion and citation navigation.
5. **Monitoring/reliability:** metric monitors, thresholds, incidents, evidence, deduplication and notification history.
6. **What-if:** explicit baseline, editable assumptions, scenario version, uncertainty and comparison—never causal wording without evidence.
7. **Action approvals:** proposed typed command, scope/risk/diff, expiry, approve/reject, execution result and audit history.
8. **Usage/billing:** entitlements, reserved/committed/refunded units, category breakdown, limits/alerts and provider checkout state.

## Performance and caching

Split routes and heavy visualization/modeling dependencies; measure bundle budgets per route. Paginate/virtualize large tables and never place full analytical datasets in component state. Cache stable metadata by workspace/version while invalidating on source/semantic publication. Use AbortController for abandoned requests and pass cancellation to jobs. Measure Web Vitals and interaction latency on representative low-end devices.

## Test strategy

Add component tests for loading/error/permission states, accessibility checks, API contract fixtures and locale/RTL snapshots. Browser E2E should cover signup/login/refresh, workspace switching, source snapshot, question/report/trust, subscription checkout return, upload/index/search, approval and token expiry. Include cross-tenant cache tests and mobile viewports. Keep the existing 19 tests, but they are insufficient as a release gate.

## Product recommendations

- Make trust evidence part of every analytical result, not a separate technical page.
- Present snapshot versus CDC status precisely; never label polling/incremental refresh as CDC.
- Disclose provider/data egress and cost-impact categories before expensive work.
- Prefer one coherent analyst workflow over separate market-driven “agent” pages.
- Defer visual polish until secure job, semantic, trust and usage contracts stabilize; design those contracts with frontend states now.

