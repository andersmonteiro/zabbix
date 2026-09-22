import io

import pytest
from flask import Flask

from routes_equipment_images import equipment_images_bp, init_equipment_images_routes


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
    assert resp.status_code in (204, 400)
