import io
import os

import pytest
from flask import Flask

import routes_equipment_images
from routes_equipment_images import (
    equipment_images_bp, init_equipment_images_routes, _sanitize_model_name,
)


@pytest.fixture
def client(tmp_path):
    app = Flask(__name__)
    init_equipment_images_routes(str(tmp_path))
    app.register_blueprint(equipment_images_bp)
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c


def test_get_missing_model_returns_generic_fallback(client):
    resp = client.get('/api/equipment-images/Huawei%20MA5800-X2')
    assert resp.status_code == 200
    assert resp.content_type.startswith('image/svg')


def test_upload_and_retrieve_image(client):
    fake_png = io.BytesIO(b'\x89PNG\r\n\x1a\nfakepngbytes')
    resp = client.post(
        '/api/equipment-images/Huawei%20MA5800-X2',
        data={'file': (fake_png, 'olt.png')},
        content_type='multipart/form-data',
    )
    assert resp.status_code == 204

    resp = client.get('/api/equipment-images/Huawei%20MA5800-X2')
    assert resp.status_code == 200
    assert resp.content_type == 'image/png'
    assert resp.data == b'\x89PNG\r\n\x1a\nfakepngbytes'


def test_upload_rejects_disallowed_extension(client):
    fake_exe = io.BytesIO(b'MZfakeexe')
    resp = client.post(
        '/api/equipment-images/Something',
        data={'file': (fake_exe, 'virus.exe')},
        content_type='multipart/form-data',
    )
    assert resp.status_code == 400


def test_model_name_is_sanitized_for_filesystem(client):
    fake_png = io.BytesIO(b'fakepng')
    resp = client.post(
        '/api/equipment-images/../../etc/passwd',
        data={'file': (fake_png, 'x.png')},
        content_type='multipart/form-data',
    )
    # Flask's <model> route segment already can't contain a literal '/',
    # so this exercises the sanitizer against the decoded value instead.
    # NOTE: lenient on purpose (both outcomes are safe) — the real regression
    # protection for the sanitizer lives in the direct unit tests below.
    assert resp.status_code in (204, 400)


# --- Finding 8: real coverage for the one security-sensitive function --------

HOSTILE_MODEL_NAMES = [
    '../../etc/passwd',
    '....//....//etc',
    '..\\..\\windows\\system32\\config\\sam',
    '..%2f..%2fetc%2fpasswd',
    '/etc/passwd',
    '\\\\server\\share\\file',
    'C:\\Windows\\win.ini',
    '..',
    '...',
    '....',
    '.',
    '. . .',
    '   ',
    '',
    'a/../../b',
    'model\x00.png',
    'model\n../../etc',
    '~/.ssh/id_rsa',
    '..;/..;/etc',
]


@pytest.mark.parametrize('hostile', HOSTILE_MODEL_NAMES)
def test_sanitize_model_name_never_yields_a_path(hostile):
    stem = _sanitize_model_name(hostile)

    assert stem, 'sanitizer must always return a non-empty stem'
    assert '/' not in stem
    assert '\\' not in stem
    assert '..' not in stem
    # No component of the result may be a relative-path segment.
    assert stem not in ('.', '..')
    assert not stem.startswith('.')
    assert '\x00' not in stem
    assert '\n' not in stem and '\r' not in stem


@pytest.mark.parametrize('hostile', HOSTILE_MODEL_NAMES)
def test_sanitized_name_cannot_escape_the_upload_dir(tmp_path, hostile):
    routes_equipment_images._upload_dir = str(tmp_path)
    stem = _sanitize_model_name(hostile)

    base = os.path.realpath(str(tmp_path))
    resolved = os.path.realpath(os.path.join(base, stem + '.png'))
    assert resolved.startswith(base + os.sep), (
        f'{hostile!r} -> {stem!r} escaped {base!r} (resolved to {resolved!r})'
    )


def test_sanitize_model_name_preserves_ordinary_model_names():
    assert _sanitize_model_name('Huawei MA5800-X2') == 'Huawei MA5800-X2'
    assert _sanitize_model_name('Mikrotik_CCR2004') == 'Mikrotik_CCR2004'


def test_default_brand_logos_are_seeded_on_init(client):
    # equipment_model on real hosts today is just the manufacturer name
    # ("huawei"/"datacom") -- the bundled logos are seeded under those exact
    # stems, so the plain per-model lookup finds them with no extra code.
    resp = client.get('/api/equipment-images/huawei')
    assert resp.status_code == 200
    assert resp.content_type.startswith('image/svg')

    resp = client.get('/api/equipment-images/datacom')
    assert resp.status_code == 200
    assert resp.content_type == 'image/png'


def test_seeding_never_overwrites_an_existing_upload(tmp_path):
    # A file already sitting in the upload dir before init runs (e.g. an
    # admin's own upload from a previous boot) must survive re-seeding.
    (tmp_path / 'huawei.png').write_bytes(b'\x89PNG\r\n\x1a\ncustom-admin-upload')
    app = Flask(__name__)
    init_equipment_images_routes(str(tmp_path))
    app.register_blueprint(equipment_images_bp)
    app.config['TESTING'] = True
    with app.test_client() as c:
        resp = c.get('/api/equipment-images/huawei')
    assert resp.data == b'\x89PNG\r\n\x1a\ncustom-admin-upload'
    # The bundled .svg must not have been added alongside the custom .png --
    # _find_existing_image would then pick whichever extension comes first.
    assert not (tmp_path / 'huawei.svg').exists()
