# AI evaluation and test strategy

> **v2 scheduling decision:** Evaluation begins in **Week 1**, in parallel with platform work. The first gate requires a versioned English/Arabic voice, intent, schema-resolution, text-to-SQL, safety, and provider-contract corpus plus prompt/model registry. Every later semantic, RAG, agent, forecast, What-if, and MCP capability must add cases before its feature gate and must pass the production release thresholds defined below.

## Current evidence

The maintained deterministic AI selection passed **235 tests plus 12 subtests**. It covers semantic rules, temporal behavior, structured intent, SQL review, forecast transformations, value index behavior, recovery, and pipeline integration with mocks/fixtures. This is a strong regression base, but not a model-quality program: no versioned real-world benchmark, WER/CER corpus, execution-accuracy dataset, Arabic set, RAG set, agent set, calibration, or production shadow evaluation is part of the release gate.

## Evaluation artifact model

Each case should have: immutable case ID/version; workspace-safe synthetic or consented input; language/dialect/noise tags; dataset/schema snapshot; semantic model version; expected intent/SQL/result/evidence; allowed equivalence; risk class; and reviewer provenance. Each run records commit, container digests, model/provider/version, prompt version, parameters/seed, tool versions, latency, tokens/cost, output, judge evidence, and failure class.

Use three layers:

1. **Deterministic CI (<15 min, no paid calls):** parsing, contracts, compiler, safety, fixed mocked model outputs, small local golden set.
2. **Nightly/weekly model evaluation:** pinned local model plus budget-capped external models against full golden/adversarial/multilingual sets.
3. **Human release evaluation:** blind review of sampled changes, Arabic/domain cases, agent/tool behavior, and failure explanations.

## Metrics and datasets

| Capability | Required datasets | Primary metrics / release checks |
|---|---|---|
| Voice/STT | Clean/noisy English; MSA; Levantine/Gulf/Egyptian samples; code-switch; accents; numbers, dates, currencies, BI terms | WER, Arabic-aware CER, normalized numeric/date/currency accuracy, language/dialect slices, empty/hallucinated segment rate, real-time factor, p95 latency |
| Intent classification | Balanced analytical, predictive, conversational, unsafe, ambiguous, out-of-domain; hard negatives | Accuracy, macro/micro precision/recall/F1, confusion matrix, per-class and language slice, abstention precision, calibration/Brier or ECE |
| Schema resolution | Single/multi-table schemas, ambiguous aliases, decoys, PII, tenant lookalikes | Table/column/entity/join-path top-1 and top-k accuracy; unauthorized selection rate must be zero |
| Text-to-SQL | Synthetic and realistic ClickHouse questions with canonical data | Parse validity, execution success, result-set equivalence, semantic correctness, exact-match secondary, hallucinated identifier rate, unsafe rejection recall/precision, cross-tenant attempt denial |
| Semantic layer | Versioned metric/entity cases and reviewer decisions | Metric/entity/relationship accuracy, formula equivalence, owner/certification enforcement, proposed-model human acceptance and edit distance |
| RAG | Permissioned policies/manuals/contracts with answerable/unanswerable questions | Retrieval precision/recall@k, MRR/nDCG, context relevance, groundedness, citation correctness/span support, faithfulness, permission leakage=0, abstention quality |
| Analyst agent | Multi-step analysis tasks with tool traces and result facts | Task completion, tool-selection accuracy, invalid/repeated tool rate, SQL/result correctness, unsupported claim rate, policy violation=0, cost/latency budget |
| Proactive monitoring | Seeded anomalies and normal periods | Precision/recall, false alerts per monitored metric/week, time to detect, deduplication, usefulness rating, evidence completeness |
| Reliability | Freshness, null, duplicate, schema drift, lag, connectivity fault injections | Detection recall/precision, recovery correctness, false-positive rate, run idempotency |
| Forecast/what-if | Rolling-origin time series by frequency/length/seasonality and scenario fixtures | MAE/RMSE/sMAPE/MASE versus naive baselines, interval coverage/calibration, assumption completeness, repeatability; causal-claim violation=0 |
| Trust | Known SQL/lineage/citation/metric versions | Source/column/filter/time-range lineage accuracy, citation support, freshness accuracy, evidence/answer consistency |

## Golden data design

- Use small public/synthetic business datasets whose answers can be computed deterministically.
- Include wide/long tables, nulls, duplicated labels, reserved words, Unicode/Arabic identifiers, time zones, mixed numeric strings, adversarial table names, and two tenants with intentionally similar schemas.
- Store expected **results**, not only exact SQL; semantically equivalent SQL should pass.
- Version raw audio and normalized transcripts separately. Human transcribers should adjudicate disagreement.
- Keep customer data out of the repository. Production feedback must be sampled only with consent, redaction, retention, and access controls.

## Adversarial suites

1. Prompt injection in question, schema descriptions, row values, and future documents.
2. Requests for other workspace/table names and guessed tenant-qualified tables.
3. SQL exfiltration functions, system tables, comments, encodings, CTEs/unions, aliases, nested functions, resource-exhaustion queries.
4. Poison audio, decompression bombs, malformed documents, hidden instructions, OCR text, and oversized context.
5. Model timeouts, invalid JSON, partial streaming, provider 429/5xx, content filters, empty output, confident wrong output.
6. Tool result injection and conflicting evidence.
7. Currency/date/number ambiguity in Arabic and English.

## LLM judge policy

LLM judges are useful for triage and pairwise qualitative comparison but must not be the only release oracle. They are prompt/model sensitive, can prefer verbosity/style, and can miss subtle data errors. Use pinned judge prompts/models, randomized answer order, calibration against human labels, confidence intervals, and periodic drift review. Safety, tenant isolation, SQL execution equivalence, citations, and numeric facts should use deterministic checks.

## Human evaluation

For each release-changing model/prompt/semantic rule, two reviewers independently score a stratified sample for correctness, grounding, usefulness, harmful/unsupported claims, clarity, and appropriate abstention. Arabic evaluation requires fluent reviewers across the claimed dialect scope. Resolve disagreements and publish an evaluation card with known weaknesses.

## CI and quality gates

- Pull request: no regression on deterministic golden set; zero unsafe/cross-tenant successes; schema/contract tests; prompt snapshot review.
- Nightly: full model matrix, cost budget, latency distribution, provider fallback, Arabic/noise slices.
- Weekly: rolling forecast backtests, RAG corpus integrity, red-team prompts, tool loops, calibration.
- Release: statistically meaningful no-regression thresholds, zero critical policy violations, human sign-off, model/prompt/semantic version frozen, rollback candidate retained.
- Production: shadow/canary metrics, user correction feedback, abstention/fallback rate, drift alerts; never learn automatically from raw user input.

## Minimum Week-14 production benchmark

A feasible benchmark is 300–500 text-to-SQL/intent cases across 8–12 synthetic schemas, 100–150 voice utterances across English/MSA/one explicitly named Arabic dialect plus noise/code-switch slices, 50 forecast series, 50 knowledge questions, and 30 multi-tool analyst tasks. The exact threshold must be set from baseline data, not invented in advance. Publish baseline, candidate delta, confidence intervals, failure examples, cost, and latency.
