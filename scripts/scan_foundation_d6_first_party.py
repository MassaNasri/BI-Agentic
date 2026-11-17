"""Scan the current first-party tree with the release gate's pinned gitleaks image."""
import argparse
import json
from pathlib import Path
import re
import shutil
import subprocess
import tarfile


ROOT = Path(__file__).resolve().parents[1]
IMAGE = ('ghcr.io/gitleaks/gitleaks@sha256:'
         'b5918eb91b8d2473cec722f066abb4352e4ffdc4ec9f4283ec143aba9ec9ebc4')


def main(output_root):
    destination = Path(output_root).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    scan_root = destination / 'first-party-tree'
    scan_root.mkdir()
    listed = subprocess.run(
        ['git', 'ls-files', '-co', '--exclude-standard', '-z'],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode('utf-8').split('\0')
    files = 0
    for name in listed:
        if not name:
            continue
        relative = Path(name.replace('\\', '/'))
        if (relative.parts[:4] == ('services', 'ai-service', 'forecasting', 'timesfm')
                or relative.name.startswith('.env')
                or relative.suffix.lower() in ('.sqlite', '.sqlite3', '.db', '.pyc')):
            continue
        source = ROOT / relative
        if not source.is_file():
            continue
        target = scan_root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        files += 1
    # Windows Docker Desktop can take more than five minutes to traverse the
    # copied tree through `docker cp`. Stream one archive through stdin instead.
    archive = destination / 'first-party-tree.tar'
    with tarfile.open(archive, 'w') as bundle:
        bundle.add(scan_root, arcname='repo')
    report = destination / 'gitleaks-redacted.json'
    container = 'biavora_d6_scan_' + re.sub(r'[^a-z0-9_-]', '_', destination.name.lower())
    command = ['docker', 'create', '--name', container,
               '-v', f'{archive}:/tree.tar:ro', '--entrypoint', '/bin/sh', IMAGE,
               '-c', 'tar -xf /tree.tar -C / && gitleaks dir --redact '
               '--no-banner --log-level error --report-format json '
               '--report-path /gitleaks-redacted.json /repo']
    subprocess.run(command, cwd=ROOT, capture_output=True, check=True, timeout=60)
    try:
        scanned = subprocess.run(['docker', 'start', '--attach', container],
                                 cwd=ROOT, capture_output=True, text=True, timeout=300)
        subprocess.run(['docker', 'cp', f'{container}:/gitleaks-redacted.json', str(report)],
                       cwd=ROOT, capture_output=True, check=True, timeout=60)
    finally:
        subprocess.run(['docker', 'rm', container], cwd=ROOT, capture_output=True,
                       timeout=60)
    findings = json.loads(report.read_text(encoding='utf-8')) if report.exists() else []
    summary = {'status': 'PASS' if scanned.returncode == 0 else 'FAIL',
               'files_scanned': files, 'timesfm_excluded': True,
               'gitleaks_exit_code': scanned.returncode, 'findings': len(findings)}
    (destination / 'summary.json').write_text(json.dumps(summary, indent=2),
                                               encoding='utf-8')
    print(json.dumps(summary), flush=True)
    if scanned.returncode:
        raise SystemExit(1)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output-root', required=True)
    main(parser.parse_args().output_root)
