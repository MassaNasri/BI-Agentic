# Trust, explainability, and governance

> **v2 canonical alignment:** Trust is a platform contract. Week-14 answers expose permission-filtered tables/columns, SQL, metric definitions, filters, time range, semantic version, query timestamp, freshness, document citations, assumptions, warnings/degraded state, and forecast uncertainty where applicable. Confidence must combine deterministic evidence and evaluation/calibration; LLM self-report is never sufficient.

## Current foundation

Voice reports persist transcription, intent, generated/final SQL, preprocessing, pipeline trace, AI trace, query rows, chart config, execution timing, and Metabase IDs. The frontend has an eight-stage AI trace panel. ETL attaches lineage/quality fields and stores metadata in SurrealDB. These are useful debugging artifacts.

They are not yet a trust layer. Traces are implementation-centric, confidence is heuristic, data/semantic versions are missing, source freshness is incomplete, report rows are copied into PostgreSQL, citations do not exist, and full attempts/debug fields can reveal schema, values, model errors, or internal “reasoning”.

## Answer evidence contract

Every analytical response should carry a stable `answer_id` and a separate, permission-checked evidence resource:

| Field | Requirement |
|---|---|
| Answer | Concise result and units; distinguish observed, inferred, forecast, and recommended content |
| Confidence | Component signals with reason; never an unexplained pseudo-probability |
| Metric definitions | Metric ID/name/formula/owner/certification/semantic version |
| SQL/query | Normalized SQL, query ID/hash, execution service, time, resource/degraded status |
| Data lineage | Source ID/type, dataset/table/columns, filters, joins, time range, workspace |
| Freshness/quality | Source event/checkpoint, ingestion/CDC timestamp, lag, quality warnings |
| Unstructured evidence | Document/version/page/section/chunk citations and quoted span pointer |
| Forecast/scenario | Model/version, horizon, baseline, assumptions, quantiles/uncertainty, fallback |
| Visualization | Chart spec, axes/series, source query ID, Metabase object/version |
| Governance | Actor, policy decisions, prompt/model/tool versions, approval/audit IDs |
| Warnings | Stale data, incomplete evidence, fallback, ambiguity, permission-limited context |

## Confidence design

Do not average arbitrary stage scores. Report evidence-backed dimensions:

- transcription quality signal;
- intent/classification calibration bucket;
- semantic resolution (certified/exact/alias/proposed/ambiguous);
- SQL validation and result execution status;
- retrieval support/citation coverage;
- forecast calibration/fallback;
- data freshness/quality.

The final label (`high`, `medium`, `low`, `degraded`) is a transparent rule over those signals. A hard failure or stale/unauthorized source cannot be masked by high model confidence.

## Chain-of-thought boundary

The UI currently surfaces fields named reasoning and extensive pipeline attempts. Production explainability should expose a **decision summary**, not private chain-of-thought:

- interpreted request and selected metric;
- why a source/table/tool was selected;
- validation and policy outcomes;
- SQL/evidence/assumptions;
- alternatives or ambiguity;
- fallback/warning.

Redact prompt bodies, secrets, tokens, raw customer samples, internal stack traces, hidden model reasoning, and provider metadata not needed by the user. Separate user evidence from privileged operator diagnostics with different retention/access.

## Governance records

- Immutable semantic model versions and approvals.
- Prompt/model/provider registry with deployment/evaluation status.
- Dataset/source versions and freshness checkpoints.
- Analysis job and tool-call audit with input/output references and hashes.
- Knowledge document/version/ACL/citation lifecycle.
- Action proposal/approval/execution records.
- Usage/cost ledger and policy decisions.
- Retention/deletion and legal hold state.

Audit logs must be append-only/tamper-evident enough for project scope, timestamped in UTC, workspace/actor scoped, searchable, access-controlled, and exported to central storage. Do not rely on mutable report JSON alone.

## Data lineage target

Create stable IDs across Source → SourceTable → Ingestion/CDC checkpoint → ClickHouse table/version → Semantic Entity/Metric → Query execution → Report/Visualization → Answer. ETL's existing lineage metadata can seed the physical portion, but legacy load-status records must preserve workspace/dataset/job scope and current SurrealDB persistence needs backup/HA/version contracts.

## Governance policies

- Publish semantic models only after human approval.
- Models/prompts/providers must pass required evaluation before promotion.
- Queries require exact workspace/dataset/table binding and resource policy.
- Customer data sent to external providers requires explicit provider/data-region/retention policy.
- Sensitive values are excluded/minimized from prompts, events, logs, traces, and DLQs.
- Documents are untrusted content; ACL and injection protections precede retrieval.
- Forecasts state uncertainty and assumptions; causal claims require separate approval/evidence.
- Actions require policy plus human approval; no unrestricted autonomous writes.

## UX

Default answer view should be simple. An expandable “How this was produced” panel shows metric definition, freshness, SQL, sources, filters, citations, assumptions, and warnings. Operators get a separate diagnostics view. Arabic/RTL evidence rendering and localized metric descriptions must be designed, not inferred from Whisper.

## Week-14 production acceptance

For every showcased answer, an evaluator must be able to reproduce the query or retrieval against the recorded dataset/semantic/document version, verify each cited claim, see freshness/quality, understand forecast assumptions, and confirm no hidden cross-workspace evidence. Automated lineage/citation tests and a manual evidence review are release gates.
