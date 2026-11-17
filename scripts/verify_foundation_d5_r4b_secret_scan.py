"""Bounded known-fixture secret scan; never prints secret material."""

import argparse
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--repo', required=True)
    parser.add_argument('--run-id', required=True)
    args = parser.parse_args()
    env_file = Path(args.env_file).resolve()
    repository = Path(args.repo).resolve()
    evidence = env_file.parent
    values = {}
    for line in env_file.read_text(encoding='utf-8').splitlines():
        if '=' not in line:
            continue
        key, value = line.split('=', 1)
        if (len(value) >= 12 and value and any(marker in key.upper()
                for marker in ('PASSWORD', 'SECRET', 'TOKEN', 'KEY'))):
            values[key] = value.encode('utf-8')
    matches = []
    files = sorted(evidence.glob('d5-r4b-*.json'))
    audit = repository / 'BIAVORA_PRODUCTION_READINESS_AUDIT'
    files += sorted(audit.glob('6[01]_FOUNDATION_D_*.md'))
    for path in files:
        content = path.read_bytes()
        matches += [{'surface': path.name, 'key': key} for key, value in values.items()
                    if value in content]
    command = ['docker', 'compose', '--project-name', 'biavora_d5_r4b',
               '--env-file', str(env_file), '-f',
               str(repository / 'docker-compose.cdc-local.yml'),
               'logs', '--no-color', '--tail', '1000',
               'query', 'controller', 'normalizer', 'transformer',
               'loader', 'connect']
    result = subprocess.run(command, cwd=repository, capture_output=True,
                            timeout=90)
    if result.returncode != 0:
        raise RuntimeError('bounded Docker log scan unavailable')
    content = result.stdout + result.stderr
    matches += [{'surface': 'bounded_container_logs', 'key': key}
                for key, value in values.items() if value in content]
    summary = {'status': 'PASS' if not matches else 'FAIL',
               'known_secret_values': len(values),
               'evidence_files_scanned': len(files),
               'container_log_tail_per_service': 1000,
               'matches': matches}
    path = evidence / f'd5-r4b-secret-scan-{args.run_id}.json'
    path.write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps({'path': str(path), **summary}), flush=True)
    if matches:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
