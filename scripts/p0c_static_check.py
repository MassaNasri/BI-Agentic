#!/usr/bin/env python3
"""Fast correctness gate for maintained first-party Python source."""

from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROOTS = (ROOT / "bi_platform_shared", ROOT / "services", ROOT / "etl-final", ROOT / "scripts", ROOT / "tests")
EXCLUDED_PARTS = {
    ".git",
    ".hypothesis",
    ".pytest_cache",
    "__pycache__",
    "backups",
    "node_modules",
    "timesfm",
    "venv",
}
MERGE_MARKER = re.compile(r"^(<{7}|={7}|>{7})(?:\s|$)", re.MULTILINE)


def maintained_python_files() -> list[Path]:
    return sorted(
        path
        for root in ROOTS
        if root.exists()
        for path in root.rglob("*.py")
        if not EXCLUDED_PARTS.intersection(path.relative_to(ROOT).parts)
    )


def main() -> int:
    failures: list[str] = []
    files = maintained_python_files()
    for path in files:
        try:
            source = path.read_text(encoding="utf-8-sig")
            if MERGE_MARKER.search(source):
                failures.append(f"{path.relative_to(ROOT)}: unresolved merge marker")
                continue
            compile(source, str(path), "exec", dont_inherit=True)
        except (OSError, SyntaxError, UnicodeError) as exc:
            failures.append(f"{path.relative_to(ROOT)}: {type(exc).__name__}: {exc}")

    if failures:
        print("Python/static gate failed:", file=sys.stderr)
        print("\n".join(f"- {failure}" for failure in failures), file=sys.stderr)
        return 1
    print(f"Python/static gate passed: {len(files)} maintained files compiled; no merge markers found.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
