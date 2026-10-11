"""Framework-independent ETL dependency readiness checks."""

from __future__ import annotations

import os
import socket


def evaluate_tcp_readiness(targets: str | None = None) -> tuple[bool, list[dict[str, object]]]:
    timeout = max(0.1, min(float(os.getenv("READINESS_TIMEOUT_SECONDS", "1.5")), 10.0))
    raw_targets = targets if targets is not None else os.getenv("READINESS_TCP_TARGETS", "")
    checks: list[dict[str, object]] = []
    for target in (item.strip() for item in raw_targets.split(",")):
        if not target:
            continue
        host, separator, raw_port = target.rpartition(":")
        if not separator or not host:
            checks.append({"name": f"tcp:{target}", "ok": False, "detail": "invalid_target"})
            continue
        try:
            with socket.create_connection((host, int(raw_port)), timeout=timeout):
                pass
            checks.append({"name": f"tcp:{target}", "ok": True, "detail": "reachable"})
        except Exception as exc:
            checks.append({"name": f"tcp:{target}", "ok": False, "detail": type(exc).__name__})
    return all(bool(check["ok"]) for check in checks), checks
