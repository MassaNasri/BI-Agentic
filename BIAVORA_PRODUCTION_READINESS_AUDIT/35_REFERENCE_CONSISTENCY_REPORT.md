# 35 — Reference Consistency Report

> **Reference Version:** 2.0  
> **Status:** APPROVED_FOR_IMPLEMENTATION_PLANNING  
> **Target:** Production Deployable in 14 Weeks

## Result

**PASS.** The canonical v2 documents agree on product target, issue classification, ownership, security boundaries, feature order, deployment baseline, and release gates. Current-state evidence may describe unsafe behavior that the target forbids; those are findings, not target contradictions. Historical comparison keys such as `previous_graduation_scope_readiness` in JSON are intentionally retained and labeled previous.

## Contradictions found and resolved

| Contradiction found | Resolution | Files updated / controlling reference |
|---|---|---|
| Graduation/prototype goal versus public production | Week 14 is production-deployable SaaS; current state remains NO-GO | `00`, `05`–`13`, `17`, `18`, `21`, `24`–`35`, `README` |
| Missing CDC classified as Critical/P0 defect | BIA-012 is P1 planned foundation feature; BIA-008/016/017 retain actual unsafe defects | `06`, `20`, `23`, `25`–`29`, `34` |
| “Close BIA-001 through 012” implied a feature is a defect | Release uses hard gates and no-open-P0 rule; CDC passes `CDC_GATE` as feature | `00`, `16`, `20`, `25`, `33` |
| Database-per-service read as physical server split | Logical owner schemas/databases/roles on one managed cluster; physical extraction incremental | `03`, `05`, `22`, `30`, `31`, `34` |
| Query currently owns source lifecycle versus Integration target | Integration is logical owner, initially isolated/co-deployed in Query control plane; workers remain Data Platform | `03`, `06`, `22`, `26`, `30`, `31`, `34` |
| New Integration “service” implied mandatory container | No new container until security/scale/failure/team evidence; explicit extraction seam | `03`, `06`, `22`, `30`, `31`, `34` |
| HTTP coupling treated as inherently wrong | HTTP is control plane; Kafka/events are data and long-running event plane | `03`, `22`, `25`, `30`, `34` |
| Voice direct fallback versus Query authority | Query is sole analytical executor; no Voice/AI/Report/Viz direct CH credential/fallback | `00`, `15`, `16`, `20`, `22`, `30`, `32`–`34` |
| Long work described as wholly absent job model | `VoicePipelineJob` skeleton exists but orchestration is missing/unwired; common durable model remains P0 | `07`, `20`, `25`, `26`, `28`, `32`, `34` |
| Provider telemetry scheduled too late | ModelProvider and raw usage telemetry start Week 1/2; ledger/billing complete later | `07`, `14`, `23`, `25`, `26`, `30`, `32`, `34` |
| Multiple-agent implication versus bounded system | One governed Analyst Orchestrator with typed tools; worker pools only for compute/isolation | `00`, `07`, `11`, `22`, `25`, `29`–`34` |
| Semantic/RAG/AI eval/Arabic absence inflated as defects | BIA-022/023/024/033 converted to planned features; unsafe dependencies remain defects | `08`–`12`, `20`, `23`, `27`–`29`, `32`, `34` |
| MCP could be merely read-only demo or autonomous execution | One useful action executes only after policy + human approval via isolated Tool Gateway | `11`, `13`, `22`, `25`, `29`–`34` |
| Payment, quota, billing, and metering conflated | Entitlements, Metering Ledger, Billing State, Payment Provider separated; simulation disabled now, real provider before paid launch | `14`, `20`, `23`, `25`–`34` |
| Request count versus token-only metering | Resource-aware usage events plus idempotent reservation/commit/release/adjustment and price versions | `14`, `22`, `25`, `29`–`34` |
| RAG could absorb structured warehouse data | Structured facts use Semantic/Query; unstructured knowledge uses permissioned pgvector RAG | `10`, `22`, `25`, `29`, `30`, `32`, `34` |
| Target was production-aligned but not deployable | Managed staging/production, secure runtime, observability, restore, migration/rollback, CI/CD and public release gate are mandatory | `16`, `22`, `25`, `26`, `29`, `30`, `33`, `34` |
| Dead code list implied deletion urgency | DELETE_SAFE/DELETE_AFTER_MIGRATION/INVESTIGATE rules require import/route/Compose/test/CI/runtime/migration proof | `19`, `26`, `30`, `34` |
| v1 scores/counts repeated after new classification | v2 uses 36 production, 24 implementation, 18 scope production readiness; 36 defects + 6 features; P0=9 | `00`, `07`, `15`, `16`, `20`, `23`, `27`, `28`, `README` |

## Canonical agreement checklist

| Decision | Consistent result |
|---|---|
| Target | Public production deployability in 14 weeks; not production-ready today |
| Query | Sole analytical execution authority with exact workspace/dataset/table binding |
| Integration | Logical capability first, co-deployed initially, explicit extraction trigger |
| PostgreSQL ownership | Managed cluster allowed; critical owner schemas/databases/roles mandatory |
| Transport | Direct secure Internet now; private/agent post-launch without model redesign |
| CDC | PostgreSQL mandatory; MySQL/MariaDB conditional; other modes honestly labeled |
| Jobs | Shared durable state machine for long work |
| AI | One orchestrator, typed tools, in-process provider facade, Week-1 eval/telemetry |
| Semantic | Foundational published/versioned/human-approved context |
| RAG | Permissioned unstructured retrieval; structured truth remains Query/Semantic |
| Actions | Proposal/policy/human approval/isolated gateway/audit |
| Metering | Resource-aware immutable ledger separated from entitlement/billing/payment |
| Runtime | Managed production approach; Kubernetes/multi-region not mandatory |
| Release | Seven hard gates ending in evidence-backed `PRODUCTION_GATE` |

## Mechanical validation

- Expected files `00`–`35` plus `README` exist: **PASS** (37 files total).
- `27_FINAL_AUDIT_RESULTS.json` parses: **PASS**.
- JSON defect counts: **BLOCKER 4 / CRITICAL 7 / HIGH 13 / MEDIUM 10 / LOW 2 = 36**: **PASS**.
- JSON kinds: **36 defects + 6 planned features = 42**: **PASS**.
- JSON priorities: **P0 9 / P1 21 / P2 8 / P3 4 = 42**: **PASS**.
- Feature arithmetic: implementation `380/16=23.75→24`; production readiness `286/16=17.875→18`; target `1320/16=82.5→83`: **PASS**.
- Platform arithmetic: `472/13=36.3077→36`: **PASS**.
- Roadmap has exactly Week 1 through Week 14 headings and SE/AI/Shared/dependency/acceptance content: **PASS**.
- Canonical `29`–`35` headers contain Version 2.0, approved planning status, and 14-week target: **PASS**.
- Searches for obsolete forward-looking “graduation scope/target/deliverable,” old readiness scores, mandatory Integration Service, and CDC-as-P0 language show no unresolved target contradiction: **PASS**. Historical comparison and current-state evidence are explicitly labeled.
- No implementation/configuration/test/migration/CI/runtime file was modified: **PASS**. Final Git status contains only the audit directory plus the pre-existing dirty TimesFM submodule; tracked parent-repository diff names are empty.

## Authority rule

Runtime code/config/tests remain evidence authority for what exists. Canonical v2 documents `29`–`34` control what should be built. `34_BIAVORA_MASTER_CONTEXT_FOR_FUTURE_PROMPTS.md` is the mandatory entrypoint. If implementation reality changes, update evidence, register, roadmap, JSON, and canonical documents together; do not silently let them drift.
