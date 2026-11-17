"""Read bounded public lifecycle state for a D6 acceptance source."""
import argparse
import json
from pathlib import Path

from verify_foundation_d_cdc import Fixture


def main(env_file, evidence):
    path = Path(evidence).resolve()
    state = json.loads(path.read_text(encoding='utf-8-sig'))
    scope = state['scope']
    fixture = Fixture(env_file)
    pipeline = fixture.api(scope['workspace_id'], 'GET',
                           f"/database/sources/{scope['source_id']}/cdc/")['data'][0]
    safe = {key: pipeline.get(key) for key in
            ('desired_state', 'observed_state', 'error_code', 'generation',
             'snapshot_complete', 'reconciliation')}
    output = path.with_name(path.stem + '-state.json')
    output.write_text(json.dumps(safe, indent=2, default=str), encoding='utf-8')
    print(json.dumps({'evidence': str(output), **safe}, default=str), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--evidence', required=True)
    args = parser.parse_args()
    main(args.env_file, args.evidence)
