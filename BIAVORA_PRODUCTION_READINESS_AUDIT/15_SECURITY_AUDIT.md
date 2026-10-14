# 15 — Security Audit

> **v2 reconciliation:** Security readiness recalculates to **31/100** under the public-SaaS baseline. Evidence below is retained. Remediation stages are: **NOW/PRE-FEATURE**—BIA-001, 002, 003, 005, 006, 008, 009, 010, 011; **BEFORE FEATURE DEPENDENCIES**—AI/Query permissions, source transport/secrets, event contracts; **BEFORE STAGING**—production identities/TLS, distributed rate limits, upload quarantine, redacted logs, owner roles; **BEFORE PRODUCTION**—security/load/restore tests, hosted billing when paid, release attestations; **POST-LAUNCH**—private transport/agent, multi-region, advanced detection. The normative control list is `33_PRODUCTION_SECURITY_BASELINE.md`.

## Verdict

Reconciled security readiness is **31/100** under the public-SaaS baseline. The repository contains useful controls—JWT validation, workspace checks in many endpoints, a shared SQL guard, ETL destination policy, credential encryption/redaction, request identifiers, and regression tests—but two runtime paths defeat tenant/query isolation and the deployed topology lacks a credible production security boundary. Treat the current system as a development/pre-production deployment, not an internet-facing multi-tenant SaaS.

This was a static, non-destructive review. No exploit was attempted. Secret values were neither copied nor printed.

## Highest-risk findings

| ID | Finding | Evidence | Risk | Required action |
|---|---|---|---|---|
| BIA-001 | Query authorization is database-scoped, not table/dataset-scoped | `services/query-service/query_api/application/query_execution.py`; `shared/bi_platform_shared/sql/guard.py` | A tenant that learns another physical table name in shared ClickHouse database `etl` can address it | Derive an immutable allowlist from authorized dataset/table bindings and pass it to the guard and ClickHouse settings |
| BIA-002 | Voice fails open to a local ClickHouse executor | `services/voice-service/voice_reports/views.py::_execute_query_with_query_service` | Query-service outage can bypass its authoritative binding checks | Fail closed; remove the local fallback and make query execution one owned capability |
| BIA-006 | Historical environment files contained secret material | Git history for `.env.microservices`; prior security reports | A removed secret remains recoverable from history and clones | Inventory and rotate every affected credential; document revocation; use a managed secret store and scanning |
| BIA-007 | Data-plane services are plaintext/weakly authenticated in Compose | root `docker-compose.yml` Kafka, Redis, ClickHouse and related settings | Credential theft, event tampering, tenant data exposure after network access | TLS/mTLS or SASL, ACLs, per-service identities, network policy, encrypted storage |
| BIA-008 | Source credentials have no production secret lifecycle | Query→Connector→Kafka flow; ETL credential crypto modules | Static salt/key, encrypted credential payloads retained in Kafka, no key ID/version/rotation | Store opaque secret references; resolve only in the connection worker; use KMS/Vault envelope encryption and retention limits |
| BIA-010 | Analytical execution lacks enforceable resource bounds | Query and voice ClickHouse executors | Expensive or enormous reads can exhaust memory/CPU and create denial of service | Enforce read-only users, max rows/bytes/time, quotas, cancellation and paged/object results |
| BIA-011 | Voice accepts large, weakly validated uploads | voice upload and Whisper queue code | Malware/storage abuse, parser risk, privacy/retention exposure | Validate signature/MIME/size/duration, quarantine/scan, isolate processing, TTL-delete and audit access |

## Authentication and session security

- The gateway validates bearer-token presence but downstream services remain responsible for authoritative JWT and workspace authorization. That is defensible only if every route is consistent; the local voice fallback proves it is not.
- Access and refresh tokens are kept in browser `localStorage`, increasing impact of any XSS. Prefer an architecture with short-lived access tokens held in memory and rotated refresh tokens in `Secure`, `HttpOnly`, `SameSite` cookies, with CSRF protection where cookie authentication is used.
- Internal calls use shared internal-key style authentication. Shared bearer secrets do not establish service identity, are hard to rotate independently, and amplify one-service compromise. Use per-workload identity or separately scoped, rotated credentials.
- Login, refresh, AI, query, upload and action routes need independent distributed abuse budgets. Gateway process-memory counters are neither authoritative nor horizontally consistent.

## Authorization and tenant isolation

The central isolation failure is a mismatch between logical authorization and physical execution. Tables are tenant-qualified but co-reside in `etl`; `SQLGuard` only restricts the database when `allowed_tables` is empty. Dataset membership must resolve to an exact physical-table set inside the query service, and the database user/session must receive corresponding constraints. Do not accept a client-provided physical name as authority.

`DatabaseSerializer` exposes `clickhouse_table_name` and `clickhouse_database`, increasing exploitability and leaking storage design. Return stable logical IDs. Administrative paths, report reads, visualizations, forecast inputs and exports must all be tested against the same authorization invariant.

## Input and application security

| Surface | Current evidence | Assessment |
|---|---|---|
| SQL | Shared parsing/guarding and deterministic generation exist | Good base, defeated by missing table allowlist; resource abuse remains |
| SSRF | ETL destination validation, DNS resolution checks and tests exist | Material improvement; connection uses the original hostname after validation, leaving a DNS-rebinding/time-of-check gap |
| File upload | Voice persists arbitrary uploaded content before transcription | Missing robust signature/MIME/AV/sandbox/retention controls |
| XSS | React escaping helps; tokens live in local storage | Add CSP/Trusted Types discipline, dependency review and component tests; never render model/document HTML unsanitized |
| CSRF/CORS | Token APIs reduce classic CSRF on bearer requests | Reassess when refresh cookies/payment webhooks are introduced; make CORS explicit and environment-scoped |
| CSV | CSV ETL exists | Exports must neutralize spreadsheet formula prefixes; imports need size/encoding/schema budgets |
| Errors/logging | Request IDs and redaction utilities exist | Raw SQL, prompts, schema samples, provider errors and traces can contain sensitive data; use field-level policy |

No evidence of shell-command execution from model output was found. Future MCP tooling would introduce that class of risk and must use typed allowlisted operations, never arbitrary commands or URLs.

## AI, RAG and action security

- AI has broad ClickHouse visibility and a process-global schema cache. Cache keys and every prompt context must include workspace, dataset, semantic-model version and policy version.
- Model responses are untrusted input. SQL goes through deterministic parsing and policy; proposed MCP actions must go through typed validation, authorization, approval and idempotency.
- Future documents must be scanned and parsed in isolation. Retrieval must apply workspace/document ACLs before ranking, preserve provenance, resist instruction-bearing documents, and never treat retrieved text as privileged instructions.
- Expose decision summaries, evidence and tool records—not hidden chain-of-thought. Full prompt/trace capture should be access-controlled, minimized, redacted and retained briefly.
- Provider egress needs a data-classification policy: which columns/samples/documents may reach local versus external models, with auditable consent and regional constraints.

## Database and infrastructure security

- Multiple services default to the same PostgreSQL database, account and schema. Compromise of one service risks unrelated business tables. Establish service-owned schemas/databases, least-privilege roles, migration identities distinct from runtime identities, and separate read versus write grants.
- Kafka, Redis and ClickHouse in root Compose are single-node development dependencies without a production TLS/ACL story. Metabase also expands the credential and data-exposure surface.
- First-party containers have no explicit non-root `USER`; images/dependencies are not reproducibly pinned; Python servers use Django `runserver`.
- `.env` is ignored locally, but historical secret exposure means ignore rules are insufficient. CI needs secret scanning including history and artifact/log review. Do not paste values into issues or reports.
- Backups, restore authorization, encryption-at-rest keys and tenant deletion proof are unverified.

## Gateway and abuse controls

The gateway buffers complete request and response bodies, trusts process-local rate state, does not establish trusted proxy/client-IP rules, and permits long downstream timeouts. Enforce streaming upload/download, hard byte limits independent of `Content-Length`, endpoint cost classes, distributed quotas, concurrency limits and cancellation. Configure a bounded header allowlist; do not relay hop-by-hop or internal authentication headers.

## CI and supply-chain gaps

The maintained gate is valuable but does not prove a secure release. Add blocking secret scanning, SAST, dependency/license review, container and IaC scanning, SBOM generation, artifact signing/provenance, pinned action digests and least-privilege workflow tokens. Define vulnerability SLAs and an exception process. Production deploys must consume immutable digests, not mutable tags.

## Security release gates

1. Close BIA-001 and BIA-002 with negative cross-tenant integration tests.
2. Rotate historically exposed credentials and introduce managed secret references.
3. Replace simulated payment with hosted checkout and verified, idempotent webhooks.
4. Harden workloads and data-plane transport/identity; run as non-root with immutable artifacts.
5. Add upload isolation, data retention/deletion and sensitive telemetry policy.
6. Complete threat models for multi-tenant analytics, CDC, RAG and MCP; test IDOR/BOLA, SSRF, SQL policy, prompt injection and approval bypass.

Until gates 1–4 pass, an internet production launch is **NO-GO**.

