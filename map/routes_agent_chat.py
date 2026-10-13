"""Proxy do chat da plataforma (agente.html) pro agente central
(agent.natverk.com.br/chat) -- o token do cliente (AI_AGENT_TOKEN) fica só
aqui no servidor, nunca no navegador: se fosse colado direto no JS,
qualquer um com o devtools aberto poderia chamar o agente central sem
passar pelo login desta tela e gastar o orçamento mensal do cliente.
Protegido pelo guard global de sessão em auth.py, igual qualquer outra
rota /api/*."""
import os

import requests
from flask import Blueprint, Response, jsonify, request, stream_with_context

agent_chat_bp = Blueprint('agent_chat', __name__, url_prefix='/api/agent')

AI_AGENT_URL = os.environ.get('AI_AGENT_URL', 'https://agent.natverk.com.br/chat')
AI_AGENT_TOKEN = os.environ.get('AI_AGENT_TOKEN', '')
AI_CHAT_TIMEOUT_SECONDS = int(os.environ.get('AI_CHAT_TIMEOUT_SECONDS', '90'))


@agent_chat_bp.route('/chat', methods=['POST'])
def chat():
    if not AI_AGENT_TOKEN:
        return jsonify({'error': 'AI_AGENT_TOKEN não configurado nesta VM'}), 503

    data = request.get_json(force=True, silent=True) or {}
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'error': 'message é obrigatório'}), 400

    payload = {'message': message}
    if data.get('conversation_id'):
        payload['conversation_id'] = data['conversation_id']

    try:
        upstream = requests.post(
            AI_AGENT_URL,
            json=payload,
            headers={'x-agent-token': AI_AGENT_TOKEN},
            stream=True,
            timeout=AI_CHAT_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        return jsonify({'error': f'Falha ao falar com o agente central: {e}'}), 502

    if upstream.status_code >= 400:
        detail = upstream.text[:300]
        upstream.close()
        return jsonify({'error': f'Agente central respondeu HTTP {upstream.status_code}: {detail}'}), 502

    # Repassa o SSE bruto (linhas "data: ..."/"event: done") sem reinterpretar
    # -- o frontend (agente.js) faz o parse exatamente como o bot do
    # WhatsApp já faz em askAgent() (server.js).
    def relay():
        try:
            for chunk in upstream.iter_content(chunk_size=None):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return Response(stream_with_context(relay()), mimetype='text/event-stream')
