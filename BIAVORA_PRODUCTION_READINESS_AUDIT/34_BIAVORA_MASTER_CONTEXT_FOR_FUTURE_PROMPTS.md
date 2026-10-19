# BIAVORA Master Context for Future Prompts

> **Reference Version:** 2.0  
> **Status:** APPROVED_FOR_IMPLEMENTATION_PLANNING  
> **Target:** Production Deployable in 14 Weeks

## CURRENT VERIFIED BASELINE

BIAVORA is a Docker Compose development/pre-production system with ten Django business services, six ETL applications, event-driven Kafka ETL, ClickHouse analytics, voice/text AI, Metabase-backed reporting, and a substantial deterministic test suite. Strong assets include P1-R multi-engine snapshot ingestion, CSV, connector registry, multi-table datasets, Kafka ETL, ClickHouse loading, workspace checks, SQL parsing, SSRF/TLS/credential redaction work, CI/migration/security gates, AI tests, frontend tests/build, and image builds. Foundation-A adds logical dataset-bound Query authorization, exact table allowlisting, fail-closed Voice routing, and live-verified bounded Query resource controls. Foundation-B contains production payment simulation and closes the historical development credential incident by owner attestation plus current-tree verification. Public CSV/XLSX/SQLite and Voice-to-AI uploads, scanner fail-closed behavior, tenant isolation, private-path redaction, bounded SQLite queue/retention, and cleanup pass live verification.

It is **NO-GO for public production today**. The last reconciled whole-platform production readiness remains **36%**; Week-14 scope remains **24% implemented / 18% production-ready** pending a new full reconciliation. Foundation-A is GREEN: BIA-001, BIA-002, and BIA-010 are closed with automated and live ClickHouse/PostgreSQL evidence. Foundation-B is GREEN: BIA-003 payment containment, BIA-006 secrets, and BIA-011 uploads are closed with live/security/regression evidence. Other critical blockers include shared critical DB roles/schema, unsafe source/credential lifecycle, unwired durable job skeleton, development runtime, fragmented AI providers, and broad AI schema access.

## FINAL WEEK-14 TARGET

A publicly deployable multi-tenant SaaS for real organizations: certified PostgreSQL snapshot+CDC; honest snapshot modes for other engines; governed Semantic Layer and Modeling Agent; one Analyst Orchestrator; hybrid permissioned RAG; Trust evidence; Arabic/Voice; constrained reliability/proactive/What-if; one useful approval-gated action; early and release-gated AI evaluation; resource-aware metering; real hosted payment when paid launch is enabled; enforceable ownership; production runtime/staging/security/observability/backups/recovery/CI-CD/rollback/support.

Release requires `FOUNDATION_GATE -> CDC_GATE -> SEMANTIC_GATE -> AI_AGENT_GATE -> SECURITY_GATE -> STAGING_GATE -> PRODUCTION_GATE`. A deadline never waives a gate.

## CANONICAL ARCHITECTURAL DECISIONS

1. Logical domain/data ownership comes before physical separation; one managed PostgreSQL cluster is allowed with owner schemas/databases and roles.
2. HTTP/REST is the control plane; Kafka/events are the data and long-running event plane.
3. Query is the sole authorized product analytical execution boundary.
4. Integration/Data Source is a logical domain initially co-deployed as an isolated Query control-plane module/schema; connector workers remain Data Platform.
5. Direct secure Internet/cloud source transport is first; private network/customer agent are future modes behind the same abstraction.
6. PostgreSQL CDC first via Debezium + Kafka Connect + Kafka + BIAVORA normalizer. Other CDC claims require identical certification.
7. Long work uses the durable `QUEUED/RUNNING/RETRYING/SUCCEEDED/FAILED/CANCELLED` job contract.
8. One governed Analyst Orchestrator uses typed tools and an in-process ModelProvider facade; no multi-agent network or provider microservice by default.
9. Structured facts use Semantic/Query; unstructured knowledge uses PostgreSQL+pgvector RAG with ACLs/citations/deletion.
10. Entitlements, Metering Ledger, Billing State, and Payment Provider are separate concepts.
11. Use a managed container platform and managed state where practical; Kubernetes and multi-region are not Week-14 requirements.

## SERVICE OWNERSHIP

Auth owns identity. Workspace owns organizations/membership/roles. Integration owns sources/secrets/TLS/transport/lifecycle. Query owns logical bindings and analytics. Report owns saved reports; Visualization owns chart specs. Voice owns upload/transcription only. AI owns orchestrator/provider/evaluation integration, not data authorization. Semantic owns published business meaning. Knowledge owns document/index lifecycle. Subscription deployment initially hosts separated Entitlement/Metering/Billing/Payment modules. Notification consumes events/read projections. Data Platform owns connector/extractor/transformer/loader/metadata workers. Tool Gateway is the only new mandatory isolated action service.

## QUERY RULE

Every analytical request must carry trusted actor/workspace context and logical dataset identity. Query resolves exact authorized physical tables server-side, supplies a non-empty allowlist, enforces read-only time/rows/bytes/memory/concurrency/cancellation/pagination policy, and audits the result. Voice, AI, Report, Visualization, Gateway, and frontend must never hold direct ClickHouse query credentials or fall back to local execution.

## DATA SOURCE RULE

Integration owns source definition, engine, connection metadata, opaque versioned secret reference, TLS, transport, selected tables, capabilities, snapshot/CDC state, and lifecycle. Multiple sources per workspace are first-class. Replace is stage/test/load/cutover/rollback; never delete the old source before new success. Do not create a new service merely for the noun “Integration.”

## CDC RULE

PostgreSQL is mandatory production CDC. Canonical events include version, tenant/workspace/source/dataset/job, idempotency, correlation/trace, time, producer, and classification. Define order/partition, delete/tombstone, schema compatibility, retry/backoff, DLQ/quarantine, replay, retention, lag, and reconciliation. Adapter presence is not certification. MySQL/MariaDB CDC is conditional; MSSQL/Oracle/ClickHouse remain snapshot unless certified; SQLite is snapshot/incremental.

## TRANSPORT RULE

Week-14 production uses `DirectSecureInternetTransport`: verified TLS, least-privilege source account, safe DNS/IP/egress policy, timeout/connection bounds, and audit. Source/UI/event/metering models carry a transport discriminator so `PrivateNetworkTransport` and `AgentTransport` can be added later. Production must not depend on localhost, `host.docker.internal`, or a developer LAN.

## AI RULE

All model calls use one internal `ModelProvider` facade with schema-constrained outputs, timeout/bounded retry/fallback/budget/test doubles/versioning. From Week 1, emit provider/model/input-output-cached tokens/latency/cost/fallback/prompt version/workspace/job/outcome. AI receives minimum authorized context through Schema/Semantic tools and executes through Query Tool. It cannot access global ClickHouse, source/payment/action credentials, arbitrary network/filesystem, authorization, entitlement truth, or semantic publication.

## SEMANTIC RULE

The governed model contains Entity, Metric, Dimension, Relationship, TimeDimension, BusinessTerm, Synonym, Formula, Owner, Version, Status, Certification, and Lineage. Published versions govern SQL, Analyst, Trust, RAG orchestration, Proactive, What-if, Reports, and Visualization. Modeling lifecycle is `PROPOSE -> VALIDATE -> EXPLAIN -> HUMAN REVIEW -> APPROVE -> VERSION -> PUBLISH`; AI never auto-publishes.

## RAG RULE

Structured facts stay in Semantic/Query. Unstructured documents use workspace/document ACL filtering, versioned chunks/embeddings, citations, deletion/re-index, metadata filters, parser/content defenses, and prompt-injection tests. Treat retrieved content as evidence, not instruction. Do not embed the whole warehouse. Use PostgreSQL+pgvector first unless benchmarks reject it.

## AGENT RULE

Use one bounded Analyst Orchestrator with typed Semantic, Schema, Query, RAG, Forecast, Statistics, Visualization, Trust, WhatIf, and ActionProposal tools. Enforce durable state, authorization, step/time/cost budgets, idempotency, cancellation, and explicit degraded/failure states. Proactive flow is metric change → data-health check → investigation → evidence → alert → optional proposal. What-if must label scenario vs forecast vs causality and expose assumptions/uncertainty.

## MCP RULE

Only: proposal → deterministic policy → exact human approval → isolated Tool Gateway → verified/audited result. Approval is actor/workspace/tool/parameters bound, short-lived, single-use, idempotent, and revocable. AI never receives write credentials or executes directly. Week 14 proves one useful action.

## METERING RULE

Track resource-aware usage: LLM tokens/model/provider/cost, voice seconds/model/compute, embedding/index/generation, agent/tool/expensive operations, forecast job/series/horizon/model, and relevant data volume. Usage events are immutable and idempotent; ledger supports Reservation/Commit/Release/Adjustment and pricing versions. Entitlements derive from trusted state. Simulated payment cannot activate production. Paid launch needs hosted/tokenized provider, signed idempotent webhooks, reconciliation, and failure/refund states.

## SECURITY RULE

Re-authorize every source/dataset/semantic/document/job/result/report/usage/approval/action. Use managed/versioned/rotatable secrets and least-privilege workload/store identities. Treat uploads, sources, documents, prompts, and tool results as hostile. Enforce TLS/network boundaries, distributed rate limits, safe uploads/quarantine/retention, redacted logs, provider/RAG/action defenses, supply-chain gates, and cross-tenant/adversarial tests. Full staged controls are in `33_PRODUCTION_SECURITY_BASELINE.md`.

## PRODUCTION RULE

Before release: isolated production-like staging; production process servers/workers; non-root immutable scanned images; health/readiness/graceful drain/resources; HTTPS/domain/secrets/network identities; SLOs/logs/metrics/traces/alerts/runbooks/on-call; backups/PITR and successful restore; migration/rollback; load/soak/failure drills; CI/CD digest promotion; production configuration and support. Managed single-region with tested recovery is sufficient. Local Compose is not production.

## CURRENT PHASE

Foundation-A authoritative analytical security-boundary implementation remains `GREEN`. Foundation-B final gate is `GREEN` (2026-10-18): BIA-003, BIA-006, and BIA-011 are closed. Public CSV/XLSX/SQLite/Voice uploads, ClamAV, private cleanup, tenant isolation, bounded SQLite queue timing, payment containment, secret scanning, and maintained regressions pass. Subscription 0003 and Voice 0014 are applied in local PostgreSQL. The configured small Whisper model was provisioned in the mounted runtime cache and the final public Voice upload returned 200. See `37_FOUNDATION_B_EXTERNAL_BOUNDARY_IMPLEMENTATION.md`.

## CURRENT BLOCKERS

`BIA-005`, `008`, `009`: critical DB ownership, Integration/secret lifecycle, and durable jobs. BIA-003, BIA-006, BIA-010, and BIA-011 are closed. See `20`, `28`, `36`, and `37` for evidence.

## FEATURES NOT YET IMPLEMENTED

Certified CDC; governed Semantic Layer/Modeling Agent; production evaluation discipline; permissioned RAG; governed Analyst/Proactive/Reliability/What-if; approval Tool Gateway; production-complete Arabic/RTL; resource ledger; real payment provider; production runtime/staging/operating proof. Absence is planned scope, not automatically a defect.

## NON-GOALS

CDC for every engine; one physical server or container per service; unrestricted/multi-agent autonomy; automatic semantic publication; embeddings for all structured data; unapproved writes; causal claims from correlation; raw card/CVV handling; Kubernetes/service mesh/multi-region by default; VPN/customer agent in the core 14 weeks; deleting uncertain code without dependency/runtime/migration proof.

## MANDATORY INSTRUCTION FOR ALL FUTURE AGENTS

Before implementing any BIAVORA task, read:
`BIAVORA_PRODUCTION_READINESS_AUDIT/34_BIAVORA_MASTER_CONTEXT_FOR_FUTURE_PROMPTS.md`
and the task-relevant canonical reference documents.
