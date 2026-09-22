from flask import Blueprint, current_app, jsonify, request, session
from werkzeug.security import check_password_hash

from models import User

auth_bp = Blueprint('auth', __name__)

_session_factory = None

# Paths reachable without a session — the login page itself, the endpoint
# that creates the session, static assets the login page needs, and the
# Docker healthcheck (which has no way to authenticate).
PUBLIC_PATHS = {'/login', '/api/login', '/health'}
PUBLIC_PREFIXES = ('/css/', '/js/')


def init_auth(session_factory):
    global _session_factory
    _session_factory = session_factory


def is_public_path(path):
    return path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES)


def register_auth_guard(app):
    @app.before_request
    def _require_login():
        if is_public_path(request.path):
            return None
        if session.get('user_id'):
            return None
        if request.path.startswith('/api/'):
            return jsonify({'error': 'Não autenticado'}), 401
        return current_app.response_class(
            status=302, headers={'Location': '/login'},
        )


@auth_bp.route('/login', methods=['GET'])
def login_page():
    return current_app.send_static_file('login.html')


@auth_bp.route('/api/login', methods=['POST'])
def login_submit():
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password', '')

    db = _session_factory()
    try:
        user = db.query(User).filter(User.username == username).first()
    finally:
        db.close()

    if user is None or not check_password_hash(user.password_hash, password):
        return jsonify({'error': 'Usuário ou senha incorretos'}), 401

    session.clear()
    session['user_id'] = user.id
    session['username'] = user.username
    session.permanent = True
    return jsonify({'ok': True, 'username': user.username})


@auth_bp.route('/api/logout', methods=['POST'])
def logout():
    session.clear()
    return jsonify({'ok': True})


@auth_bp.route('/api/session', methods=['GET'])
def current_session():
    return jsonify({'username': session.get('username')})
