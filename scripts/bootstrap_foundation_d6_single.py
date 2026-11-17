"""Prepare one-source disposable D6 fixture without creating extra CDC scopes."""
import argparse
import time

from verify_foundation_d_cdc import Fixture, wait_for


def main(env_file):
    fixture = Fixture(env_file)
    wait_for('fresh Query health',
             lambda: fixture.session.get(fixture.base + '/health/', timeout=3).ok,
             seconds=120)
    fixture.ch.command(
        'CREATE USER IF NOT EXISTS cdc_query IDENTIFIED WITH sha256_password BY {password:String}',
        parameters={'password': fixture.env['CDC_QUERY_CH_PASSWORD']})
    fixture.ch.command('GRANT SELECT ON etl.* TO cdc_query')
    fixture.ch.command('ALTER USER cdc_query SETTINGS readonly=0')
    print('PASS single-source fixture metadata and SELECT-only Query identity', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', required=True)
    main(parser.parse_args().env_file)
