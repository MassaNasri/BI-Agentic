# 33 — Production Security Baseline

> **Reference Version:** 3.0 / 2026-10-27
> **Status:** APPROVED_FOR_IMPLEMENTATION_PLANNING  
> **Target:** Public launch 10 January 2027; evidence-gated

This is the normative minimum for an Internet-facing BIAVORA SaaS. It is staged by dependency, not by willingness to accept risk. Items in a completed stage require automated tests or recorded operational evidence. Existing JWT/workspace checks, SQL parsing, SSRF controls, credential redaction, TLS contracts, migration/security regression assets, and image builds should be preserved and strengthened.

## Foundation status and pre-feature blockers

Local implementation/security invariants close before dependent work. Environment-dependent C deployment validation is separately deferred to CAP-14, required before public release; it no longer blocks local Foundation-D (49).

Current local statuses use 36/37/42 plus CI-repair validation in 49. **Foundation-C Local Engineering: CLOSED. Foundation-C External Deployment Validation: DEFERRED_TO_PRODUCTION_READINESS. Production Readiness: NO-GO.** BIA-008 remains technically PARTIAL; dated historical findings in 20 are not rewritten.

| Control | Current state | Required residual evidence |
|---|---|---|
| Query authorization / sole authority / resource safety (BIA-001/002/010) | CLOSED for Foundation-A; maintained local regressions in 42 | Preserve exact logical bindings/allowlists, fail-closed paths, cancellation/resources and deployed tenant tests |
| Payment simulation (BIA-003) | CLOSED for containment | Paid activation disabled unless a real hosted provider/webhook/reconciliation gate passes |
| Critical ownership (BIA-005) | CLOSED for local C6 defect | Deploy/rehearse exact owner roles, migrations and denied cross-owner writes; Notification foreign reads remain adjacent debt |
| Historical credential incident (BIA-006) | CLOSED via owner attestation plus technical controls, report 37 | Preserve scanner/config/redaction controls; no new independent revocation claim |
| Source lifecycle (BIA-008/014) | LOCAL ENGINEERING COMPLETE; BIA-014 CLOSED; BIA-008 technically PARTIAL | Managed secrets/KMS, deployed identity/real rotation/restart under CAP-14/G-C-DEPLOY |
| Source DNS/public transport (BIA-018) | Local DNS defect CLOSED; external validation DEFERRED_TO_PRODUCTION_READINESS | CAP-14 combined public verify-full ETL, stable egress/allowlist and hostile DNS/CA/hostname drills |
| Public metadata (BIA-030) | CLOSED for local canonical defect | Preserve route inventory/SQL logicalization/Gateway filters; expand artifact/new-route tenant tests |
| Durable context (BIA-009/020) | PARTIAL skeleton; active flows synchronous/pending integration | Persisted job/context/idempotency/outbox/recovery, no false success before dependent work |
| AI schema/provider boundary (BIA-019/021) | Open | Authorized minimum Schema/Query tools, tenant/version keyed cache, facade and no broad AI warehouse credentials |
| Upload boundary (BIA-011) | CLOSED for Foundation-B | Preserve maintained voice/file/SQLite scanner/limits/retention tests and staged operating proof |
| Kafka compatibility / CI | v1 TRANSITIONAL; previous remote FAILED; repair PENDING_PUSH_AND_RUN | Actual deployed v1 retention/drain under CAP-14; current mandatory CI GREEN before local Foundation-D |

## PRE-STAGING

### Authentication and authorization

- Validate token signature/issuer/audience/expiry/rotation and enforce logout/revocation policy appropriate to token lifetime.
- Re-authorize actor/workspace role and object ownership at source, dataset, job, result, report, semantic, presentation/artifact, usage, approval, and action boundaries. Never trust a request workspace ID alone.
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

### AI, presentation, and tool security

- Remove broad AI CH credentials/global schema enumeration; enforce authorized Schema/Semantic/Query tools and tenant/version keyed caches.
- Apply provider allow/data-region policy, timeout/budget/retry controls, prompt/data minimization, safe structured output validation, and tenant-safe logging.
- Treat document/source content as untrusted. Sandbox/quarantine parsers, filter/recheck ACLs, prevent instruction override, and test prompt/data exfiltration.
- Tool schemas and orchestrator budgets fail closed. ActionProposal cannot execute. No third-party write credential is available to AI.

### Logging, privacy, and data lifecycle

- Structured allowlisted logs redact tokens/secrets/credentials/card data and minimize SQL/prompts/rows/document text; ERROR severity must not dump raw tenant SQL/context.
- Define retention/deletion/export and backup-retention policy for uploads, transcripts, prompts/traces, query results, reports, presentation specs/assets/artifacts/evidence, semantic versions, audit, and ledger.
- Encrypt managed stores and backups; restrict telemetry access and audit sensitive access.

### Billing and metering foundation

- Separate trusted Entitlement, Metering, Billing State, and Provider inputs. The client never declares paid status.
- Usage events are server-produced, idempotent, immutable, workspace/job scoped, and reconciled to reservations/commits/releases.
- Hosted/tokenized collection is selected; BIAVORA never stores PAN/CVV.

### CI/CD and supply chain

- Pin/lock dependencies and base images; scan source/secrets/dependencies/images/IaC; generate SBOM and sign/promote immutable digests when platform permits.
- Protect branches/environments, require reviewed migrations/security-sensitive changes, isolate CI credentials, and prevent untrusted code from production secrets.
- Add tenant-negative, SSRF/DNS, upload, Kafka poison/replay, provider/tool/presentation injection, authorization, metering concurrency, and migration rollback gates.

## PRE-PRODUCTION

### Staging proof

- Production-like isolated staging uses the same secret/identity/network/runtime/observability contracts and release candidate digests.
- Security tests cover OWASP-style API/browser issues, cross-tenant object/tool/cache/result access, privilege changes, token failures, rate-limit bypass, large/malicious upload, SSRF/DNS rebinding, provider/presentation/tool injection, action replay/expiry, webhook forgery/replay, and log leakage.
- Load/soak proves query/job/source/provider/action/usage controls remain effective under concurrency and failure.

### Runtime and resilience

- Production WSGI/ASGI/worker processes run as non-root with graceful drain, read-only/minimal filesystem where practical, resource limits, health/readiness, patch policy, and no debug mode.
- PostgreSQL PITR/restore, ClickHouse recovery/rebuild, object/artifact restore/deletion, Kafka recovery/replay, semantic/job/ledger recovery, migrations, and application rollback are rehearsed with recorded RPO/RTO.
- SLOs/dashboards/alerts/runbooks and named responders cover auth, ingestion/CDC, query/jobs, provider/presentation, actions, billing/usage, saturation, backup, and security events.

### Payments/actions

- If paid launch is enabled: hosted/tokenized checkout, server-verified amount/plan, signed idempotent webhooks, pending/success/failure/refund/chargeback states, reconciliation, support/audit, and entitlement delay/revocation tests pass. Otherwise paid activation is disabled.
- The minimum approval-required presentation action uses exact human approval bound to actor/workspace/tool/parameters, short TTL, single use, idempotency, isolated credential/egress, result verification, and immutable audit.

### Release gate

- No open P0; no exception for tenant breach, data loss/corruption, secret exposure, arbitrary action, false payment/entitlement, or missing restore.
- Security, platform/operations, data, AI/product, and finance owners sign the release evidence.
- Capability/engine claims exactly match certified modes. Kill switches/rollback criteria and incident contacts are active during controlled launch.

## POST-LAUNCH

- Continuous vulnerability/dependency/image scanning, patch SLAs, access reviews, secret rotation, provider/model risk review, abuse/fraud tuning, and penetration tests.
- Periodic tenant isolation, restore, incident, action, billing reconciliation, CDC recovery, and prompt/presentation injection drills.
- Private network/customer agent transport, customer-managed keys, enterprise SSO/SCIM, advanced DLP/SIEM, additional regions, and multi-region resilience based on customer/risk demand.
- Dedicated Integration/Model Gateway/Presentation deployments only when measured security/scale/ownership warrants them.

## Mandatory evidence format

Each release control records: control ID/owner; environment and artifact digest; test/drill date; command/report link; pass/fail and measured threshold; exception/expiry if allowed; rollback/mitigation; reviewer. Secret values, private data, and exploit payloads are never copied into the evidence record.

## Presentation-specific release boundary

The formal threat model and tests in [44](44_AI_PRESENTATION_AND_EXECUTIVE_REPORT_ARCHITECTURE.md) are mandatory. Outbound payloads use a positive schema and data classification; provider prompts, assets and notes may contain only minimum approved analytical outputs. Always prohibit credentials/credential_ref, keys/tokens, internal URLs, physical ClickHouse bindings and raw dumps, even if a human approves. Aggregated identifying labels/small cohorts may still be sensitive.

Register exact provider/tool origins and schemas; MCP is transport, not authorization. Managed provider secrets are available only to the governed execution boundary. Approval binds actor/workspace/tool/provider/payload hash/cost/expiry and is single-use/revocable. A safe preapproved create intent may avoid an extra click, but CAP-09 must prove a genuine explicit approval path. Reauthorize at dispatch/download.

Private artifacts need IDOR/cross-tenant tests, safe SSRF-resistant download, MIME/size/malware/active-content checks, short-lived authorized URLs and retention/deletion evidence. No raw vendor HTML/widget display. Validate exported facts and claims; provider success alone is insufficient. Unknown remote outcome requires reconciliation before retry/failover; incurred cost is recorded and reserved budgets cannot be double-spent.

Structured & Unstructured RAG, Proactive Monitoring Agent and Arabic & Voice Support expansion are OUT OF JANUARY 10 RELEASE SCOPE. References to hostile documents/content above describe defensive input handling, not a new document/RAG feature. Existing voice safety remains mandatory. Scope and final evidence gate are in 43/45; historical 16/17 are not current release checklists.

## Deployment checkpoint retained

Managed external secret store/KMS, deployed workload identities and real identity rotation, stable controlled public egress, customer-like PostgreSQL TLS verify-full and allowlist proof, combined full public production-policy ETL, deployed Kafka v1 backlog/drain attestation, and deployment cutover/rollback proof remain mandatory under CAP-14 before public GO. CAP-14 dates: operator/platform plan 16 November, environment/probes 29 November, G-C-DEPLOY 15 December; revalidate the final candidate before public GO. This sequencing decision changes no production guard or test acceptance threshold.
