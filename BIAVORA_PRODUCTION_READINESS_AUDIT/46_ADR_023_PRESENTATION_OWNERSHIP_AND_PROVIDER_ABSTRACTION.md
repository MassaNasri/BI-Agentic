# ADR-023 — Presentation Generation Ownership and Provider Abstraction

Date: 2026-10-27. Status: **Accepted for implementation planning**, not implemented. ADR numbering continues 001–022 in [24](24_ARCHITECTURE_DECISION_RECORDS_NEEDED.md). Governing scope: [43](43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md); detailed contracts: [44](44_AI_PRESENTATION_AND_EXECUTIVE_REPORT_ARCHITECTURE.md).

## Context and evidence

`services/report-service/service_config/settings.py` does not install the duplicate `voice_reports` domain app. `service_config/urls.py` includes `voice_reports.report_urls`, whose views use `_proxy_request` to Voice. `services/voice-service/voice_reports/models.py` owns the active report, SQL-edit, page, assignment and pipeline-job tables; its active views retain synchronous AI calls. `bi_platform_shared/contracts/viz.py` already defines VisualizationSpec. Query's application resolver/guard owns analytical execution. Adding a deck feature must not accidentally revive duplicate persistence, move authorization to a vendor, or demand a large legacy migration in December.

## Options

| Option | Benefit | Cost/risk | Decision |
|---|---|---|---|
| A. Move all report ownership into Report Service, add Presentation there | Unified report owner | Legacy tables/routes/history, jobs, foreign keys and permissions need a substantial reconciled cutover before new functionality | Target consolidation later; not a January prerequisite |
| B. New Presentation logical domain co-deployed with Report Service | Reuses existing deployment and product boundary, owns new artifacts/jobs, independent schema/worker; avoids moving working legacy state | Temporary two distinct domains with explicit API references; Report deployment needs production hardening and a real owned app | **Chosen** |
| C. Separate Presentation Service | Independent deployment/scaling/failure boundary | Additional network/configuration, migrations, telemetry and operations for two engineers; no measured need yet | Rejected for January |
| D. Put lifecycle/provider orchestration in AI or Voice | Quick access to existing workflow | Adds persistence/external effects to synchronous/compute path, conflates analysis and artifact ownership | Rejected |

## Decision and deployment boundary

Create a new Presentation domain in the existing Report deployment, with owned PostgreSQL tables/role and background worker entrypoint in its image. The exact package name is chosen during implementation; do not enable duplicate legacy Report ORM models. New presentation jobs/specs/evidence manifests/artifacts have one writer. Legacy saved reports stay Voice-owned and remain accessible through existing proxy routes. Presentation may link them through authorized versioned APIs, never read/write their tables directly. This is a bounded legacy compatibility boundary, not duplicate ownership of the same object.

AI Analyst produces the analysis plan, Query-governed findings and storyline/spec; Presentation validates and persists it, coordinates policy/approval, provider dispatch, artifact retrieval/validation and metering/audit. Visualization supplies existing governed chart contracts/results. Query is the sole analytical execution authority. The external provider never connects to customer databases, executes SQL or decides metric definitions.

The mandatory public abstraction is `PresentationProvider → SlidesGPTProvider / GammaProvider`. Named adapters translate vendor contracts; separate MCP/REST transports sit behind the governed tool/egress boundary. MCP-first where appropriate; Gamma may use its official REST API without changing domain DTOs. Execution credentials/network access belong to the governed gateway. No unrestricted MCP session reaches the LLM.

BIAVORA owns a formal sanitized outbound DTO and immutable approval hash, distinct from its internal PresentationSpec/evidence. External payload contains minimum approved aggregates, labels, chart assets/values, narrative and evidence summaries. It excludes credentials/credential refs, tokens, SQL/bindings, internal URLs and dumps. Approval cannot override a forbidden data class. All vendor responses/downloads are untrusted; artifacts become private BIAVORA objects only after validation and factuality checks.

BIAVORA does not build a PPTX serializer, slide layout/theme/typography/image-placement engine or complex deck renderer. Vendors own final composition/rendering/export. Reusing safe chart rendering is permitted; it is not a slide engine. If a vendor cannot preserve facts/confidentiality/export safely, disable that adapter and surface a typed limitation, rather than weakening requirements.

## Migration, failure isolation and consequences

Add new domain migrations/role, API/job routes, worker and artifact policies; existing report IDs, tables and gateway aliases remain compatible. Fresh/upgrade/rollback and denied foreign-write tests are mandatory. A future legacy-report move needs an independent ADR revision, data/history reconciliation, a single-writer cutover, route parity and rollback; the old plan to delete the Report proxy/deployment is superseded. No such deletion or move occurs in this task.

Worker concurrency/bulkheads isolate provider delay from report reads. Provider calls happen outside DB transactions with durable dispatch intent and reconciliation. Unknown remote outcome cannot be retried blindly. Policy and provider kill switches stop new work while retaining jobs/evidence/artifacts for recovery. Presentation schema rollback must not drop accepted jobs/provider IDs or usage records; use compatible readers and expand/contract migrations.

New owned role, queue/outbox, object storage, metering and gateway are implementation prerequisites, not present infrastructure claims. Both adapters are required in the design and conformance; each production provider requires independent official-contract, privacy/retention, cost and sandbox proof. At least one accepted export path is required for launch.

## Acceptance and review triggers

Accept implementation only with: one authoritative new-domain writer; no foreign ORM/report migration accident; Query-only analysis; exact loss fixture and exported factuality; both adapter conformance; valid approval/egress/tenant/artifact tests; duplicate/uncertain-dispatch recovery; usage/audit; migration/restore/rollback; actual staged provider download. These map to G-J/G-E/G-P/G-R in 43–45.

Revisit physical extraction only for measured independent load, provider-failure containment, security/network isolation or durable team ownership; require costs/SLO/on-call and migration evidence. Revisit legacy consolidation after launch. A change in provider access, retention, tool schema, price or factual-preservation behavior triggers adapter revalidation before promotion, not silent production fallback.
