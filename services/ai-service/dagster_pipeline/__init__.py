from __future__ import annotations

from dagster import HookContext, RetryPolicy, failure_hook


ASSET_RETRY_POLICY = RetryPolicy(max_retries=1, delay=1.0)


@failure_hook
def pipeline_failure_hook(context: HookContext) -> None:
    exception = getattr(context, "op_exception", None)
    exception_type = type(exception).__name__ if exception else "unknown"
    context.log.error(
        "Dagster asset failure | asset=%s op=%s run_id=%s exception_type=%s error=%s",
        context.op.name,
        context.op.name,
        context.run_id,
        exception_type,
        str(exception) if exception else "n/a",
    )

