# 47 — Scope, architecture and release-roadmap reconciliation report

Date: **2026-10-27** · Target launch: **10 January 2027** · Mode: documentation and architecture only.
Outcome: one current release blueprint, exact capability traceability and a provider-neutral Presentation design. **Production NO-GO. Foundation-C remains BLOCKED_EXTERNAL overall.** This report does not certify a deployment.

## A. Repository state

- Repository: BI-Voice-Agent / BIAVORA.
- Branch: `foundation-c-staging`.
- HEAD: `9ed2439512179b032736c6f1917521fb7c0dce71`.
- At entry: **5,751 tracked paths**, no parent-repository untracked files, no staged changes; only `services/ai-service/forecasting/timesfm` dirty with untracked submodule content.
- That pre-existing TimesFM state was left untouched. No command staged, reset, cleaned, edited or committed it; no recursive inspection inside that submodule was used for this reconciliation.
- HEAD and branch remain unchanged. No commit or push. The final changed/new files are listed in H/I.

Recent commits inspected: `9ed2439` Foundation-C local engineering closure; `9298d2f` Foundation-B hardening; `274ace6` Foundation-A Query boundary; `0b9ee0b` AI schema correction; `925c2cb` visualization CI PostgreSQL; `038b8f6` P1-R CI reproducibility; `0010e52` P1-R multi-database acceptance; `1ca062c` shared library.

Current states, without inflating scope:

| State | Evidence / conclusion |
|---|---|
| CLOSED | A: BIA-001/002/010. B: BIA-003/006/011. C local defects: BIA-005/014/030; BIA-018 DNS defect only |
| LOCAL PASS | C6 restricted-role end-to-end lifecycle, migration/rollback, tenant probes and bounded v2 replay, as recorded in 42 |
| PARTIAL | BIA-008 lifecycle; jobs/provider/evaluation/metering/operating foundations |
| BLOCKED_EXTERNAL | Managed store/KMS and deployed identities/rotation; combined public production-policy TLS/egress ETL; actual Kafka v1 drain; C overall |
| TRANSITIONAL | v1 reader defaults OFF in production, bounded seven-day opt-in; actual deployed retention/backlog unknown |
| NOT STARTED | PostgreSQL WAL CDC, governed semantic/model publication, Presentation runtime/adapters and MCP approval execution |

Report 42's “uncommitted / pending push” wording is historical. Its work is now at the recorded HEAD; the report remains unchanged. Exact-SHA remote CI is **UNVERIFIED**, not assumed red or green. The workflow triggers on pull requests, main pushes or manual dispatch, so a feature-branch push alone would not prove execution. No new remote CI run or deployed infrastructure was inspected.

## B. Documents and source reviewed

Key review: audit 00–42, with current scope/architecture/debt/implementation/security/master documents and Foundation 36–42 receiving detailed reconciliation; prior `docs/audit` architecture/ownership/communication/action/restructure documents; P0-A/B/C and P1/P1-R remediation/acceptance/security/release/recovery reports; ETL architecture, runbook, rollback, rollout/migration/success criteria and implementation notes. [48](48_DOCUMENTATION_INVENTORY_AND_SCOPE_REFERENCES.md) gives the complete file inventory, review-depth limitations and retained-reference locations.

Source tracing covered Query authorization/resource/public SQL boundaries; Integration models/credential lifecycle/routing; shared owner roles/secrets; ETL registry/security/v1 policy; Report settings/routes/proxy and Voice active report/job/text path; AI schema readers/cache/Dagster/routing; shared visualization contracts; Subscription counters/payment containment; Compose/Dockerfiles/requirements and the release workflow. [45 evidence anchors](45_BIAVORA_RELEASE_TRACEABILITY_MATRIX.md) list exact paths.

This was a targeted repository review plus a repository-wide first-party documentation/reference search, not an execution of every source path. Ancillary notes were indexed and inspected by relevant sections; no claim of manually reading every source line is made. No environment-secret files or backup/runtime payloads were needed.

## C. Final approved product scope

1. Foundation / Production Hardening.
2. Multi-Database Integration.
3. PostgreSQL CDC.
4. Semantic Layer & Metrics.
5. Semantic Modeling Agent.
6. Analyst Agent.
7. Trust & Explainability.
8. Data Reliability Agent — Limited.
9. MCP Actions with Human Approval — Limited.
10. What-if Analysis.
11. AI Presentation & Executive Report Generation.
12. AI Evaluation & Security Testing.
13. Quota / Metering evolution.
14. Production Deployment / Operations Readiness.

The exact customer release contract, P0/P1/P2 and certified-engine boundaries are in [43](43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md). Seven existing snapshot adapters do not mean seven production-certified network engines. PostgreSQL is the sole required CDC engine. CSV/XLSX/SQLite import remains; other direct engines require explicit transport/live certification. Paid activation remains disabled unless its real payment gate passes.

## D. Removed release scope and retained occurrences

**Structured & Unstructured RAG; Proactive Monitoring Agent; Arabic & Voice Support expansion are OUT OF JANUARY 10 RELEASE SCOPE.**

Current scope, roadmap, architecture, ownership, AI/security, debt, implementation and ADR references now state exclusion/deferral. MAP-032/093 and ADR-015 no longer require a knowledge/vector plane; MAP-035/BIA-033 and ADR-022 no longer require language/voice expansion. MAP-094 retains only limited reliability/What-if, not proactive business investigation.

Old mentions remain intentionally in historical reports (A), explicit current exclusions/conflict explanations (B), clearly superseded earlier plans (C), and existing source/config/tests (D). [48](48_DOCUMENTATION_INVENTORY_AND_SCOPE_REFERENCES.md) enumerates every matching line within the stated search boundary, including broad Arabic matches. Existing Voice/language code, tests and security fixes are preserved. Infrastructure alerts and CDC operational monitoring remain required.

## E. Architecture decisions

- Query remains sole analytical execution authority. Models, MCP and presentation vendors never obtain customer database access.
- Keep logical ownership before physical splits; HTTP control plane, Kafka asynchronous data/event plane. DataSource and Dataset stay distinct; persisted connection metadata is not a permanent socket.
- Preserve existing Integration in Query, encrypted/versioned credentials, v2 references, staged source replacement and direct TLS/DNS/SSRF/egress controls.
- Keep one governed Analyst, published semantic definitions, human-reviewed Modeling proposals, durable jobs/context and minimum scoped Schema/Query tools.
- Reuse existing VisualizationSpec/ChartContract; sanitize its outbound projection rather than send internal Metabase/query metadata.
- **ADR-023 chooses a new Presentation logical domain inside the existing Report deployment, with owned schema and worker. Voice retains legacy saved-report ownership for January.** No new microservice, wholesale report migration or dormant duplicate ORM activation.
- Provider adapters and MCP/REST transports are separate. Governance owns external credentials, approvals and network access.
- Metering uses token/provider/deck/export usage and idempotent reservations/commit/release; Entitlements, Metering, Billing and Payments remain separate.
- Production runtime/dependency support, backup/restore, CI and operations are early workstreams, not a last-week checklist.

## F. Presentation architecture

```text
PresentationProvider
├── SlidesGPTProvider
└── GammaProvider
```

Internal governed analysis → trusted metrics → evidence → charts → analytical narrative → PresentationSpec → outbound data policy/approval → provider → validated private artifact.

[44](44_AI_PRESENTATION_AND_EXECUTIVE_REPORT_ARCHITECTURE.md) specifies request/plan/evidence/slide/spec/job/artifact contracts, categories, the dynamic ten-slide loss example, exact deterministic numerical fixture, reliability warnings, UX, data-egress boundary, threat model, tests, rollout, usage and observability. Fact/contribution/correlation is distinguished from proven cause.

Unknown remote outcome enters reconciliation; it cannot trigger blind retries or fallback charges. Approval binds immutable payload/provider/cost/actor/workspace; downloads reauthorize. Providers receive only approved minimal analytical outputs, never credentials/refs, tokens, physical tables, internal URLs or raw dumps. Export factuality is checked before completion.

Both named adapters and conformance suites remain mandatory. At least one live-certified provider and usable PPTX or PDF export is required; secondary live deployment and format/template breadth are P2. No self-built PPTX/layout engine. Official vendor documentation was researched, but access, confidentiality/retention, cost, idempotency and export behavior remain implementation-time certification gates. Links and limitations are recorded adjacent to claims in 44.

## G. Roadmap through 10 January

| Phase | Dates | Gate / outcome |
|---|---|---|
| P0 | 27 October–2 November 2026 | G-C external Foundation-C closure; evaluation/design/access research |
| P1 | 3–16 November | G-D PostgreSQL CDC; G-J durable jobs/context and scoped AI/provider foundations |
| P2 | 17–29 November | G-S Semantic Layer, metrics and publication |
| P3 | 30 November–6 December | G-M Modeling; evidence/policy/ledger/artifact foundations |
| P4 | 7–15 December | G-A Analyst/Trust/What-if/reliability; G-E approval/egress/reservations |
| P5 | 16–23 December | G-P Presentation analysis/spec/provider/export/factuality |
| P6 | 24–29 December | G-I integrated capability/failure/security/usage acceptance |
| P7 | 30 December–4 January 2027 | G-Q frozen quality/security/runtime/operations candidate |
| P8 | 5–9 January | G-R staging regression/soak, restore/migration/rollback and support readiness |
| Launch | 10 January 2027 | G-L GO only with mandatory immutable-candidate evidence |

Two engineers with reciprocal review, one primary deliverable each, shared-contract handoffs and at least 25% contingency/review/operations capacity. Per-phase engineer-day estimates must still be made; this is an aggressive target, not a validated promise. Detailed entry/current-state/exit/test/deployment/risk criteria and common Definition of Done are in 43/45/26.

## H. Files modified

- [BIAVORA_PRODUCTION_READINESS_AUDIT/08_AI_EVALUATION_AND_TEST_STRATEGY.md](08_AI_EVALUATION_AND_TEST_STRATEGY.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/09_SEMANTIC_LAYER_AND_MODELING_AGENT_PLAN.md](09_SEMANTIC_LAYER_AND_MODELING_AGENT_PLAN.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/10_RAG_AND_KNOWLEDGE_ARCHITECTURE.md](10_RAG_AND_KNOWLEDGE_ARCHITECTURE.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/11_AGENTIC_ARCHITECTURE.md](11_AGENTIC_ARCHITECTURE.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/12_TRUST_EXPLAINABILITY_AND_GOVERNANCE.md](12_TRUST_EXPLAINABILITY_AND_GOVERNANCE.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/13_MCP_ACTIONS_AND_APPROVAL_ARCHITECTURE.md](13_MCP_ACTIONS_AND_APPROVAL_ARCHITECTURE.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/14_SUBSCRIPTION_METERING_REDESIGN.md](14_SUBSCRIPTION_METERING_REDESIGN.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/20_TECHNICAL_DEBT_AND_PROBLEM_REGISTER.md](20_TECHNICAL_DEBT_AND_PROBLEM_REGISTER.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/21_DESIGN_PATTERNS_RECOMMENDATIONS.md](21_DESIGN_PATTERNS_RECOMMENDATIONS.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/22_TARGET_ARCHITECTURE.md](22_TARGET_ARCHITECTURE.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/23_FEATURE_READINESS_MATRIX.md](23_FEATURE_READINESS_MATRIX.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/24_ARCHITECTURE_DECISION_RECORDS_NEEDED.md](24_ARCHITECTURE_DECISION_RECORDS_NEEDED.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/25_14_WEEK_IMPLEMENTATION_ROADMAP.md](25_14_WEEK_IMPLEMENTATION_ROADMAP.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/26_MASTER_REFACTOR_BUILD_DELETE_PLAN.md](26_MASTER_REFACTOR_BUILD_DELETE_PLAN.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/29_CANONICAL_PRODUCT_SCOPE.md](29_CANONICAL_PRODUCT_SCOPE.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/30_CANONICAL_ARCHITECTURE_RULES.md](30_CANONICAL_ARCHITECTURE_RULES.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/31_CANONICAL_SERVICE_OWNERSHIP_MAP.md](31_CANONICAL_SERVICE_OWNERSHIP_MAP.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/32_CANONICAL_AI_ARCHITECTURE.md](32_CANONICAL_AI_ARCHITECTURE.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/33_PRODUCTION_SECURITY_BASELINE.md](33_PRODUCTION_SECURITY_BASELINE.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/34_BIAVORA_MASTER_CONTEXT_FOR_FUTURE_PROMPTS.md](34_BIAVORA_MASTER_CONTEXT_FOR_FUTURE_PROMPTS.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/README.md](README.md)
- [README.md](../README.md)
- [REDESIGN_PLAN.md](../REDESIGN_PLAN.md)
- [REDESIGN_PLAN_PROFILE.md](../REDESIGN_PLAN_PROFILE.md)
- [docs/audit/DATABASE_OWNERSHIP_MATRIX.md](../docs/audit/DATABASE_OWNERSHIP_MATRIX.md)
- [docs/audit/MICROSERVICES_RESTRUCTURING_PLAN.md](../docs/audit/MICROSERVICES_RESTRUCTURING_PLAN.md)
- [docs/audit/PRE_DEVELOPMENT_ACTION_PLAN.md](../docs/audit/PRE_DEVELOPMENT_ACTION_PLAN.md)
- [docs/audit/README.md](../docs/audit/README.md)
- [docs/audit/SERVICE_COMMUNICATION_MATRIX.md](../docs/audit/SERVICE_COMMUNICATION_MATRIX.md)
- [docs/audit/TARGET_MICROSERVICES_ARCHITECTURE.md](../docs/audit/TARGET_MICROSERVICES_ARCHITECTURE.md)
- [etl-final/docs/MIGRATION_CHECKLIST.md](../etl-final/docs/MIGRATION_CHECKLIST.md)
- [etl-final/docs/PARALLEL_RUN_STRATEGY.md](../etl-final/docs/PARALLEL_RUN_STRATEGY.md)
- [etl-final/docs/ROLLOUT_PLAN.md](../etl-final/docs/ROLLOUT_PLAN.md)
- [etl-final/docs/SUCCESS_CRITERIA.md](../etl-final/docs/SUCCESS_CRITERIA.md)

## I. Files created

- [BIAVORA_PRODUCTION_READINESS_AUDIT/43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md](43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/44_AI_PRESENTATION_AND_EXECUTIVE_REPORT_ARCHITECTURE.md](44_AI_PRESENTATION_AND_EXECUTIVE_REPORT_ARCHITECTURE.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/45_BIAVORA_RELEASE_TRACEABILITY_MATRIX.md](45_BIAVORA_RELEASE_TRACEABILITY_MATRIX.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/46_ADR_023_PRESENTATION_OWNERSHIP_AND_PROVIDER_ABSTRACTION.md](46_ADR_023_PRESENTATION_OWNERSHIP_AND_PROVIDER_ABSTRACTION.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/47_SCOPE_ARCHITECTURE_RECONCILIATION_REPORT.md](47_SCOPE_ARCHITECTURE_RECONCILIATION_REPORT.md)
- [BIAVORA_PRODUCTION_READINESS_AUDIT/48_DOCUMENTATION_INVENTORY_AND_SCOPE_REFERENCES.md](48_DOCUMENTATION_INVENTORY_AND_SCOPE_REFERENCES.md)
- [scripts/check_release_documentation.py](../scripts/check_release_documentation.py)

The sole executable addition is a deterministic documentation inventory/checker, not application functionality. Temporary authoring scratch files outside the repository were removed after use.

## J. Historical files intentionally unchanged

Numbered **00–07, 15–19, 27 JSON, 28, 35 and 36–42** remain byte-preserved relative to HEAD. In particular, all Foundation reports preserve chronology and scoped evidence; no status was rewritten to manufacture consistency or readiness. All P0/P1/P1-R remediation implementation/test reports and ETL Test-File reports remain unchanged. Existing source/configuration/tests and TimesFM remain untouched.

Old supporting plans received a supersession banner with their bodies preserved. Root README's service/dependency overview was corrected against current Compose, including Subscription/Notification and containerized Metabase/Redis; development instructions otherwise remain documentation.

## K. Conflicts found and resolved

| Earlier statement / ambiguity | Resolution |
|---|---|
| Rolling Week-14 scope/date and readiness percentages | Fixed 10 January target; exact 14-capability evidence matrix; old scores explicitly historical |
| RAG/proactive/language expansion in roadmap/AI/ADR/map | Excluded or deferred; historical evidence retained and indexed |
| Remove Kafka / HTTP-only older restructuring | Banner supersedes it; HTTP control, Kafka data/event pipeline retained |
| Report is already the persistence owner or should be deleted | Source shows proxy/Voice ownership; ADR-023 adds new domain without wholesale legacy migration |
| Registry/snapshot success implies production multi-engine CDC | Explicit engine/mode/certification matrix; PostgreSQL-only required CDC |
| Python TLS/pinning proof applies to Debezium | Connect's driver/credential/egress path needs separate certification |
| Job model/comment implies working durable orchestration | Active synchronous route and missing alternate modules documented; G-J remains open |
| AI metadata enumeration/global cache is acceptable schema context | Authorized minimum scoped tools and cache versioning required |
| Local C6 GREEN or old committed-state wording proves current release | Local scope retained; external gates and exact-SHA remote CI remain unproved |
| Raw request counters are sufficient production metering | Resource-aware reservation/ledger and provider-cost reconciliation required |
| Presentation means forwarding a prompt to a vendor | Internal authoritative analysis/evidence/spec before governed rendering |
| Existing Metabase path implies all external renderers may query | Existing scoped rendering compatibility disclosed; deck vendors never receive warehouse access |

## L. Current critical path / exact next implementation

**Foundation-C external closure is next.** Obtain controlled staging and operator-provided secrets/workload identity; inspect authoritative exact-SHA CI; prove managed key/identity rotation, combined public verify-full TLS/egress/DNS source lifecycle, and actual v1 retention/drain. No credentials or public database were invented.

Then G-C → PostgreSQL CDC + durable/context/provider/AI authorization foundations → Semantic → Modeling → Analyst/evidence/What-if/reliability + egress/approval/metering → Presentation → convergence → quality/operations → RC. No Foundation-D, CDC, Semantic or Presentation code was started by this task. Only bounded design/research/evaluation-corpus and unrelated hardening exceptions are documented while G-C is blocked.

## M. Ranked launch risks

| Rank | Risk | Required response |
|---|---|---|
| BLOCKER | C external staging/identity/public TLS/egress/Kafka drain; remote CI unverified | Close G-C with actual operator/environment evidence |
| CRITICAL | Missing durable context, broad AI schema access, unsupported/unpinned/development runtime and deployed recovery gaps | G-J and supported-runtime/operations track; no public exposure assumption |
| CRITICAL | Serial scope exceeds unvalidated two-person capacity; provider access/privacy/export uncertainty | Early estimates/checkpoints and provider certification; reduce P2 only |
| HIGH | CDC mutable-state/DDL/restart correctness; report ownership migration; factuality, duplicate costs and ledger reconciliation | Deterministic/live failure matrices, bounded ADR-023, reconciliation state |
| MEDIUM | Forecast capacity/artifacts, constrained UX and frontend size | Bound supported scenarios; clear degraded states and measured capacity |
| LOW | Cosmetic/debug/deprecation cleanup | Defer unless tied to a demonstrated gate failure |

Runtime facts were read locally. Supported-version selection must use current official lifecycle sources at implementation: [Django downloads/support](https://www.djangoproject.com/download/) and [Python version status](https://devguide.python.org/versions/). No automatic framework upgrade is performed here.

## N. Scope and schedule risks

There are roughly eleven calendar weeks, not fourteen unrestricted development weeks. CDC, durable execution, semantics, governed actions, two adapter mappings and production operations are substantial missing work. Holidays, external setup, reviews and defects reduce capacity. Presentation vendor integration does not remove BI analysis, egress or artifact-verification work.

Cut optional template breadth, secondary live provider, extra network-engine certification, advanced forecasts/diagnostics/reliability, independent extra actions and broad UI cleanup first. Preserve mandatory CDC, semantics, Analyst, one governed presentation action/export, evidence, security, metering and operations. Missed checkpoints force re-estimation and an explicit scope/date decision; keep January 10 visible, never silently move it or waive safety. No new feature enters unless it replaces scope or fixes a blocker/security/correctness/operations requirement.

## O. Validation and limits

- `python -X utf8 scripts/check_release_documentation.py --write-inventory`: PASS after completing the report. Checks changed Markdown relative links, balanced fences, table shape/text hygiene, all 14 ordered capability rows in 43/45, preserved MAP IDs and all 42 BIA rows, unchanged historical files and documentation-only changes.
- **40 changed/new Markdown files** checked; **9 Mermaid blocks** checked structurally. Diagrams were not rendered with a Mermaid engine; structural checking is not graphical validation.
- Removed-feature search: **174 documentation/reference files** inventoried excluding catalog 48; **42 matching files**, **171 occurrences**: A historical 46; B current exclusions/deferrals 59; C superseded bodies 60; D maintained source/config/tests 6. Catalog/report/checker self-references and third-party/private-data paths are excluded explicitly in 48.
- Current scope and duplicate-plan review: 43/45 share CAP-01–14; current 20/22–26/29–34/README agree on exclusions, date and dependencies. Old Week-14 references remain only as historical descriptions, legacy filenames or in explicitly superseded bodies. Review is semantic/manual plus deterministic indexing; a keyword scan alone cannot prove scope correctness.
- `git diff --check`: PASS, exit 0 after removing three added trailing-space issues.
- `git diff --stat --ignore-submodules=all`: **34 tracked Markdown files changed; 591 insertions, 965 deletions**. This stat omits **7 untracked additions**: six numbered Markdown documents (43–48) and one documentation checker. Total authored change set: 40 Markdown files plus one helper script.
- Historical report immutability and superseded-body preservation checked against HEAD; no application/config/test/migration/dependency/workflow diff.
- Final branch/HEAD unchanged; staged diff empty; pre-existing TimesFM remains the sole unrelated dirty path. New files are deliberately untracked because staging/commit was not authorized.
- Official provider documentation was read only; no customer data sent and no provider generation/account certification. Remote CI/staging/application tests were not run.

Reproduce from repository root:

```powershell
python -X utf8 scripts/check_release_documentation.py --write-inventory
git diff --check
git diff --stat --ignore-submodules=all
git status --short
```

These checks validate document consistency, not product correctness. Application, Docker, integration, vendor and staging suites were not run for this documentation-only task. Historical test results are cited as historical. No new production-readiness GREEN, current readiness percentage or vendor certification is claimed.

## P. No-code confirmation

**No production code, application tests, migrations, dependencies, infrastructure configuration or CI workflow changed.** Changes are Markdown plus one small deterministic documentation-support script. No later-phase feature implementation, deployment, provider generation, destructive operation, staging, commit or push occurred. Dirty TimesFM was preserved.
