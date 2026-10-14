# 33 — Production Security Baseline

> **Reference Version:** 2.0  
> **Status:** APPROVED_FOR_IMPLEMENTATION_PLANNING  
> **Target:** Production Deployable in 14 Weeks

This is the normative minimum for an Internet-facing BIAVORA SaaS. It is staged by dependency, not by willingness to accept risk. Items in a completed stage require automated tests or recorded operational evidence. Existing JWT/workspace checks, SQL parsing, SSRF controls, credential redaction, TLS contracts, migration/security regression assets, and image builds should be preserved and strengthened.

## PRE-FEATURE BLOCKERS

These close before dependent implementation because otherwise new code would amplify an unsafe boundary.

| Control | Verified present risk | Required acceptance evidence |
|---|---|---|
| Tenant-scoped analytical authorization | Query passes database but no table allowlist (`BIA-001`) | Logical dataset binding, exact table allowlist, read-only/resource settings, arbitrary/cross-tenant negative tests |
| Sole Query execution authority | Voice falls back to local CH (`BIA-002`) | No direct Voice/AI/Report/Viz credential or fallback; outage becomes durable failure/retry |
| Subscription simulation containment | Subscribe view creates active/success state without provider (`BIA-003`) | Production mode cannot activate simulation; feature flag/config cannot be client controlled |
| Critical logical data ownership | Shared DB name/user; Notification unmanaged cross-domain projections (`BIA-005`) | Owner map and least-privilege Auth/Workspace/Query/Integration/Entitlement roles; denied cross-owner writes; reversible migrations |
| Secret incident closure | `.env.microservices` exists in Git history (`BIA-006`) | Inventory, rotate/invalidate, history/artifact/log scan, owner signoff, managed replacements; no values exposed in evidence |
| Source/credential lifecycle | Query source config + destructive replacement; static encryption salt/no key version (`BIA-008`) | Integration owner, opaque versioned secret refs, KMS/secrets manager, rotation/audit, staged cutover/rollback |
| Durable security context | Active long flows synchronous; job skeleton unwired (`BIA-009`) | Persisted actor/workspace/job/idempotency and validated transitions; no false success/replay |
| Query resource safety | No universal CH limit/full materialization (`BIA-010`) | Max time/rows/bytes/memory/concurrency, pagination/ref, cancellation, abuse/load tests |
| Upload boundary | Voice writes unvalidated chunks (`BIA-011`) | Streaming size/type/magic checks, safe names, quarantine/AV/decompression defenses, storage ACL, TTL/delete, abuse tests |

## PRE-STAGING

### Authentication and authorization

- Validate token signature/issuer/audience/expiry/rotation and enforce logout/revocation policy appropriate to token lifetime.
- Re-authorize actor/workspace role and object ownership at source, dataset, job, result, report, semantic, document, usage, approval, and action boundaries. Never trust a request workspace ID alone.
- Define admin/support access with MFA, least privilege, time-bounded elevation, audit, and no shared accounts.
- Remove cross-domain ORM access; use owned APIs/events/read projections.

### Secrets and infrastructure identity

- Move runtime secrets to a managed secret store; record owner, consumer identity, key/version, created/rotated dates, and emergency rotation.
- Use separate staging/production secrets and workload identities. Do not reuse global internal API keys across broad service sets.
- Configure Kafka topic/group ACLs and encrypted/authenticated transport; ClickHouse distinct loader/query/admin identities and TLS; Redis authentication/TLS and network isolation; PostgreSQL owner roles/TLS; object store tenant-scoped service identities.
- Prevent secrets in images, Compose-rendered output, CI logs/artifacts, URLs, events, traces, and exception messages.

### Network and source connectivity

- Edge terminates modern HTTPS, applies WAF/body/time/header limits, trusted proxy configuration, request IDs, and distributed rate limits.
- Private internal services are not publicly exposed; egress is allow-listed by workload where practical.
- Direct source connection verifies TLS hostname/chain, uses least-privilege source account, safe DNS/IP policy across redirects/resolution/use, timeouts, connection limits, and auditable destination.
- Preserve a transport abstraction for future private/agent connection without weakening the direct mode.

### AI, RAG, and tool security

- Remove broad AI CH credentials/global schema enumeration; enforce authorized Schema/Semantic/Query tools and tenant/version keyed caches.
- Apply provider allow/data-region policy, timeout/budget/retry controls, prompt/data minimization, safe structured output validation, and tenant-safe logging.
- Treat document/source content as untrusted. Sandbox/quarantine parsers, filter/recheck ACLs, prevent instruction override, and test prompt/data exfiltration.
- Tool schemas and orchestrator budgets fail closed. ActionProposal cannot execute. No third-party write credential is available to AI.

### Logging, privacy, and data lifecycle

- Structured allowlisted logs redact tokens/secrets/credentials/card data and minimize SQL/prompts/rows/document text; ERROR severity must not dump raw tenant SQL/context.
- Define retention/deletion/export and backup-retention policy for uploads, transcripts, prompts/traces, documents/chunks/embeddings, query results, reports, semantic versions, audit, and ledger.
- Encrypt managed stores and backups; restrict telemetry access and audit sensitive access.

### Billing and metering foundation

- Separate trusted Entitlement, Metering, Billing State, and Provider inputs. The client never declares paid status.
- Usage events are server-produced, idempotent, immutable, workspace/job scoped, and reconciled to reservations/commits/releases.
- Hosted/tokenized collection is selected; BIAVORA never stores PAN/CVV.

### CI/CD and supply chain

- Pin/lock dependencies and base images; scan source/secrets/dependencies/images/IaC; generate SBOM and sign/promote immutable digests when platform permits.
- Protect branches/environments, require reviewed migrations/security-sensitive changes, isolate CI credentials, and prevent untrusted code from production secrets.
- Add tenant-negative, SSRF/DNS, upload, Kafka poison/replay, provider/tool/RAG injection, authorization, metering concurrency, and migration rollback gates.

## PRE-PRODUCTION

### Staging proof

- Production-like isolated staging uses the same secret/identity/network/runtime/observability contracts and release candidate digests.
- Security tests cover OWASP-style API/browser issues, cross-tenant object/tool/cache/result access, privilege changes, token failures, rate-limit bypass, large/malicious upload, SSRF/DNS rebinding, provider/RAG/tool injection, action replay/expiry, webhook forgery/replay, and log leakage.
- Load/soak proves query/job/source/provider/action/usage controls remain effective under concurrency and failure.

### Runtime and resilience

- Production WSGI/ASGI/worker processes run as non-root with graceful drain, read-only/minimal filesystem where practical, resource limits, health/readiness, patch policy, and no debug mode.
- PostgreSQL PITR/restore, ClickHouse recovery/rebuild, object/document restore/deletion, Kafka recovery/replay, semantic/job/ledger recovery, migrations, and application rollback are rehearsed with recorded RPO/RTO.
- SLOs/dashboards/alerts/runbooks and named responders cover auth, ingestion/CDC, query/jobs, provider/RAG, actions, billing/usage, saturation, backup, and security events.

### Payments/actions

- If paid launch is enabled: hosted/tokenized checkout, server-verified amount/plan, signed idempotent webhooks, pending/success/failure/refund/chargeback states, reconciliation, support/audit, and entitlement delay/revocation tests pass. Otherwise paid activation is disabled.
- The minimum action integration uses exact human approval bound to actor/workspace/tool/parameters, short TTL, single use, idempotency, isolated credential/egress, result verification, and immutable audit.

### Release gate

- No open P0; no exception for tenant breach, data loss/corruption, secret exposure, arbitrary action, false payment/entitlement, or missing restore.
- Security, platform/operations, data, AI/product, and finance owners sign the release evidence.
- Capability/engine claims exactly match certified modes. Kill switches/rollback criteria and incident contacts are active during controlled launch.

## POST-LAUNCH

- Continuous vulnerability/dependency/image scanning, patch SLAs, access reviews, secret rotation, provider/model risk review, abuse/fraud tuning, and penetration tests.
- Periodic tenant isolation, restore, incident, action, billing reconciliation, CDC recovery, and prompt/RAG injection drills.
- Private network/customer agent transport, customer-managed keys, enterprise SSO/SCIM, advanced DLP/SIEM, additional regions, and multi-region resilience based on customer/risk demand.
- Dedicated Integration/Model Gateway/vector deployments only when measured security/scale/ownership warrants them.

## Mandatory evidence format

Each release control records: control ID/owner; environment and artifact digest; test/drill date; command/report link; pass/fail and measured threshold; exception/expiry if allowed; rollback/mitigation; reviewer. Secret values, private data, and exploit payloads are never copied into the evidence record.
