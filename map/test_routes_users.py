import pytest
from flask import Flask
from werkzeug.security import generate_password_hash

from models import Base, User, get_engine, get_session_factory
from routes_users import users_bp, init_users_routes


@pytest.fixture
def client_and_sessions():
    engine = get_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    session_factory = get_session_factory(engine)

    app = Flask(__name__)
    app.secret_key = 'test-secret'
    init_users_routes(session_factory)
    app.register_blueprint(users_bp)
    app.config['TESTING'] = True
    with app.test_client() as c:
        yield c, session_factory


@pytest.fixture
def client(client_and_sessions):
    return client_and_sessions[0]


def _seed_user(session_factory, username='admin', password='secret123'):
    session = session_factory()
    try:
        user = User(username=username, password_hash=generate_password_hash(password))
        session.add(user)
        session.commit()
        session.refresh(user)
        return user.id
    finally:
        session.close()


def test_list_users_empty(client):
    resp = client.get('/api/users')
    assert resp.status_code == 200
    assert resp.get_json() == []


def test_create_user(client):
    resp = client.post('/api/users', json={'username': 'operador', 'password': 'senha123'})
    assert resp.status_code == 201
    body = resp.get_json()
    assert body['username'] == 'operador'
    assert 'password_hash' not in body


def test_create_user_rejects_short_password(client):
    resp = client.post('/api/users', json={'username': 'operador', 'password': '123'})
    assert resp.status_code == 400


def test_create_user_rejects_duplicate_username(client_and_sessions):
    client, session_factory = client_and_sessions
    _seed_user(session_factory, 'operador')
    resp = client.post('/api/users', json={'username': 'operador', 'password': 'outrasenha'})
    assert resp.status_code == 409


def test_delete_user(client_and_sessions):
    client, session_factory = client_and_sessions
    _seed_user(session_factory, 'admin')
    target_id = _seed_user(session_factory, 'operador')

    resp = client.delete(f'/api/users/{target_id}')
    assert resp.status_code == 204
    assert len(client.get('/api/users').get_json()) == 1


def test_delete_last_user_is_refused(client_and_sessions):
    client, session_factory = client_and_sessions
    only_id = _seed_user(session_factory, 'admin')

    resp = client.delete(f'/api/users/{only_id}')
    assert resp.status_code == 400
    assert len(client.get('/api/users').get_json()) == 1


def test_delete_currently_logged_in_user_is_refused(client_and_sessions):
    client, session_factory = client_and_sessions
    admin_id = _seed_user(session_factory, 'admin')
    _seed_user(session_factory, 'operador')

    with client.session_transaction() as sess:
        sess['user_id'] = admin_id

    resp = client.delete(f'/api/users/{admin_id}')
    assert resp.status_code == 400
    assert len(client.get('/api/users').get_json()) == 2


def test_change_password(client_and_sessions):
    client, session_factory = client_and_sessions
    user_id = _seed_user(session_factory, 'admin', 'oldpassword')

    resp = client.put(f'/api/users/{user_id}/password', json={'password': 'newpassword'})
    assert resp.status_code == 200

    session = session_factory()
    try:
        from werkzeug.security import check_password_hash
        user = session.get(User, user_id)
        assert check_password_hash(user.password_hash, 'newpassword')
    finally:
        session.close()
