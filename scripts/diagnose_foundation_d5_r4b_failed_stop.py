"""Targeted isolated controller transition probe; no credential output."""

import argparse
import json

from bi_platform_shared.cdc_contract import Scope
from shared.cdc.connect import ConnectClient
from shared.cdc.worker import ControlPlane, FencedConnect, control_pipeline


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--pipeline-id', required=True)
    args = parser.parse_args()
    control = ControlPlane('controller')
    control.recover_cutovers = False
    connector = ConnectClient()
    result = []
    for attempt in range(3):
        item = next(item for item in control.pipelines()
                    if item['scope']['pipeline_id'] == args.pipeline_id)
        scope = Scope(**item['scope'])
        control.claim(scope)
        status = connector.request(scope, '/status')
        state = status.get('connector', {}).get('state') if status else None
        control_pipeline(item, control, FencedConnect(connector, control, scope), None)
        result.append({'attempt': attempt + 1, 'input_observed': item['observed_state'],
                       'connect_state': state})
        if item['observed_state'] == 'STOPPED':
            break
    print(json.dumps(result), flush=True)
