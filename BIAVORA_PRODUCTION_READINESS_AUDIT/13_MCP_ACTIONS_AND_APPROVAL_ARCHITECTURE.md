# MCP actions and approval architecture

> **v2 canonical alignment:** MCP/action support is a planned product feature. Week 14 must prove one useful action end-to-end with `PROPOSE -> POLICY VALIDATE -> HUMAN APPROVE -> TOOL GATEWAY EXECUTE -> AUDIT RESULT`. No model receives write credentials or can bypass approval. Expired/replayed approvals and ambiguous parameters must fail closed.

## Current state

No MCP client/server/tool gateway or action workflow exists. `Plan.has_mcp_access` is only a subscription flag. No tool registry, approval state, action policy, scoped credentials, idempotency, or execution audit was found.

## Safety principle

```text
Agent proposes -> deterministic policy check -> human reviews exact action
-> short-lived approval -> isolated Tool Gateway -> execute once -> verify/audit result
```

The analyst orchestrator never receives third-party write credentials. It can create an action proposal, not execute it directly.

## Components

| Component | Responsibility |
|---|---|
| Tool registry | Versioned tool name, owner, schemas, risk, scopes, timeout, idempotency, reversibility, enabled workspaces |
| Policy engine | Actor/workspace role, entitlement, data classification, allowlist, amount/target limits, business-hours/dual approval rules |
| Proposal service | Immutable normalized command, human-readable diff/preview, evidence, expiry, dedupe key |
| Approval service/UI | Pending/approved/rejected/expired/cancelled state; approver cannot be silently impersonated by agent |
| Tool Gateway | Fetches scoped secret, validates approval hash, executes allowlisted adapter/MCP tool, records result |
| Audit/evidence | Request/approval/execution/result/verification IDs, timestamps, actor, tool version, external correlation ID |

## State machine

`DRAFT -> POLICY_REJECTED | PENDING_APPROVAL -> REJECTED | EXPIRED | APPROVED -> EXECUTING -> SUCCEEDED | FAILED | UNKNOWN -> RECONCILED`

`UNKNOWN` is essential for timeouts after a remote system may have committed. Reconcile by idempotency/external correlation ID before any retry. Approval binds the canonical command hash, target, scope, and expiry; any mutation invalidates it.

## Tool contract

Each tool declares:

- JSON input/output schema and version;
- required workspace/actor scopes and entitlement;
- read/write/financial/destructive risk class;
- reversible/irreversible behavior and compensation if any;
- idempotency-key support;
- validation/preview method;
- timeout/retry policy and rate/cost limits;
- credential owner and allowed network destinations;
- audit/redaction and data residency policy.

Adapters form an anti-corruption layer so vendor/MCP response details do not enter the agent contract.

## Minimum Week-14 production scope

Implement proposal/approval/audit infrastructure and one genuinely useful, low-risk action integration end-to-end, preferably a reversible notification or ticket creation/update. It must require explicit approval, use an idempotency key, display the exact payload/destination, verify the result, and produce an audit record. Production scope excludes payments, deletes, source SQL writes, credential changes, and unrestricted messaging.

## Security requirements

- Per-tool/workspace OAuth or secret reference in a vault; no secrets in prompts, browser, Kafka, logs, or approval records.
- Egress allowlist and SSRF-safe connector.
- Short-lived execution token bound to proposal/approval/tool/version.
- CSRF-safe approval, reauthentication for high risk, optional two-person approval.
- Tool output treated as untrusted; it cannot inject instructions.
- Strict payload/response size and time bounds; sandbox file/document parsers.
- Revocation immediately prevents pending execution.
- Notification on action result and searchable audit trail.

## MCP-specific rule

MCP is a transport/protocol, not an authorization model. Register each MCP server and tool explicitly, pin/verify its origin/version, filter exposed tools, mediate every call through local policy, and never hand a raw remote MCP session to the LLM. A tool-list change is a security-sensitive deployment requiring review/evaluation.

## Testing

Cover unauthorized workspace/role, stale/modified/duplicate approval, expiry, concurrent approval, timeout-after-commit, provider 429/5xx, replay, secret redaction, malicious tool output, external ID reconciliation, reversible compensation, and audit completeness. Zero unapproved execution is a release invariant.
