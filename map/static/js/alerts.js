// Notification bell shared across every page (loaded next to nav.js). Polls
// /api/alerts, which itself polls Zabbix's problem.get in the background --
// this file never talks to Zabbix directly.
const ALERTS_REFRESH_INTERVAL_MS = 30000;

// Duplicated from app.js/circuitos.js on purpose: this file loads on pages
// that don't load app.js, and a build step isn't worth it for six lines.
function alertsEsc(str) {
  if (str === null || str === undefined) return '';
  return String(str).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function alertsFormatAge(seconds) {
  if (seconds < 60) return 'agora';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min atrás`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h atrás`;
  return `${Math.floor(seconds / 86400)} d atrás`;
}

function alertsSeverityClass(severity) {
  if (severity >= 4) return 'sev-crit';
  if (severity >= 2) return 'sev-warn';
  return 'sev-info';
}

// Quando setado (via showAlertsPanel com um 3º argumento), o painel do sino
// mostra só os alertas daquele host em vez de todos -- usado pelos pontos de
// entrada "ver alertas" na lista de hosts e no popup do mapa, pra não
// precisar sair da página. O sino em si sempre limpa esse filtro ao abrir.
let alertsHostFilter = null;

async function refreshAlerts() {
  const bell = document.getElementById('alerts-bell');
  const badge = document.getElementById('alerts-badge');
  const list = document.getElementById('alerts-list');
  if (!bell || !badge || !list) return;

  let state;
  try {
    const resp = await fetch('/api/alerts');
    state = await resp.json();
  } catch (err) {
    console.error('Falha ao buscar /api/alerts', err);
    return;
  }

  const allProblems = state.problems || [];
  const now = Math.floor(Date.now() / 1000);

  // O badge do sino sempre reflete TODOS os alertas, independente de um
  // filtro por host estar ativo na lista abaixo dele.
  if (allProblems.length === 0) {
    badge.hidden = true;
  } else {
    badge.hidden = false;
    badge.textContent = allProblems.length > 99 ? '99+' : String(allProblems.length);
    const worst = Math.max(...allProblems.map((p) => p.severity));
    badge.className = `alerts-badge ${alertsSeverityClass(worst)}`;
  }

  if (state.stale) {
    list.innerHTML = '<div class="alerts-empty">Sem dados recentes do Zabbix.</div>';
    return;
  }

  const filterBar = alertsHostFilter
    ? `<div class="alerts-filter-bar">Filtrando: <b>${alertsEsc(alertsHostFilter.hostName)}</b><button type="button" id="alerts-clear-filter">Ver todos</button></div>`
    : '';
  const problems = alertsHostFilter
    ? allProblems.filter((p) => String(p.hostid) === alertsHostFilter.hostid)
    : allProblems;

  if (problems.length === 0) {
    list.innerHTML = filterBar + (alertsHostFilter
      ? '<div class="alerts-empty">Nenhum alerta ativo para este host.</div>'
      : '<div class="alerts-empty">Nenhum alerta ativo.</div>');
  } else {
    list.innerHTML = filterBar + problems.map((p) => `
      <div class="alert-row">
        <div class="alert-dot ${alertsSeverityClass(p.severity)}"></div>
        <div class="alert-body">
          <div class="alert-name">${alertsEsc(p.name)}</div>
          <div class="alert-meta">${alertsEsc(p.host)} · ${alertsEsc(p.severity_label)} · ${alertsFormatAge(now - p.clock)}${p.acknowledged ? ' · reconhecido' : ''}</div>
        </div>
      </div>
    `).join('');
  }

  const clearBtn = document.getElementById('alerts-clear-filter');
  if (clearBtn) {
    clearBtn.addEventListener('click', () => {
      alertsHostFilter = null;
      refreshAlerts();
    });
  }
}

// Abre o painel do sino ancorado em `anchorEl` (bell, badge de host, ou o
// botão do popup do mapa) -- é como app.js mostra alertas sem sair da
// página. `hostFilter` é `{ hostid, hostName }` ou null pra ver todos.
function showAlertsPanel(anchorEl, hostFilter) {
  const panel = document.getElementById('alerts-panel');
  if (!panel || !anchorEl) return;
  alertsHostFilter = hostFilter || null;
  panel.hidden = false;
  const rect = anchorEl.getBoundingClientRect();
  panel.style.top = `${rect.bottom + 8}px`;
  panel.style.right = `${Math.max(8, window.innerWidth - rect.right)}px`;
  refreshAlerts();
}

(function initAlerts() {
  const bell = document.getElementById('alerts-bell');
  const panel = document.getElementById('alerts-panel');
  if (!bell || !panel) return;

  bell.addEventListener('click', (e) => {
    e.stopPropagation();
    if (!panel.hidden && !alertsHostFilter) {
      panel.hidden = true;
      return;
    }
    showAlertsPanel(bell, null);
  });
  document.addEventListener('click', (e) => {
    if (!panel.hidden && !panel.contains(e.target) && e.target !== bell) {
      panel.hidden = true;
    }
  });

  refreshAlerts();
  setInterval(refreshAlerts, ALERTS_REFRESH_INTERVAL_MS);
})();
