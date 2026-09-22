from flask import Blueprint, jsonify, request, session
from werkzeug.security import generate_password_hash

from models import User

users_bp = Blueprint('users', __name__, url_prefix='/api/users')

_session_factory = None


def init_users_routes(session_factory):
    global _session_factory
    _session_factory = session_factory


def _serialize(user):
    return {'id': user.id, 'username': user.username, 'created_at': user.created_at.isoformat()}


@users_bp.route('', methods=['GET'])
def list_users():
    db = _session_factory()
    try:
        users = db.query(User).order_by(User.username).all()
        return jsonify([_serialize(u) for u in users])
    finally:
        db.close()


@users_bp.route('', methods=['POST'])
def create_user():
    data = request.get_json(force=True, silent=True) or {}
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username or len(password) < 6:
        return jsonify({'error': 'Usuário obrigatório e senha com no mínimo 6 caracteres'}), 400

    db = _session_factory()
    try:
        if db.query(User).filter(User.username == username).first():
            return jsonify({'error': 'Já existe um usuário com esse nome'}), 409
        user = User(username=username, password_hash=generate_password_hash(password))
        db.add(user)
        db.commit()
        return jsonify(_serialize(user)), 201
    finally:
        db.close()


@users_bp.route('/<int:user_id>', methods=['DELETE'])
def delete_user(user_id):
    db = _session_factory()
    try:
        user = db.get(User, user_id)
        if user is None:
            return jsonify({'error': 'Usuário não encontrado'}), 404
        # A logged-in operator can't delete their own account from under
        # themselves — that would leave the session authenticated for a
        # user row that no longer exists.
        if user.id == session.get('user_id'):
            return jsonify({'error': 'Não é possível remover o próprio usuário logado'}), 400
        if db.query(User).count() <= 1:
            return jsonify({'error': 'Não é possível remover o último usuário'}), 400
        db.delete(user)
        db.commit()
        return '', 204
    finally:
        db.close()


@users_bp.route('/<int:user_id>/password', methods=['PUT'])
def change_password(user_id):
    data = request.get_json(force=True, silent=True) or {}
    password = data.get('password') or ''
    if len(password) < 6:
        return jsonify({'error': 'Senha com no mínimo 6 caracteres'}), 400

    db = _session_factory()
    try:
        user = db.get(User, user_id)
        if user is None:
            return jsonify({'error': 'Usuário não encontrado'}), 404
        user.password_hash = generate_password_hash(password)
        db.commit()
        return jsonify({'ok': True})
    finally:
        db.close()
