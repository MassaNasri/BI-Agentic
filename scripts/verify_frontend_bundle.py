#!/usr/bin/env python3
"""Reject private or development endpoints from the production frontend bundle."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "frontend" / "dist"
FORBIDDEN = (
    "http://127.",
    "https://127.",
    "http://localhost:",
    "https://localhost:",
    "host.docker.internal",
    "://auth-service",
    "://workspace-service",
    "://query-service",
    "://visualization-service",
    "clickhouse://",
    "postgresql://",
    "surrealdb",
)


def main() -> int:
    if not DIST.is_dir():
        print("frontend/dist does not exist; run npm run build first", file=sys.stderr)
        return 1
    violations: list[str] = []
    for path in DIST.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        lowered = text.lower()
        for token in FORBIDDEN:
            if token in lowered:
                violations.append(f"{path.relative_to(ROOT)} contains {token!r}")
    if violations:
        print("Frontend production configuration gate failed:", file=sys.stderr)
        print("\n".join(f"- {item}" for item in violations), file=sys.stderr)
        return 1
    print("Frontend production configuration gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
