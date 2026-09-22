import pytest
from flask import Flask, jsonify
from werkzeug.security import generate_password_hash

from auth import auth_bp, init_auth, register_auth_guard
from models import Base, User, get_engine, get_session_factory


@pytest.fixture
def client():
    engine = get_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    session_factory = get_session_factory(engine)

    session = session_factory()
    session.add(User(username='admin', password_hash=generate_password_hash('secret123')))
    session.commit()
    session.close()

    app = Flask(__name__, static_folder='static', static_url_path='')
    app.secret_key = 'test-secret'
    app.config['TESTING'] = True
    init_auth(session_factory)
    app.register_blueprint(auth_bp)
    register_auth_guard(app)

    @app.route('/protected')
    def protected():
        return 'ok'

    @app.route('/api/protected')
    def api_protected():
        return jsonify({'ok': True})

    with app.test_client() as c:
        yield c


def test_protected_page_redirects_to_login_when_unauthenticated(client):
    resp = client.get('/protected')
    assert resp.status_code == 302
    assert resp.headers['Location'] == '/login'


def test_protected_api_returns_401_json_when_unauthenticated(client):
    resp = client.get('/api/protected')
    assert resp.status_code == 401
    assert 'error' in resp.get_json()


def test_login_with_correct_credentials_grants_access(client):
    resp = client.post('/api/login', json={'username': 'admin', 'password': 'secret123'})
    assert resp.status_code == 200
    assert resp.get_json()['ok'] is True

    resp = client.get('/protected')
    assert resp.status_code == 200
    assert resp.get_data(as_text=True) == 'ok'


def test_login_with_wrong_password_is_rejected(client):
    resp = client.post('/api/login', json={'username': 'admin', 'password': 'wrong'})
    assert resp.status_code == 401
    assert client.get('/protected').status_code == 302


def test_login_with_unknown_username_is_rejected(client):
    resp = client.post('/api/login', json={'username': 'ghost', 'password': 'secret123'})
    assert resp.status_code == 401


def test_logout_clears_session(client):
    client.post('/api/login', json={'username': 'admin', 'password': 'secret123'})
    assert client.get('/protected').status_code == 200

    resp = client.post('/api/logout')
    assert resp.status_code == 200
    assert client.get('/protected').status_code == 302
