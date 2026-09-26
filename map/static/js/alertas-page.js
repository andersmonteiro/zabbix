// Página cheia de alertas (/alertas.html) -- reusa os helpers de alerts.js
// (alertsEsc/alertsFormatAge/alertsSeverityClass/alertsFormatClock/
// alertsFormatDuration), carregado antes deste arquivo. Suporta ?hostid=<id>
// na URL pra abrir já filtrado por host -- usado pelos links "Ver alertas"
// da lista de hosts e do popup do mapa.
const ALERTAS_PAGE_REFRESH_INTERVAL_MS = 30000;

// 'open' ou 'resolved' -- /api/alerts traz os dois juntos (problemas abertos
// e resolvidos nas últimas 24h, igual ao "Show recent problems" do próprio
// Zabbix); a aba decide qual metade mostrar.
let alertasActiveTab = 'open';

function alertasPageFilterHostid() {
  return new URLSearchParams(window.location.search).get('hostid');
}

function alertRowHtml(p, now) {
  const timeInfo = p.resolved
    ? `Resolvido <b>${alertsEsc(alertsFormatClock(p.resolved_clock))}</b> · durou ${alertsEsc(alertsFormatDuration(p.resolved_clock - p.clock))}`
    : `Início <b>${alertsEsc(alertsFormatClock(p.clock))}</b> · ${alertsEsc(alertsFormatAge(now - p.clock))}`;
  return `
    <div class="alert-row">
      <div class="alert-dot ${p.resolved ? 'sev-resolved' : alertsSeverityClass(p.severity)}"></div>
      <div class="alert-body">
        <div class="alert-name">${alertsEsc(p.name)}</div>
        <div class="alert-meta">${alertsEsc(p.host)} · ${alertsEsc(p.severity_label)}${p.acknowledged ? ' · <span class="alert-ack">reconhecido</span>' : ''}</div>
        <div class="alert-time">${timeInfo}</div>
      </div>
    </div>
  `;
}

async function refreshAlertasPage() {
  const list = document.getElementById('alertas-list');
  if (!list) return;

  let state;
  try {
    const resp = await fetch('/api/alerts');
    state = await resp.json();
  } catch (err) {
    console.error('Falha ao buscar /api/alerts', err);
    return;
  }

  if (state.stale) {
    list.innerHTML = '<div class="alerts-empty">Sem dados recentes do Zabbix.</div>';
    return;
  }

  let problems = state.problems || [];
  const filterHostid = alertasPageFilterHostid();
  const chip = document.getElementById('alerts-filter-chip');
  if (filterHostid) {
    problems = problems.filter((p) => String(p.hostid) === filterHostid);
    if (chip) {
      chip.hidden = false;
      const hostLabel = problems[0] ? problems[0].host : filterHostid;
      document.getElementById('alerts-filter-host').textContent = hostLabel;
    }
  } else if (chip) {
    chip.hidden = true;
  }

  const openProblems = problems.filter((p) => !p.resolved);
  const resolvedProblems = problems.filter((p) => p.resolved);
  document.getElementById('tab-count-open').textContent = openProblems.length;
  document.getElementById('tab-count-resolved').textContent = resolvedProblems.length;

  const shown = alertasActiveTab === 'open' ? openProblems : resolvedProblems;
  document.getElementById('alertas-panel-title').textContent =
    alertasActiveTab === 'open' ? 'Alertas abertos' : 'Alertas resolvidos (últimas 24h)';

  const now = Math.floor(Date.now() / 1000);
  if (shown.length === 0) {
    const noun = alertasActiveTab === 'open' ? 'alerta ativo' : 'alerta resolvido nas últimas 24h';
    list.innerHTML = filterHostid
      ? `<div class="alerts-empty">Nenhum ${noun} para este host.</div>`
      : `<div class="alerts-empty">Nenhum ${noun}.</div>`;
    return;
  }

  list.innerHTML = shown.map((p) => alertRowHtml(p, now)).join('');
}

document.querySelectorAll('.alerts-tab').forEach((btn) => {
  btn.addEventListener('click', () => {
    if (btn.dataset.tab === alertasActiveTab) return;
    alertasActiveTab = btn.dataset.tab;
    document.querySelectorAll('.alerts-tab').forEach((b) => b.classList.toggle('active', b === btn));
    refreshAlertasPage();
  });
});

refreshAlertasPage();
setInterval(refreshAlertasPage, ALERTAS_PAGE_REFRESH_INTERVAL_MS);
