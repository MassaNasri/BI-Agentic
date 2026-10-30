"""Validate required release jobs, production fixture and security suite coverage."""
from pathlib import Path
import yaml

from run_security_regression import SUITES

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    'current-tree-secret-scan', 'static-and-compose', 'frontend',
    'backend-and-ai', 'etl', 'security-regression', 'migration-drift',
    'docker-build', 'foundation-c-owner-boundary',
}
EXPECTED_TESTS = {
    'query': {'tests/test_clickhouse_credential_redaction.py', 'tests/test_ingestion_callback_security.py',
              'tests/test_security_configuration.py', 'integration.test_public_boundary'},
    'visualization': {'visualization_api/tests/test_security_ownership_and_query_reference.py'},
    'voice': {'voice_reports/tests_security_workspace_authorization.py'},
    'auth': {'users.tests_security_invitation'},
    'workspace': {'workspace.tests_security_invitation'},
    'etl': {'etl-final/shared/security/test_security_controls.py'},
}


def main():
    workflow = yaml.safe_load((ROOT / '.github/workflows/p0c-release-gate.yml').read_text(encoding='utf-8'))
    jobs = workflow['jobs']
    release = jobs['release-gate']
    assert set(release['needs']) == REQUIRED
    assert release['if'] == 'always()'
    assert 'success success success success success success success success success' in release['steps'][0]['run']
    for name, job in jobs.items():
        assert 'continue-on-error' not in job, name
        for step in job['steps']:
            assert 'continue-on-error' not in step, (name, step.get('name'))
    security = jobs['security-regression']
    assert set(security['needs']) == {'backend-and-ai', 'etl'}
    assert security['strategy']['fail-fast'] is False
    assert set(security['strategy']['matrix']['suite']) == set(SUITES) == set(EXPECTED_TESTS)
    for suite, tests in EXPECTED_TESTS.items():
        tokens = {x for command in SUITES[suite]['commands'] for x in command}
        assert tests <= tokens, suite
        expected = ([f'services/{suite}-service/requirements.txt'] if suite != 'etl' else
                    ['etl-final/shared/requirements.txt', 'etl-final/connector-service/requirements.txt'])
        assert SUITES[suite]['requirements'] == expected, suite
    install = next(s for s in security['steps'] if s.get('name') == 'Install service-native security dependencies')
    execute = next(s for s in security['steps'] if s.get('name') == 'Run every security check for this service')
    assert 'run_security_regression.py ${{ matrix.suite }} --install' in install['run']
    assert execute['run'] == 'python scripts/run_security_regression.py ${{ matrix.suite }}'
    assert 'if' not in install and 'if' not in execute
    owner = jobs['foundation-c-owner-boundary']
    migration = next(s for s in owner['steps'] if s.get('name', '').startswith('Migrate, apply ownership'))
    fixture = migration['env']
    assert fixture['APP_ENV'] == 'production'
    assert fixture['DEBUG'] == 'false'
    assert fixture['ALLOWED_HOSTS'] == 'localhost,127.0.0.1'
    assert fixture['CORS_ALLOWED_ORIGINS'] == fixture['DJANGO_CORS_ALLOWED_ORIGINS'] == ''
    assert any('tests/test_owner_boundary_environment.py' in s.get('run', '') for s in owner['steps'])
    print('PASS: YAML parsed; all nine jobs mandatory; six native security environments; all original security suites retained; no continue-on-error; production fixture explicit.')


if __name__ == '__main__':
    main()
