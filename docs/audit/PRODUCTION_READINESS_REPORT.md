# Production readiness report

**NOT READY. Do not deploy this baseline or start new features before the P0 security and recovery gates are closed.** A successful local build or database reset is not production readiness. Evidence date: 2026-09-13; source and runtime scope are stated in the main audit.

| Category | Status | Evidence / release gate |
| --- | --- | --- |
| Security | BLOCKER | Historical active secrets, unauthenticated ETL, SSRF exposure and source-known encryption fallback. Rotate and fail closed. |
| Architecture | BLOCKER | Shared persistence, report proxy/voice ownership inversion, Kafka workflows and shared upload directory violate the requested target. Execute R1–R7 with contract gates. |
| Databases | BLOCKER | Shared PostgreSQL account, notification foreign ORM, multi-owner ClickHouse/Surreal, memory-only metadata and migration drift. Isolate ownership, persistence and grants; prove recovery. |
| Networking | BLOCKER | Host-published internal APIs/data ports, plaintext Redis/Kafka and no TLS edge. Firewall reachability outside the host is NOT VERIFIED. Define ingress and service networks. |
| Docker | FAIL | All application Dockerfiles use runserver/root; floating images/dependencies. Seven ignore files were added and all 17 app/worker images built, but production server, users, limits and immutable releases remain required. |
| APIs | FAIL | No canonical first-party OpenAPI, inconsistent errors/versioning, public ETL and raw object IDs. Validate `/api/v1` and `/internal/v1` contracts and timeouts. |
| Authentication | BLOCKER | Retained credentials, shared symmetric signing power, refresh lifecycle gaps and invited-existing-user password overwrite. Require asymmetric verification and verified identity recovery. |
| Authorization | BLOCKER | SEC-001, SEC-002 and SEC-015 allow unchecked tenant/object/binding choices; SEC-003 bypasses the central SQL guard. Add negative two-tenant tests before release. |
| AI | FAIL | Ten selected tests fail; direct warehouse reads, potentially long synchronous work and ineffective cancellation. External model output must pass the same query authorization boundary. No live paid inference/cost/load claim. |
| Observability | PARTIAL | ETL tracing/metrics helpers and some request IDs exist. No complete deployed collection/alert path or end-to-end trace evidence. Redact sensitive URLs/prompts and validate outage alerts. |
| Backups | PARTIAL | 37 files verified, PostgreSQL restore count parity. Other full service recovery drills and encrypted off-host retention incomplete; former Surreal memory state unavailable. |
| CI/CD | FAIL | No first-party CI release gate found; no green all-service baseline, lint config missing, unsupported core Django and no verified SBOM/advisory gate. |
| Testing | FAIL | 411 selected tests passed, 46 failed; 17 additional passing subtests; separate collection errors. Startup/HTTP evidence is separate and does not establish full workflow correctness. |
| Performance | PARTIAL | Some pagination, batching, query caps and idempotency helpers exist; no load/soak results. Gateway buffers bodies and retains rate-limit keys; AI waits and warehouse retention need bounded policies. |
| Deployment | BLOCKER | One host, host PostgreSQL/Ollama, standalone H2 Metabase, sequential readiness chain, no tested HA/rolling rollback/DR runbook. Local startup is the only deployment scope exercised. |

## Gates and definitions

Production blockers are counted as all unresolved CRITICAL and HIGH issues in `issues.json`; category rows overlap and must not be added to that number. A PASS requires positive evidence for that exact scope. PARTIAL means useful controls exist with material gaps. FAIL means the checked requirement is not met. BLOCKER means the gap directly prevents safe release. NOT VERIFIED is used for unexecuted tests, not silently treated as PASS.

Microservices architecture: **NOT COMPLIANT** with the user target. Database-per-service: **NOT COMPLIANT**. HTTP-only business communication: **NOT COMPLIANT**. Five grouped ETL Kafka business paths and one shared-file path are confirmed; voice report events remain undecided until their consumers are identified. Native database access by its owning service and private same-domain AI Redis coordination are allowed infrastructure operations.

## Before the next development sprint

Close the exact first ten tasks in the action plan: secret rotation, tenant and SQL bypasses, ETL ingress/egress/key controls, persistent metadata/recovery, migration parity and reproducible verification. Gate any temporary restricted development use behind localhost bindings and mail-disabled configuration. Do not call unrotated credentials safe because the machine is local.

## Before production

Use separate environment files and service-specific secrets; a TLS reverse proxy; non-root production WSGI/ASGI images; isolated owner databases/roles; authenticated internal HTTP with propagated tenant scope and idempotency; object-level authorization; persistent media and metadata; supported locked dependencies and SBOM scans; migration jobs; readiness/liveness plus worker heartbeats; request traces/metrics/log redaction; tested backup restore and rollback; and a green unit/contract/security/integration pipeline. R0–R13 in the restructuring plan provide concrete files, tasks and rollback gates.

One PostgreSQL server may host separate logical databases for an MVP if credentials and ownership are isolated. One Metabase deployment may serve a controlled read-only BI projection; it must not gain operational cross-service database access. A single host may be a deliberately accepted pilot constraint only with tested recovery and a stated outage budget; it is not high availability. These are deployment choices, not waivers for tenant isolation or exposed secrets.

## After MVP

Scale workers from measured queue latency and CPU/memory profiles; add replicas/HA where SLOs justify them; tune indexes/partitions/caches from query evidence; automate retention and warehouse deletion policy; improve cost attribution and model evaluation; remove compatibility routes after observed migration completion. No speculative Kubernetes or service multiplication is required for the target boundaries.

Core Django 4.2 is out of support as of this audit; the support window was checked against [Django's official support table](https://www.djangoproject.com/download/). Vendor guidance recommends [PostgreSQL for Metabase application storage](https://www.metabase.com/docs/latest/installation-and-operation/configuring-application-database). No exhaustive dependency CVE assessment or real production penetration test was performed.
