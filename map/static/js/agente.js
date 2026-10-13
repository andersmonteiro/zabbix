// Tela do Agente de IA -- chat de verdade com o agente central
// (agent.natverk.com.br), via proxy em /api/agent/chat (routes_agent_chat.py).
// O token do cliente nunca aparece aqui: fica só no servidor do map/.

function agenteEsc(str) {
  if (str === null || str === undefined) return '';
  return String(str).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

// Conversor leve de markdown -- o agente foi instruído (ver SYSTEM_PROMPT
// em chat.py) a mostrar saída crua de equipamento em blocos ``` e usar
// **negrito** pros títulos curtos antes de cada bloco; sem isso os
// asteriscos/crases apareciam literalmente na tela em vez de formatados.
// Cobre só esse subconjunto (fences + negrito + código inline), não é um
// parser de markdown completo -- escapa tudo primeiro, então nunca
// injeta HTML vindo do texto do modelo.
function renderLiteMarkdown(raw) {
  const parts = raw.split(/(```[\s\S]*?```)/g);
  return parts.map((part) => {
    if (part.startsWith('```')) {
      const inner = part.replace(/^```[^\n]*\n?/, '').replace(/```$/, '');
      return `<pre class="agente-code">${agenteEsc(inner)}</pre>`;
    }
    return agenteEsc(part)
      .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
      .replace(/`([^`]+)`/g, '<code>$1</code>');
  }).join('');
}

const messagesEl = document.getElementById('agente-messages');
const formEl = document.getElementById('agente-form');
const inputEl = document.getElementById('agente-input');
const sendBtn = formEl.querySelector('.agente-send-btn');

// Uma conversa por carregamento da página -- recarregar a aba começa um
// papo novo de propósito (o histórico multi-turno fica guardado no agente
// central por conversation_id, não precisa persistir nada aqui).
let conversationId = null;
let sending = false;

function addMessage(role, text, extraClass) {
  const welcome = messagesEl.querySelector('.agente-welcome');
  if (welcome) welcome.remove();
  const el = document.createElement('div');
  el.className = `agente-msg ${role}${extraClass ? ` ${extraClass}` : ''}`;
  el.textContent = text;
  messagesEl.appendChild(el);
  messagesEl.scrollTop = messagesEl.scrollHeight;
  return el;
}

// Bolha do assistente criada já com os "..." de digitando -- uma consulta
// real (Zabbix/SSH) pode levar alguns segundos, e sem isso a tela ficava
// parada sem nenhum sinal de que a pergunta estava sendo processada. O
// primeiro `assistantEl.innerHTML = renderLiteMarkdown(rawText)` em
// streamToAgent sobrescreve esses spans sozinho, sem precisar de código
// extra pra limpar.
function addTypingMessage() {
  const el = addMessage('assistant', '');
  el.innerHTML = '<span class="agente-typing"><span></span><span></span><span></span></span>';
  return el;
}

document.querySelectorAll('.agente-suggestion-chip').forEach((btn) => {
  btn.addEventListener('click', () => {
    inputEl.value = btn.textContent;
    inputEl.focus();
  });
});

// SSE vem em "registros" separados por linha em branco -- a maioria é só
// "data: <pedaço de texto>", mas o último registro do turno é
// "event: done\ndata: {"conversation_id": "..."}" (ver chat.py). Sem
// distinguir os dois, o JSON final do "done" acabaria grudado no fim da
// resposta visível, como se fosse texto do assistente.
async function streamToAgent(message, assistantEl) {
  const resp = await fetch('/api/agent/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ message, conversation_id: conversationId }),
  });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      if (body && body.error) detail = body.error;
    } catch (err) { /* corpo não era JSON */ }
    throw new Error(detail);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let rawText = '';

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    let sepIndex;
    while ((sepIndex = buffer.indexOf('\n\n')) !== -1) {
      const record = buffer.slice(0, sepIndex);
      buffer = buffer.slice(sepIndex + 2);

      const lines = record.split('\n');
      const isDone = lines.some((l) => l.startsWith('event: done'));
      const dataLine = lines.find((l) => l.startsWith('data: '));
      if (!dataLine) continue;
      const data = dataLine.slice('data: '.length);

      if (isDone) {
        try {
          const parsed = JSON.parse(data);
          if (parsed.conversation_id) conversationId = parsed.conversation_id;
        } catch (err) { /* ignora, mantém o conversation_id atual */ }
      } else {
        rawText += data;
        assistantEl.innerHTML = renderLiteMarkdown(rawText);
        messagesEl.scrollTop = messagesEl.scrollHeight;
      }
    }
  }

  if (!rawText) {
    assistantEl.textContent = '(sem resposta)';
  }
}

formEl.addEventListener('submit', async (e) => {
  e.preventDefault();
  if (sending) return;
  const text = inputEl.value.trim();
  if (!text) return;

  addMessage('user', text);
  inputEl.value = '';
  sending = true;
  sendBtn.disabled = true;
  inputEl.disabled = true;

  const assistantEl = addTypingMessage();
  try {
    await streamToAgent(text, assistantEl);
  } catch (err) {
    assistantEl.textContent = `Não consegui falar com o agente: ${err.message}`;
    assistantEl.classList.add('notice');
  } finally {
    sending = false;
    sendBtn.disabled = false;
    inputEl.disabled = false;
    inputEl.focus();
  }
});
