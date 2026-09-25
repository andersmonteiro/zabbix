// Página cheia de alertas (/alertas.html) -- reusa os helpers de alerts.js
// (alertsEsc/alertsFormatAge/alertsSeverityClass), carregado antes deste
// arquivo. Suporta ?hostid=<id> na URL pra abrir já filtrado por host --
// usado pelos links "Ver alertas" da lista de hosts e do popup do mapa.
const ALERTAS_PAGE_REFRESH_INTERVAL_MS = 30000;

function alertasPageFilterHostid() {
  return new URLSearchParams(window.location.search).get('hostid');
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

  const now = Math.floor(Date.now() / 1000);
  if (problems.length === 0) {
    list.innerHTML = filterHostid
      ? '<div class="alerts-empty">Nenhum alerta ativo para este host.</div>'
      : '<div class="alerts-empty">Nenhum alerta ativo.</div>';
    return;
  }

  list.innerHTML = problems.map((p) => `
    <div class="alert-row">
      <div class="alert-dot ${alertsSeverityClass(p.severity)}"></div>
      <div class="alert-body">
        <div class="alert-name">${alertsEsc(p.name)}</div>
        <div class="alert-meta">${alertsEsc(p.host)} · ${alertsEsc(p.severity_label)}${p.acknowledged ? ' · <span class="alert-ack">reconhecido</span>' : ''}</div>
        <div class="alert-time">Início <b>${alertsEsc(alertsFormatClock(p.clock))}</b> · ${alertsEsc(alertsFormatAge(now - p.clock))}</div>
      </div>
    </div>
  `).join('');
}

refreshAlertasPage();
setInterval(refreshAlertasPage, ALERTAS_PAGE_REFRESH_INTERVAL_MS);
