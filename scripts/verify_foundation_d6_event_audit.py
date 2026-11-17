"""Run the payload-free Kafka overlap audit for a retained D6 result."""
import argparse
import json
from pathlib import Path
import subprocess


def main(evidence):
    path = Path(evidence).resolve()
    state = json.loads(path.read_text(encoding='utf-8-sig'))
    origin = path.stat().st_ctime
    first = int((origin + state['first_mutation_seconds']) * 1000)
    last = int((origin + state['last_mutation_seconds']) * 1000)
    command = ['docker', 'exec', f"{state['project_name']}-loader-1", 'python',
               '/acceptance/foundation_d6_event_audit.py', '--scope',
               json.dumps(state['scope']), '--writer-from-ms', str(first),
               '--writer-to-ms', str(last)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=180)
    lines = result.stdout.strip().splitlines()
    if lines:
        summary = json.loads(lines[-1])
        output = path.with_name(path.stem + '-event-audit.json')
        output.write_text(json.dumps(summary, indent=2), encoding='utf-8')
        print(json.dumps({'evidence': str(output), **summary}), flush=True)
    if result.returncode:
        detail = result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ''
        raise AssertionError(f'Event audit exit {result.returncode}: {detail[:160]}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--evidence', required=True)
    main(parser.parse_args().evidence)
