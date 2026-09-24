const STATUS_COLOR = { up: '#3ecf6a', warn: '#f5a623', down: '#e5484d', unknown: '#888888' };
const REFRESH_INTERVAL_MS = 30000;

// Every string below comes from the database, and the CRUD API is
// unauthenticated by design — so any DB-sourced value that ends up inside an
// innerHTML / bindTooltip template literal has to be escaped first, or it is
// stored XSS. (Duplicated in circuitos.js: these are plain <script> tags with
// no module system, and a build step is not worth six lines.)
function esc(str) {
  if (str === null || str === undefined) return '';
  return String(str).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

// Corredor BR-163 (PA/MT) — região de cobertura do cliente.
const map = L.map('map').setView([-8.3, -55.4], 7);

async function addTileLayer() {
  let cfg = { tile_provider: 'osm', mapbox_token: '' };
  try {
    cfg = await (await fetch('/api/config')).json();
  } catch (err) {
    console.error('Falha ao buscar /api/config, usando OpenStreetMap', err);
  }

  if (cfg.tile_provider === 'mapbox' && cfg.mapbox_token) {
    L.tileLayer(
      `https://api.mapbox.com/styles/v1/mapbox/dark-v11/tiles/{z}/{x}/{y}?access_token=${cfg.mapbox_token}`,
      { attribution: '&copy; Mapbox &copy; OpenStreetMap', maxZoom: 20 },
    ).addTo(map);
  } else {
    // Genuine OpenStreetMap tile server — no account, no API key, no quota
    // risk, matching the spec's "grátis, sem conta" requirement for the
    // default path. (CARTO's basemaps, used here in earlier drafts, now
    // require a registered API key even for their free tier — that would
    // have silently broken the "no account needed" default for every new
    // client install, so it was replaced with the real OSM tile server.)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors', maxZoom: 19, subdomains: 'abc',
    }).addTo(map);
  }
}
addTileLayer();

let markerLayer = L.layerGroup().addTo(map);
let lineLayer = L.layerGroup().addTo(map);

// alert_severity vem de problemas REAIS abertos no Zabbix para aquele host
// (não do item de ping/SNMP) -- 4-5 = vermelho, 2-3 = amarelo, sobrepõe a
// cor normal de status quando presente. pulseClass ativa a animação CSS
// (.pulse-warn / .pulse-down em app.css) para chamar atenção no mapa.
function alertVisual(status, alertSeverity) {
  if (alertSeverity !== null && alertSeverity !== undefined) {
    if (alertSeverity >= 4) return { color: STATUS_COLOR.down, pulseClass: 'pulse-down' };
    if (alertSeverity >= 2) return { color: STATUS_COLOR.warn, pulseClass: 'pulse-warn' };
  }
  if (status === 'down') return { color: STATUS_COLOR.down, pulseClass: 'pulse-down' };
  if (status === 'warn') return { color: STATUS_COLOR.warn, pulseClass: 'pulse-warn' };
  return { color: STATUS_COLOR[status] || STATUS_COLOR.unknown, pulseClass: '' };
}

// Ícone de transmissão (wifi) dentro do glow em vez de um círculo vazio --
// reconhecível como "equipamento de rede ativo" mesmo em 16px, com stroke
// escuro que contrasta em qualquer cor de status (verde/amarelo/vermelho).
const EQUIPMENT_GLYPH =
  '<svg width="9" height="9" viewBox="0 0 24 24" fill="none" stroke="#00110a" stroke-width="3.4" ' +
  'stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.55a11 11 0 0 1 14.08 0"/>' +
  '<path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/>' +
  '<line x1="12" y1="20" x2="12.01" y2="20"/></svg>';

function glowIcon(color, pulseClass) {
  return L.divIcon({
    className: '',
    html:
      '<div class="glow-marker ' + (pulseClass || '') + '" style="position:relative;width:26px;height:26px;">' +
        '<div class="glow-halo" style="position:absolute;inset:0;border-radius:50%;background:' + color + ';opacity:0.35;filter:blur(4px)"></div>' +
        '<div style="position:absolute;top:5px;left:5px;width:16px;height:16px;border-radius:50%;background:' + color + ';border:2px solid rgba(255,255,255,0.85);box-shadow:0 0 4px rgba(0,0,0,0.4);display:flex;align-items:center;justify-content:center;">' +
          EQUIPMENT_GLYPH +
        '</div>' +
      '</div>',
    iconSize: [26, 26], iconAnchor: [13, 13],
  });
}

// O trecho "up" ganha uma camada extra de tracinhos brancos que correm ao
// longo da linha (.flow-line, animação em app.css) -- lê como dado fluindo
// pela fibra em tempo real, e some sozinho quando o link cai (nada flui
// por um link down). É o único elemento animado do mapa que se move em
// linha reta ao longo do traçado, então fica reconhecível como "assinatura".
function drawGlowLine(latlngs, color, status) {
  const opts = { weight: 5, color, opacity: 0.95, lineCap: 'round', lineJoin: 'round', smoothFactor: 3 };
  if (status === 'down') opts.dashArray = '1 10';
  L.polyline(latlngs, { weight: 14, color, opacity: 0.18, lineCap: 'round', lineJoin: 'round', smoothFactor: 3 }).addTo(lineLayer);
  const line = L.polyline(latlngs, opts).addTo(lineLayer);

  if (status === 'up') {
    L.polyline(latlngs, {
      weight: 2.5, color: '#ffffff', opacity: 0.85, lineCap: 'round', lineJoin: 'round',
      smoothFactor: 3, dashArray: '1 15', className: 'flow-line',
    }).addTo(lineLayer);
  }
  return line;
}

// Small triangular warning badge dropped at a segment's midpoint when SNMP
// isn't answering for that link — deliberately a different shape from the
// round status glow, so it reads as "monitoring degraded" rather than
// restating the line's own up/down color.
function warningIcon() {
  return L.divIcon({
    className: '',
    html:
      '<div style="position:relative;width:20px;height:20px;display:flex;align-items:center;justify-content:center;">'
      + '<div style="position:absolute;inset:0;border-radius:50%;background:#e5484d;opacity:0.3;filter:blur(3px)"></div>'
      + '<svg width="14" height="14" viewBox="0 0 24 24" fill="#e5484d" stroke="#fff" stroke-width="1.2">'
      + '<path d="M12 2 L22 20 L2 20 Z"/><line x1="12" y1="9" x2="12" y2="14" stroke="#fff" stroke-width="2"/>'
      + '<circle cx="12" cy="17" r="1.2" fill="#fff"/></svg>'
      + '</div>',
    iconSize: [20, 20], iconAnchor: [10, 10],
  });
}

function midpoint(latlngs) {
  const mid = Math.floor((latlngs.length - 1) / 2);
  const [lat1, lng1] = latlngs[mid];
  const [lat2, lng2] = latlngs[Math.min(mid + 1, latlngs.length - 1)];
  return [(lat1 + lat2) / 2, (lng1 + lng2) / 2];
}

function fmt(value, unit) {
  if (value === null || value === undefined) return '—';
  return `${value}${unit || ''}`;
}

// Mbps cru vira Gbps acima de 1000 -- em enlaces de 40G/100G um número em
// Mbps de 5 dígitos é mais difícil de ler rápido do que "3.49 Gbps".
function fmtThroughput(mbps) {
  if (mbps === null || mbps === undefined) return '—';
  if (mbps >= 1000) return `${(mbps / 1000).toFixed(2)} Gbps`;
  return `${mbps.toFixed(1)} Mbps`;
}

function fmtUptime(seconds) {
  if (seconds === null || seconds === undefined) return '—';
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${minutes}min`;
  return `${minutes}min`;
}

function fmtUpDown(value) {
  if (value === null || value === undefined) return '—';
  return value ? 'up' : 'down';
}

function fmtLatency(ms) {
  if (ms === null || ms === undefined) return '—';
  return `${ms.toFixed(1)} ms`;
}

// >85% do link = crítico (perto de saturar), >60% = atenção.
function utilizationClass(pct) {
  if (pct >= 85) return 'crit';
  if (pct >= 60) return 'warn';
  return 'ok';
}

// Tooltip como mini-tabela label/valor em vez de texto corrido com "·" --
// o texto corrido quebrava linha no meio de uma métrica e ficava
// desalinhado. `cls` opcional ('crit'/'warn'/'ok') colore só o valor.
function tipTable(title, rows) {
  const body = rows
    .map(([label, value, cls]) => `<tr><td>${esc(label)}</td><td class="${esc(cls || '')}">${esc(value)}</td></tr>`)
    .join('');
  return `<div class="tip-table-title">${esc(title)}</div><table class="tip-table">${body}</table>`;
}

const STATUS_LABEL_PT = { up: 'Operacional', warn: 'Atenção', down: 'Crítico', unknown: 'Sem dados' };

function openModal({ photoUrl, title, statusClass, kicker, rows, utilizationPct }) {
  document.getElementById('modal-photo-img').src = photoUrl;

  const modal = document.getElementById('detail-modal');
  const cls = STATUS_COLOR[statusClass] ? statusClass : 'unknown';
  modal.classList.remove('status-up', 'status-warn', 'status-down', 'status-unknown');
  modal.classList.add(`status-${cls}`);

  document.getElementById('modal-kicker').textContent = kicker
    ? `${kicker} · ${STATUS_LABEL_PT[cls]}`
    : STATUS_LABEL_PT[cls];
  document.getElementById('modal-title').textContent = title;

  const table = document.getElementById('modal-table');
  table.innerHTML = rows
    .map(([label, value]) => `<tr><td>${esc(label)}</td><td>${esc(value)}</td></tr>`)
    .join('');

  const barWrap = document.getElementById('modal-utilization');
  if (utilizationPct !== null && utilizationPct !== undefined) {
    // pct vem do backend já como número calculado (0-100), nunca de input
    // do usuário -- clamp por segurança, sem precisar de esc().
    const pct = Math.max(0, Math.min(100, utilizationPct));
    barWrap.hidden = false;
    barWrap.innerHTML =
      `<div class="util-bar-label">Utilização do link <span>${pct.toFixed(0)}%</span></div>` +
      `<div class="util-bar-track"><div class="util-bar-fill ${utilizationClass(pct)}" style="width:${pct}%"></div></div>`;
  } else {
    barWrap.hidden = true;
    barWrap.innerHTML = '';
  }

  document.getElementById('backdrop').classList.add('open');
  document.getElementById('detail-modal').classList.add('open');
}

function closeModal() {
  document.getElementById('backdrop').classList.remove('open');
  document.getElementById('detail-modal').classList.remove('open');
}
document.getElementById('modal-close').addEventListener('click', closeModal);
document.getElementById('backdrop').addEventListener('click', closeModal);

function equipmentPhotoUrl(model) {
  // No local static fallback file exists — always route through the API,
  // which already returns a generic SVG server-side when no image is
  // uploaded for the given model (including the 'generic' placeholder
  // used here when a circuit segment, not an equipment point, was clicked).
  return `/api/equipment-images/${encodeURIComponent(model || 'generic')}`;
}

function formatAge(seconds) {
  if (seconds === null || seconds === undefined) return 'nunca';
  if (seconds < 90) return `${seconds}s`;
  return `${Math.round(seconds / 60)} min`;
}

function updateStaleBanner(state) {
  const banner = document.getElementById('stale-banner');
  if (!banner) return;
  if (state.stale) {
    banner.textContent =
      `Dados do Zabbix desatualizados — última atualização há ${formatAge(state.last_refresh_seconds_ago)}. `
      + 'Os status em cinza não refletem a rede.';
    banner.hidden = false;
  } else {
    banner.hidden = true;
  }
}

// Painel lateral: lista de circuitos e de hosts, cada host com um badge
// numérico refletindo os mesmos alertas reais do Zabbix usados no pulso do
// mapa (vermelho >=4, laranja 2-3) -- clicar num host centraliza o mapa nele.
function renderOpsPanel(state) {
  const circuitsList = document.getElementById('ops-circuits-list');
  const hostsList = document.getElementById('ops-hosts-list');
  if (!circuitsList || !hostsList) return;

  circuitsList.innerHTML = state.circuits.length === 0
    ? '<div class="ops-empty">Nenhum circuito cadastrado.</div>'
    : state.circuits.map((c) => `
        <div class="ops-circuit-item">${esc(c.name)}<br><small>${esc(c.segments.length)} segmento(s)</small></div>
      `).join('');

  const hosts = state.points.filter((p) => p.point_type === 'equipment');
  if (hosts.length === 0) {
    hostsList.innerHTML = '<div class="ops-empty">Nenhum host cadastrado.</div>';
    return;
  }

  // Pior primeiro (crítico > aviso > sem alerta), depois por nome.
  const sorted = [...hosts].sort((a, b) => {
    const sevA = a.alert_severity ?? -1;
    const sevB = b.alert_severity ?? -1;
    if (sevA !== sevB) return sevB - sevA;
    return a.name.localeCompare(b.name);
  });

  hostsList.innerHTML = sorted.map((h) => {
    const hasAlert = h.alert_severity !== null && h.alert_severity !== undefined;
    const badge = hasAlert
      ? `<span class="ops-host-badge ${h.alert_severity >= 4 ? 'crit' : 'warn'}">${esc(h.alert_count)}</span>`
      : '';
    return `
      <div class="ops-host-item" data-id="${esc(h.id)}">
        <span class="ops-host-dot ${esc(h.status || 'unknown')}"></span>
        <span class="ops-host-name">${esc(h.name)}</span>
        ${badge}
      </div>
    `;
  }).join('');

  hostsList.querySelectorAll('.ops-host-item').forEach((el) => {
    el.addEventListener('click', () => {
      const host = hosts.find((h) => String(h.id) === el.dataset.id);
      if (host) map.setView([host.lat, host.lng], 12);
    });
  });
}

async function refresh() {
  let state;
  try {
    const resp = await fetch('/api/map-state');
    state = await resp.json();
  } catch (err) {
    console.error('Falha ao buscar /api/map-state', err);
    return;
  }

  updateStaleBanner(state);
  renderOpsPanel(state);

  markerLayer.clearLayers();
  lineLayer.clearLayers();

  const pointsById = Object.fromEntries(state.points.map((p) => [p.id, p]));

  state.circuits.forEach((circuit) => {
    circuit.segments.forEach((segment) => {
      const origin = pointsById[segment.origin_point_id];
      const dest = pointsById[segment.destination_point_id];
      if (!origin || !dest) return;
      const waypoints = segment.waypoint_ids.map((id) => pointsById[id]).filter(Boolean);
      const latlngs = [origin, ...waypoints, dest].map((p) => [p.lat, p.lng]);
      const color = STATUS_COLOR[segment.status] || STATUS_COLOR.unknown;
      const line = drawGlowLine(latlngs, color, segment.status);

      const statusCls = segment.status === 'down' ? 'crit' : segment.status === 'warn' ? 'warn' : 'ok';
      const utilPct = segment.utilization_pct;
      line.bindTooltip(
        tipTable(`${origin.name} ↔ ${dest.name}`, [
          ...(segment.port_name ? [['Porta', segment.port_name]] : []),
          ['Status', segment.status, statusCls],
          ['Sinal RX', fmt(segment.optical_rx_dbm, ' dBm')],
          ['Sinal TX', fmt(segment.optical_tx_dbm, ' dBm')],
          ['Entrada', fmtThroughput(segment.throughput_in_mbps)],
          ['Saída', fmtThroughput(segment.throughput_out_mbps)],
          ...(utilPct !== null && utilPct !== undefined
            ? [['Utilização', `${utilPct.toFixed(0)}%`, utilizationClass(utilPct)]]
            : []),
          ...(segment.snmp_offline ? [['SNMP', 'indisponível', 'warn']] : []),
        ]),
        { className: 'mini-tip', sticky: true },
      );
      line.on('click', () => openModal({
        photoUrl: equipmentPhotoUrl(null),
        title: `${origin.name} ↔ ${dest.name}`,
        statusClass: segment.status,
        kicker: 'Circuito',
        utilizationPct: utilPct,
        rows: [
          ['Circuito', circuit.name],
          ['Porta', segment.port_name || '—'],
          ['Status', segment.status],
          ['SNMP', segment.snmp_offline ? 'indisponível — status por ping' : 'OK'],
          ['Velocidade', fmtThroughput(segment.speed_mbps)],
          ['Throughput', `${fmtThroughput(segment.throughput_in_mbps)} ↓ / ${fmtThroughput(segment.throughput_out_mbps)} ↑`],
          ['Sinal óptico RX', fmt(segment.optical_rx_dbm, ' dBm')],
          ['Sinal óptico TX', fmt(segment.optical_tx_dbm, ' dBm')],
          ['Limiar configurado', fmt(segment.signal_warn_threshold_dbm, ' dBm')],
          ['Erros', fmt(segment.error_count, '')],
        ],
      }));

      if (segment.snmp_offline) {
        L.marker(midpoint(latlngs), { icon: warningIcon(), zIndexOffset: 500 })
          .addTo(markerLayer)
          .bindTooltip(`${esc(circuit.name)}: SNMP indisponível — status exibido por ping`, { className: 'mini-tip' });
      }
    });
  });

  state.points.forEach((point) => {
    // route_point é só geometria da linha (gerada a partir da rota real da
    // estrada) -- não é infraestrutura física, então não vira marcador.
    // waypoint é o poste/caixa que o operador cadastra manualmente.
    if (point.point_type === 'route_point') return;
    if (point.point_type === 'waypoint') {
      L.circleMarker([point.lat, point.lng], { radius: 4, color: '#888', fillOpacity: 1 })
        .addTo(markerLayer)
        .bindTooltip('Poste / caixa (só trajeto)', { className: 'mini-tip' });
      return;
    }
    const { color, pulseClass } = alertVisual(point.status, point.alert_severity);
    const marker = L.marker([point.lat, point.lng], { icon: glowIcon(color, pulseClass) }).addTo(markerLayer);
    const pingUp = point.status === 'unknown' ? null : point.status !== 'down';
    marker.bindTooltip(
      tipTable(point.name, [
        ['IP', point.equipment_ip || '—'],
        ['Ping', fmtUpDown(pingUp), pingUp === false ? 'crit' : pingUp === true ? 'ok' : ''],
        ['SNMP', point.snmp_offline ? 'down' : 'up', point.snmp_offline ? 'crit' : 'ok'],
        ['Latência', fmtLatency(point.latency_ms)],
        ['Uptime', fmtUptime(point.uptime_seconds)],
        ...(point.alert_severity !== null && point.alert_severity !== undefined
          ? [['Alertas', `${point.alert_count} aberto(s)`, point.alert_severity >= 4 ? 'crit' : 'warn']]
          : []),
      ]),
      { className: 'mini-tip' },
    );
    marker.on('click', () => openModal({
      photoUrl: equipmentPhotoUrl(point.equipment_model),
      title: point.name,
      statusClass: point.status,
      kicker: 'Equipamento',
      rows: [
        ['Modelo', point.equipment_model || '—'],
        ['IP', point.equipment_ip || '—'],
        ['Status', point.status],
        ['Ping', fmtUpDown(point.status === 'unknown' ? null : point.status !== 'down')],
        ['SNMP', point.snmp_offline ? 'indisponível' : 'OK'],
        ['Latência (RTT)', fmtLatency(point.latency_ms)],
        ['Uptime', fmtUptime(point.uptime_seconds)],
        ['CPU', fmt(point.cpu_percent, '%')],
        ['Alertas abertos', point.alert_severity !== null && point.alert_severity !== undefined
          ? `${point.alert_count} (severidade máxima: ${point.alert_severity})`
          : 'nenhum'],
      ],
    }));
  });
}

refresh();
setInterval(refresh, REFRESH_INTERVAL_MS);
