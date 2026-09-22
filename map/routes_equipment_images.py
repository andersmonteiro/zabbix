import os
import re

from flask import Blueprint, request, send_file, Response

equipment_images_bp = Blueprint('equipment_images', __name__, url_prefix='/api/equipment-images')

_upload_dir = None
ALLOWED_EXTENSIONS = {'.png', '.jpg', '.jpeg', '.svg', '.webp'}

GENERIC_FALLBACK_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="64" height="64" '
    'fill="none" stroke="#aaaaaa" stroke-width="1.5">'
    '<rect x="3" y="8" width="18" height="8" rx="1.5"/>'
    '<circle cx="7" cy="12" r="1"/><circle cx="10.5" cy="12" r="1"/>'
    '<path d="M14 12h6"/></svg>'
)


def init_equipment_images_routes(upload_dir):
    global _upload_dir
    _upload_dir = upload_dir
    os.makedirs(_upload_dir, exist_ok=True)


def _sanitize_model_name(model):
    # Strip anything that isn't alphanumeric/space/dash/underscore/dot, then
    # collapse to a safe filename stem — blocks path traversal regardless of
    # how the model string arrives (URL-decoded slashes, "..", etc.).
    cleaned = re.sub(r'[^A-Za-z0-9 _.\-]', '', model).strip()
    cleaned = cleaned.replace('..', '').strip('. ')
    return cleaned or 'unknown'


def _find_existing_image(model_stem):
    for ext in ALLOWED_EXTENSIONS:
        candidate = os.path.join(_upload_dir, model_stem + ext)
        if os.path.isfile(candidate):
            return candidate
    return None


@equipment_images_bp.route('/<path:model>', methods=['GET'])
def get_equipment_image(model):
    stem = _sanitize_model_name(model)
    existing = _find_existing_image(stem)
    if existing is None:
        return Response(GENERIC_FALLBACK_SVG, mimetype='image/svg+xml')
    return send_file(existing)


@equipment_images_bp.route('/<path:model>', methods=['POST'])
def upload_equipment_image(model):
    stem = _sanitize_model_name(model)
    if 'file' not in request.files:
        return {'error': 'Campo "file" ausente'}, 400
    file = request.files['file']
    ext = os.path.splitext(file.filename or '')[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return {'error': f'Extensão não permitida: {ext}'}, 400

    for existing_ext in ALLOWED_EXTENSIONS:
        stale = os.path.join(_upload_dir, stem + existing_ext)
        if os.path.isfile(stale):
            os.remove(stale)

    file.save(os.path.join(_upload_dir, stem + ext))
    return '', 204
