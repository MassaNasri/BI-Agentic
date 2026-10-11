"""Repository-wide pytest collection policy for the canonical offline gate."""

from pathlib import Path


_REPOSITORY_ROOT = Path(__file__).resolve().parent
_NON_TEST_DIAGNOSTICS = {
    (_REPOSITORY_ROOT / "etl-final" / "shared" / "models" / "test_import.py").resolve(),
    (_REPOSITORY_ROOT / "etl-final" / "shared" / "models" / "test_import2.py").resolve(),
    (_REPOSITORY_ROOT / "etl-final" / "shared" / "models" / "test_file.txt").resolve(),
    # This Django TestCase is executed through manage.py so the test DB is created.
    (_REPOSITORY_ROOT / "etl-final" / "extractor-service" / "extractor" / "engine" / "test_run_extractor_view.py").resolve(),
}


def pytest_ignore_collect(collection_path, config):  # noqa: ARG001
    """Keep print-only diagnostics and an encoded fixture out of test collection."""

    return Path(str(collection_path)).resolve() in _NON_TEST_DIAGNOSTICS

