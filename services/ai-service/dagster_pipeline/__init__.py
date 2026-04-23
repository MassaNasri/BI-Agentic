from __future__ import annotations

try:
    from dagster import HookContext, RetryPolicy, failure_hook
except ModuleNotFoundError:  # pragma: no cover - exercised in lean test environments
    class HookContext:  # type: ignore[no-redef]
        op_exception = None
        op = type("Op", (), {"name": "unknown"})()
        run_id = ""
        log = type("L", (), {"error": staticmethod(lambda *args, **kwargs: None)})()

    class RetryPolicy:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            self.args = args
            self.kwargs = kwargs

    def failure_hook(fn):  # type: ignore[no-redef]
        return fn


ASSET_RETRY_POLICY = RetryPolicy(max_retries=2, delay=1.0)


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
