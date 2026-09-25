// Tela do Agente de IA -- por enquanto só a interface (placeholder), sem
// nenhuma IA de verdade por trás. Segue o design em
// docs/superpowers/specs/2026-09-25-assistente-ia-agente-design.md, que
// ainda não virou plano de implementação -- ver essa spec antes de plugar
// um backend real aqui.

function agenteEsc(str) {
  if (str === null || str === undefined) return '';
  return String(str).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

const messagesEl = document.getElementById('agente-messages');
const formEl = document.getElementById('agente-form');
const inputEl = document.getElementById('agente-input');

function addMessage(role, text, extraClass) {
  const welcome = messagesEl.querySelector('.agente-welcome');
  if (welcome) welcome.remove();
  const el = document.createElement('div');
  el.className = `agente-msg ${role}${extraClass ? ` ${extraClass}` : ''}`;
  el.innerHTML = agenteEsc(text);
  messagesEl.appendChild(el);
  messagesEl.scrollTop = messagesEl.scrollHeight;
}

document.querySelectorAll('.agente-suggestion-chip').forEach((btn) => {
  btn.addEventListener('click', () => {
    inputEl.value = btn.textContent;
    inputEl.focus();
  });
});

formEl.addEventListener('submit', (e) => {
  e.preventDefault();
  const text = inputEl.value.trim();
  if (!text) return;
  addMessage('user', text);
  inputEl.value = '';
  // Sem backend ainda -- só confirma que a tela funciona. Trocar por uma
  // chamada real (streaming) quando o serviço central existir.
  setTimeout(() => {
    addMessage(
      'assistant',
      'Esse agente ainda está em desenvolvimento — em breve vai poder consultar seus equipamentos diretamente por aqui.',
      'notice',
    );
  }, 350);
});
