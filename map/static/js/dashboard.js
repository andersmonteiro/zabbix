function dashEsc(str) {
  if (str === null || str === undefined) return '';
  return String(str).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

async function dashApi(path) {
  const resp = await fetch(path);
  if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
  return resp.json();
}

function dashAgeLabel(seconds) {
  if (seconds < 60) return 'agora';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min atrás`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h atrás`;
  return `${Math.floor(seconds / 86400)} d atrás`;
}

function dashSevClass(severity) {
  if (severity >= 4) return 'sev-crit';
  if (severity >= 2) return 'sev-warn';
  return 'sev-info';
}

// Pior-primeiro: um host "down" importa mais que um "up" no painel de saúde.
const STATUS_RANK = { down: 0, warn: 1, unknown: 2, up: 3 };

async function loadDashboard() {
  const [hosts, mapState, alertsState, circuits] = await Promise.allSettled([
    dashApi('/api/zabbix/hosts'),
    dashApi('/api/map-state'),
    dashApi('/api/alerts'),
    dashApi('/api/circuits'),
  ]);

  renderHostKpis(hosts.status === 'fulfilled' ? hosts.value : null);
  renderMapDependentPanels(mapState.status === 'fulfilled' ? mapState.value : null, hosts.status === 'fulfilled' ? hosts.value : []);
  renderAlerts(alertsState.status === 'fulfilled' ? alertsState.value : null);
  renderCircuits(circuits.status === 'fulfilled' ? circuits.value : null);
}

function renderHostKpis(hosts) {
  if (!hosts) {
    document.getElementById('kpi-hosts-total').textContent = '—';
    document.getElementById('kpi-hosts-sub').textContent = 'indisponível';
    document.getElementById('kpi-ssh-fail').textContent = '—';
    document.getElementById('kpi-ssh-sub').textContent = 'indisponível';
    return;
  }
  document.getElementById('kpi-hosts-total').textContent = hosts.length;
  const groupsCount = new Set(hosts.flatMap((h) => h.groups)).size;
  document.getElementById('kpi-hosts-sub').textContent = `em ${groupsCount} grupo(s)`;

  const sshFail = hosts.filter((h) => h.ssh_last_ok === false).length;
  const sshUnknown = hosts.filter((h) => h.ssh_last_ok === null || h.ssh_last_ok === undefined).length;
  const sshFailEl = document.getElementById('kpi-ssh-fail');
  sshFailEl.textContent = sshFail;
  sshFailEl.className = `kpi-card-value${sshFail > 0 ? ' crit' : ''}`;
  document.getElementById('kpi-ssh-sub').textContent = `${sshUnknown} nunca testado(s)`;
}

function renderMapDependentPanels(mapState, hosts) {
  const healthList = document.getElementById('health-list');
  const healthSub = document.getElementById('health-panel-sub');
  const hostsByHostid = new Map((hosts || []).map((h) => [String(h.hostid), h]));

  if (!mapState) {
    healthList.innerHTML = '<div class="dash-empty">Não foi possível carregar o status da rede.</div>';
    healthSub.textContent = '—';
    renderStatusBar({ up: 0, warn: 0, down: 0, unknown: 0 });
    document.getElementById('kpi-hosts-up').textContent = '—';
    document.getElementById('kpi-hosts-up-sub').textContent = 'indisponível';
    return;
  }

  const points = (mapState.points || []).filter((p) => p.point_type === 'equipment');
  const counts = { up: 0, warn: 0, down: 0, unknown: 0 };
  points.forEach((p) => { counts[p.status] = (counts[p.status] || 0) + 1; });

  document.getElementById('kpi-hosts-up').textContent = counts.up;
  document.getElementById('kpi-hosts-up-sub').textContent = `${counts.up}/${points.length} no mapa`;

  renderStatusBar(counts);

  if (points.length === 0) {
    healthList.innerHTML = '<div class="dash-empty">Nenhum ponto de equipamento no mapa.</div>';
    healthSub.textContent = '0 pontos';
    return;
  }

  healthSub.textContent = `${points.length} ponto(s)`;
  const sorted = [...points].sort((a, b) => (STATUS_RANK[a.status] ?? 9) - (STATUS_RANK[b.status] ?? 9));
  healthList.innerHTML = sorted.slice(0, 8).map((p) => {
    const host = hostsByHostid.get(String(p.zabbix_hostid));
    const meta = host ? [host.vendor, host.groups[0]].filter(Boolean).join(' · ') : '—';
    const latency = p.latency_ms !== null && p.latency_ms !== undefined ? `${Math.round(p.latency_ms)} ms` : '—';
    return `
      <div class="health-row">
        <div class="health-name" title="${dashEsc(p.name)}">${dashEsc(p.name)}</div>
        <div class="health-meta" title="${dashEsc(meta)}">${dashEsc(meta)}</div>
        <span class="status-pill ${dashEsc(p.status)}">${dashEsc(p.status)}</span>
        <div class="health-latency">${dashEsc(latency)}</div>
      </div>
    `;
  }).join('');
}

function renderStatusBar(counts) {
  const total = counts.up + counts.warn + counts.down + counts.unknown;
  const track = document.getElementById('status-bar-track');
  const legend = document.getElementById('status-legend');
  const labels = { up: 'Operacional', warn: 'Atenção', down: 'Down', unknown: 'Sem dados' };

  if (total === 0) {
    track.innerHTML = '<div class="status-bar-seg unknown" style="flex:1;"></div>';
    legend.innerHTML = '<div class="status-legend-item">Nenhum host no mapa ainda.</div>';
    return;
  }

  track.innerHTML = Object.keys(labels).map((key) => {
    const pct = (counts[key] / total) * 100;
    return pct > 0 ? `<div class="status-bar-seg ${key}" style="flex: ${pct};"></div>` : '';
  }).join('');

  legend.innerHTML = Object.entries(labels).map(([key, label]) => `
    <div class="status-legend-item"><span class="status-legend-dot ${key}"></span>${dashEsc(label)}: ${counts[key]}</div>
  `).join('');
}

function renderAlerts(state) {
  const kpiEl = document.getElementById('kpi-alerts');
  const kpiSub = document.getElementById('kpi-alerts-sub');
  const list = document.getElementById('recent-alerts-list');

  if (!state || state.stale) {
    kpiEl.textContent = '—';
    kpiSub.textContent = 'sem dados recentes';
    list.innerHTML = '<div class="dash-empty">Sem dados recentes do Zabbix.</div>';
    return;
  }

  const active = (state.problems || []).filter((p) => !p.resolved);
  kpiEl.textContent = active.length;
  kpiEl.className = `kpi-card-value${active.length > 0 ? ' crit' : ' ok'}`;
  const crit = active.filter((p) => p.severity >= 4).length;
  kpiSub.textContent = crit > 0 ? `${crit} crítico(s)` : (active.length > 0 ? 'nenhum crítico' : 'tudo normal');

  if (active.length === 0) {
    list.innerHTML = '<div class="dash-empty">Nenhum alerta ativo.</div>';
    return;
  }

  const now = Math.floor(Date.now() / 1000);
  const sorted = [...active].sort((a, b) => b.severity - a.severity || b.clock - a.clock);
  list.innerHTML = sorted.slice(0, 6).map((p) => `
    <div class="action-item">
      <div class="action-icon ${dashSevClass(p.severity)}">
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
      </div>
      <div class="action-body">
        <div class="action-title" title="${dashEsc(p.name)}">${dashEsc(p.name)}</div>
        <div class="action-sub">${dashEsc(p.host)} · ${dashEsc(dashAgeLabel(now - p.clock))}</div>
      </div>
      <a class="action-link" href="/alertas.html?hostid=${dashEsc(p.hostid)}">Ver</a>
    </div>
  `).join('');
}

function renderCircuits(circuits) {
  const kpiEl = document.getElementById('kpi-circuits');
  const kpiSub = document.getElementById('kpi-circuits-sub');
  if (!circuits) {
    kpiEl.textContent = '—';
    kpiSub.textContent = 'indisponível';
    return;
  }
  kpiEl.textContent = circuits.length;
  const segments = circuits.reduce((sum, c) => sum + (c.segments ? c.segments.length : 0), 0);
  kpiSub.textContent = `${segments} segmento(s)`;
}

loadDashboard();
