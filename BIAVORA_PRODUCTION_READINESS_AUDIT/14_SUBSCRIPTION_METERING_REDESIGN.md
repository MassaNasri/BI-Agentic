> **SUPERSEDED SUPPORTING PLAN — 2026-10-27.** The body below preserves prior design context, not January commitments. Product Scope revision dated 2026-10-27 in [43](43_BIAVORA_PRODUCT_SCOPE_AND_RELEASE_ROADMAP_2027.md), current architecture 22/30–34, and presentation 44/46 control. Structured & Unstructured RAG, Proactive Monitoring Agent and Arabic & Voice Support expansion are OUT OF JANUARY 10 RELEASE SCOPE; do not implement their old milestones. Existing functionality/security remains maintained.

# Subscription and metering redesign

> **v2 canonical alignment:** Treat Entitlements, Metering, Billing State, and Payment Provider as separate owned concepts. The production simulation bypass is a P0 financial-integrity defect and must be disabled immediately; a real hosted/tokenized provider is required before paid public launch, but can land later in the roadmap. Raw provider/model/token/cost/latency telemetry starts with the Week-1 provider facade. The ledger uses idempotent `Reservation -> Commit/Release`, adjustments, immutable usage events, pricing versions, and workspace attribution.

## Critical current behavior

The checkout is explicitly simulated. `SubscriptionPlansPanel.jsx` collects card number, holder, expiry, CVV, or bank fields only in React state, validates their shape, then sends **only** `workspace_id`, `plan_id`, and `payment_method`. `SubscribeView` deactivates the existing subscription, creates a new active subscription, and writes `Payment(status="success")` without contacting a payment provider.

This must be disabled in production or replaced with a hosted/tokenized provider flow. The application should not collect CVV/card data it does not process, and must never send/store raw card details.

## Current quota behavior

One counter (`voice_requests_used` or free-tier `requests_used`) is incremented under a row lock when voice/text begins. The operation is atomic but lacks:

- idempotency/request ID;
- reserve/finalize/release lifecycle;
- refund on AI/source failure;
- period/billing-cycle buckets beyond resetting on new subscription;
- tokens, model/provider, voice seconds, forecast compute, SQL scan/bytes, storage, source/CDC usage, RAG embeddings/retrieval, or actions;
- immutable usage events and reconciliation;
- cost attribution and admin adjustment audit.

## Target billing truth

Payment provider webhooks are authoritative. Recommended flow:

```text
Browser -> provider-hosted checkout/tokenization
Provider -> signed webhook -> Billing inbox/idempotency
Billing -> payment/subscription state transaction + outbox
Outbox -> entitlement projection/notification
```

Verify webhook signature/timestamp, persist the raw provider event securely, deduplicate by provider event ID, handle out-of-order events, and map provider customer/subscription/payment IDs. Model `pending`, `requires_action`, `paid`, `failed`, `refunded`, `disputed`, and cancellation/renewal states. Money uses currency + integer minor units or precise decimal with explicit currency.

## Entitlements versus usage

Separate:

- **Plan/entitlement:** allowed features, limits, retention, connectors, model tier, action tools.
- **Usage event:** append-only measured fact.
- **Reservation:** temporary budget hold for expensive asynchronous work.
- **Aggregation:** period totals by meter.
- **Adjustment:** auditable credit/debit, never silent counter edit.

Suggested meters:

| Meter | Unit / source |
|---|---|
| Voice | audio seconds and request; AI worker completion |
| LLM | input/output tokens and model cost; provider facade |
| SQL | execution, scanned rows/bytes, output bytes; query service |
| Forecast | series × horizon/model class/compute seconds |
| Ingestion | snapshot rows/bytes and source count |
| CDC | connector-hours and changed rows/bytes |
| Knowledge | stored bytes/pages, embedded chunks/tokens, retrieval calls |
| Actions | approved/executed calls by risk/tool |
| Storage | audio/report/document/retention byte-days where required |

## Usage event contract

`event_id`, `idempotency_key`, workspace, actor, job/request, meter, quantity/unit, occurred/recorded time, plan/price version, model/source/tool attributes, status (`reserved|final|released|adjusted`), cost metadata, and trace ID. Producer outboxes the event with the business transaction; Billing consumes idempotently. Store no raw prompt/query/document content in usage.

## Reservation lifecycle

For variable jobs: estimate maximum → reserve under transaction → execute → finalize actual → release unused. A failed job releases the reservation according to policy. Duplicate client/worker retries reuse the same idempotency key. Hard-limit checks use finalized + active reserved totals. Soft limits warn; overage behavior is explicit.

## API and UX

- Entitlement check is a read API/cache, not a hidden mutating GET with `consume=true`.
- Create-job command includes an idempotency key and returns reservation/job IDs.
- Usage dashboard explains period, meter, included/used/reserved/remaining, and recent jobs.
- Payment UI redirects/embeds provider-hosted secure elements and shows real state; never hand-built raw CVV fields.
- Admin adjustments require reason, actor, before/after, and immutable audit.

## Migration

1. Production feature flag disables simulated checkout immediately.
2. Add provider/customer/payment state and signed webhook inbox.
3. Add plan/price versions, entitlements, meters, usage events/reservations/aggregates.
4. Dual-write voice request as a usage event while preserving current counter; reconcile.
5. Switch enforcement to ledger projections; add LLM/forecast/SQL/ingestion meters incrementally.
6. Retire coarse counters only after reconciliation and rollback window.

## Tests

Provider signature/replay/out-of-order, payment failure/refund/dispute, concurrent subscribe, period rollover/time zone, reservation race, retry/idempotency, partial job failure/release, aggregate rebuild, workspace transfer, plan change/proration policy, entitlement cache staleness, and notification failure. Real provider sandbox E2E is mandatory before calling billing production-ready.
