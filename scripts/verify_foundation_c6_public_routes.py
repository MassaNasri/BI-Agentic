"""Compare registered service URLs with the reviewed Gateway route inventory.

The inventory is generated from Django URL resolvers, then checked against the
actual Gateway router. Update the checked-in JSON only after reviewing new
routes and their public/internal classification.
"""

import argparse
import ast
import json
import os
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY = ROOT / "scripts" / "foundation_c6_public_route_inventory.json"
SERVICES = {
    "auth-service": "service_config.settings",
    "workspace-service": "service_config.settings",
    "query-service": "service_config.sqlite_test_settings",
    "subscription-service": "service_config.settings",
    "voice-service": "service_config.settings",
    "ai-service": "backend.settings",
    "report-service": "service_config.settings",
    "visualization-service": "service_config.settings",
    "notification-service": "service_config.settings",
    "api-gateway": "service_config.settings",
}
CHILD = r'''
import json, os, django
os.environ["DJANGO_SETTINGS_MODULE"] = os.environ["BIAVORA_ROUTE_SETTINGS"]
django.setup()
from django.urls import URLPattern, URLResolver, get_resolver
def routes(items, prefix=""):
    for item in items:
        path = prefix + str(item.pattern)
        if isinstance(item, URLResolver):
            if path.startswith("admin/"):
                yield "admin/<django-admin>/"
            else:
                yield from routes(item.url_patterns, path)
        elif isinstance(item, URLPattern):
            yield path
print("ROUTES_JSON=" + json.dumps(sorted(set(routes(get_resolver().url_patterns)))))
'''


def _static_ai_routes():
    """Trace the AI URL include graph without importing the Whisper runtime."""
    service_root = ROOT / "services" / "ai-service"

    def visit(module, prefix=""):
        source = service_root / (module.replace(".", "/") + ".py")
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id != "path" or not node.args or not isinstance(node.args[0], ast.Constant):
                continue
            path = prefix + str(node.args[0].value)
            if len(node.args) > 1 and isinstance(node.args[1], ast.Call) and isinstance(node.args[1].func, ast.Name) and node.args[1].func.id == "include":
                include = node.args[1].args[0]
                if isinstance(include, ast.Constant) and isinstance(include.value, str):
                    yield from visit(include.value, path)
            elif path == "admin/":
                yield "admin/<django-admin>/"
            else:
                yield path

    return sorted(set(visit("backend.urls")))


def _sample(path):
    path = re.sub(r"<int:[^>]+>", "1", path)
    path = re.sub(r"<uuid:[^>]+>", "00000000-0000-4000-8000-000000000001", path)
    path = re.sub(r"<(?:str|slug|path):[^>]+>", "sample", path)
    return "/" + path


def _classification(service, path, resolve_target):
    if service == "api-gateway" and path == "^.*$":
        return "PUBLIC"
    if path.startswith("admin/"):
        return "ADMIN_ONLY"
    if path in {"health/", "ready/"}:
        return "INTERNAL_ONLY"
    if "/internal/" in "/" + path or path in {
        "notification/events/", "notification/subscriptions/expiry-warnings/run/",
    }:
        return "INTERNAL_ONLY"
    if service == "subscription-service" and path in {"check-access/", "plans/", "subscribe/"}:
        return "DEPRECATED"
    target = resolve_target(_sample(path))
    if target is None or target.service != service:
        return "UNREACHABLE"
    if service == "subscription-service" and not path.startswith("subscription/"):
        return "DEPRECATED"
    return "PUBLIC"


def current_inventory():
    sys.path.insert(0, str(ROOT / "services" / "api-gateway"))
    from gateway.routing import resolve_target

    inventory = {}
    for service, settings in SERVICES.items():
        if service == "ai-service":
            paths = _static_ai_routes()
            inventory[service] = {path: _classification(service, path, resolve_target) for path in paths}
            continue
        environment = dict(os.environ)
        environment.update({
            "APP_ENV": "test", "BIAVORA_ROUTE_SETTINGS": settings,
            "PYTHONPATH": str(ROOT),
            "DJANGO_SECRET_KEY": "route-inventory-test-only-signing-key-0123456789",
        })
        result = subprocess.run(
            [sys.executable, "-c", CHILD], cwd=ROOT / "services" / service,
            env=environment, capture_output=True, text=True, timeout=90,
        )
        if result.returncode:
            raise RuntimeError(f"{service} URL resolver failed: {result.stderr[-1200:]}")
        lines = [line.removeprefix("ROUTES_JSON=") for line in result.stdout.splitlines()
                 if line.startswith("ROUTES_JSON=")]
        if len(lines) != 1:
            raise RuntimeError(f"{service} URL resolver produced no inventory")
        inventory[service] = {
            path: _classification(service, path, resolve_target)
            for path in json.loads(lines[0])
        }
    return inventory


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-reviewed-baseline", action="store_true")
    args = parser.parse_args()
    current = current_inventory()
    if args.write_reviewed_baseline:
        INVENTORY.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        expected = json.loads(INVENTORY.read_text(encoding="utf-8"))
        if current != expected:
            changed = {
                service: {"added": sorted(set(current[service]) - set(expected.get(service, {}))),
                          "removed": sorted(set(expected.get(service, {})) - set(current[service])),
                          "reclassified": sorted(path for path in set(current[service]) & set(expected.get(service, {}))
                                                 if current[service][path] != expected[service][path])}
                for service in current
            }
            raise SystemExit("Public route inventory changed; review classifications: " + json.dumps(changed))
    print("C6 registered URL / Gateway route inventory PASS: "
          + ", ".join(f"{service}={len(routes)}" for service, routes in current.items()))


if __name__ == "__main__":
    main()
