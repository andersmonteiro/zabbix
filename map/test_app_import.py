"""Guards the one class of bug that every other test in this suite is blind to:
the tests all exercise `models` / `routes_*` directly against
`sqlite:///:memory:`, so nothing ever imports `app.py` itself — which means a
missing runtime dependency (e.g. the Postgres DBAPI driver that `app.py`'s
default DATABASE_URL requires) can ship green and crash-loop the container on a
real client install."""
import os
import re
import subprocess
import sys

MAP_DIR = os.path.dirname(os.path.abspath(__file__))


def test_app_module_imports_cleanly(tmp_path):
    env = dict(os.environ)
    env['DATABASE_URL'] = 'sqlite:///:memory:'
    env['EQUIPMENT_IMAGES_DIR'] = str(tmp_path / 'equipment-images')
    # Keep the background poller from doing anything meaningful during import.
    env['POLL_INTERVAL_SECONDS'] = '3600'

    result = subprocess.run(
        [sys.executable, '-c', 'import app'],
        cwd=MAP_DIR, env=env, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, (
        f"`import app` failed (exit {result.returncode}):\n{result.stderr}"
    )


def test_requirements_declare_a_postgres_driver():
    """app.py builds 'postgresql+psycopg2://...' as its default DATABASE_URL and
    SQLAlchemy's create_engine() imports the DBAPI driver eagerly, so the driver
    must be an installed runtime dependency, not just a dev convenience."""
    with open(os.path.join(MAP_DIR, 'requirements.txt'), encoding='utf-8') as fh:
        requirements = fh.read()

    packages = {
        re.split(r'[=<>!~\[]', line.strip(), maxsplit=1)[0].lower()
        for line in requirements.splitlines()
        if line.strip() and not line.strip().startswith('#')
    }
    assert packages & {'psycopg2', 'psycopg2-binary'}, (
        f'no psycopg2 driver in requirements.txt: {sorted(packages)}'
    )
