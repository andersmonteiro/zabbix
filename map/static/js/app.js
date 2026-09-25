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

const MAP_LAYER_STORAGE_KEY = 'natverk-map-layer';
const MAP_LABELS_STORAGE_KEY = 'natverk-map-labels';
const labelLayer = L.layerGroup();

// Rótulo fixo com o nome do ponto (não é o tooltip de hover, que continua
// existindo separado no marker) -- overlay opcional "Nomes dos locais".
// Callout tipo "plaquinha": uma linha fina sai do ponto exato do host e
// termina na caixa com o nome, deslocada na diagonal para não tampar o
// próprio marcador. Um L.marker com divIcon (não L.tooltip) porque
// precisamos desenhar essa linha nós mesmos dentro do ícone.
const LABEL_DX = 20;
const LABEL_DY = -13;

function labelMarker(lat, lng, text) {
  const html =
    `<svg width="160" height="46" viewBox="-4 -27 160 46" style="position:absolute;left:0;top:0;overflow:visible;pointer-events:none;">` +
    `<line x1="0" y1="0" x2="${LABEL_DX}" y2="${LABEL_DY}" stroke="rgba(255,255,255,0.55)" stroke-width="1.2"/>` +
    `<circle cx="0" cy="0" r="2" fill="rgba(255,255,255,0.85)"/>` +
    `</svg>` +
    `<div class="map-label" style="position:absolute;left:${LABEL_DX + 5}px;top:${LABEL_DY - 9}px;">${esc(text)}</div>`;
  return L.marker([lat, lng], {
    icon: L.divIcon({ className: '', html, iconSize: [0, 0], iconAnchor: [0, 0] }),
    interactive: false, keyboard: false,
  });
}

function renderLabels(points) {
  labelLayer.clearLayers();
  points.forEach((p) => {
    if (p.point_type !== 'equipment') return;
    labelMarker(p.lat, p.lng, p.name).addTo(labelLayer);
  });
}

// Três opções sempre disponíveis, todas grátis/sem conta/sem API key (ver
// o comentário histórico abaixo sobre CARTO). "Escuro" reaproveita o
// próprio tile server OSM só com um filtro CSS (.tiles-dark em app.css),
// então continua sendo o mesmo provedor -- não é um serviço à parte.
function initTileLayers(cfg) {
  const layers = {
    'Claro': L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors', maxZoom: 19, subdomains: 'abc', className: 'tiles-light',
    }),
    'Escuro': L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors', maxZoom: 19, subdomains: 'abc', className: 'tiles-dark',
    }),
    'Satélite': L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
      attribution: 'Tiles &copy; Esri, Maxar, Earthstar Geographics', maxZoom: 19,
    }),
  };

  // Mapbox Dark só aparece quando o cliente configurou um token -- opção
  // extra, não obrigatória (ver comentário "grátis, sem conta" acima).
  if (cfg.tile_provider === 'mapbox' && cfg.mapbox_token) {
    layers['Mapbox Dark'] = L.tileLayer(
      `https://api.mapbox.com/styles/v1/mapbox/dark-v11/tiles/{z}/{x}/{y}?access_token=${cfg.mapbox_token}`,
      { attribution: '&copy; Mapbox &copy; OpenStreetMap', maxZoom: 20 },
    );
  }

  let savedName = null;
  try { savedName = localStorage.getItem(MAP_LAYER_STORAGE_KEY); } catch (err) { /* private mode etc. */ }
  (layers[savedName] || layers['Escuro']).addTo(map);

  // "Nomes dos locais" é um overlay (não um basemap) -- fica marcável
  // independente de qual basemap está ativo, mostrando o nome de cada
  // equipamento como rótulo fixo ao lado do ponto (ver labelLayer/
  // renderLabels), não só ao passar o mouse.
  const overlays = { 'Nomes dos locais': labelLayer };
  L.control.layers(layers, overlays, { position: 'topright' }).addTo(map);

  let labelsOn = false;
  try { labelsOn = localStorage.getItem(MAP_LABELS_STORAGE_KEY) === '1'; } catch (err) { /* private mode etc. */ }
  if (labelsOn) labelLayer.addTo(map);

  map.on('baselayerchange', (e) => {
    try { localStorage.setItem(MAP_LAYER_STORAGE_KEY, e.name); } catch (err) { /* private mode etc. */ }
  });
  map.on('overlayadd overlayremove', (e) => {
    if (e.name !== 'Nomes dos locais') return;
    try { localStorage.setItem(MAP_LABELS_STORAGE_KEY, e.type === 'overlayadd' ? '1' : '0'); } catch (err) { /* private mode etc. */ }
  });
}

async function addTileLayer() {
  let cfg = { tile_provider: 'osm', mapbox_token: '' };
  try {
    cfg = await (await fetch('/api/config')).json();
  } catch (err) {
    console.error('Falha ao buscar /api/config, usando OpenStreetMap', err);
  }
  // Nenhuma opção padrão precisa de conta/API key/quota -- CARTO's
  // basemaps, usados aqui em rascunhos anteriores, passaram a exigir
  // chave registrada até no tier grátis, o que quebraria silenciosamente
  // a instalação "sem conta" para todo cliente novo.
  initTileLayers(cfg);
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

// Switch de rede (retângulo com 3 portas) em vez do glifo de wifi anterior
// -- o wifi em 9px virava um borrão irreconhecível; um retângulo com
// divisórias grossas lê como "equipamento com portas" mesmo pequeno, e
// combina com os cantos retos do resto da UI (nada de curvas finas).
const EQUIPMENT_GLYPH =
  '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#00110a" stroke-width="2.6" ' +
  'stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="6" width="18" height="12"/>' +
  '<line x1="8.5" y1="6" x2="8.5" y2="18"/><line x1="15.5" y1="6" x2="15.5" y2="18"/></svg>';

function glowIcon(color, pulseClass) {
  return L.divIcon({
    className: '',
    html:
      '<div class="glow-marker ' + (pulseClass || '') + '" style="position:relative;width:34px;height:34px;">' +
        '<div class="glow-halo" style="position:absolute;inset:0;background:' + color + ';opacity:0.35;filter:blur(4px)"></div>' +
        '<div style="position:absolute;top:6px;left:6px;width:22px;height:22px;background:' + color + ';border:2px solid rgba(255,255,255,0.9);box-shadow:0 1px 6px rgba(0,0,0,0.5);display:flex;align-items:center;justify-content:center;">' +
          EQUIPMENT_GLYPH +
        '</div>' +
      '</div>',
    iconSize: [34, 34], iconAnchor: [17, 17],
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
      + '<div style="position:absolute;inset:0;background:#e5484d;opacity:0.3;filter:blur(3px)"></div>'
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

  // Só a linha de circuito popula isso (renderSegmentChart, chamado depois
  // de openModal no handler de clique) -- reseta aqui pra não sobrar o
  // gráfico do último segmento aberto quando o clique agora é num ponto.
  const chartWrap = document.getElementById('modal-chart');
  chartWrap.hidden = true;
  chartWrap.innerHTML = '';
  modal.classList.remove('has-chart');

  document.getElementById('backdrop').classList.add('open');
  document.getElementById('detail-modal').classList.add('open');
}

function fmtTime(epochSeconds) {
  return new Date(epochSeconds * 1000).toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
}

// Índice do ponto de `series` (ordenado por tempo) mais próximo de `t`,
// via busca binária -- usado pelo hover pra achar o valor sob o cursor
// sem varrer a série inteira a cada movimento do mouse.
function nearestSeriesIndex(series, t) {
  if (!series.length) return -1;
  let lo = 0, hi = series.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (series[mid][0] < t) lo = mid + 1; else hi = mid;
  }
  if (lo > 0 && Math.abs(series[lo - 1][0] - t) < Math.abs(series[lo][0] - t)) return lo - 1;
  return lo;
}

// Gráfico de histórico de tráfego (SVG desenhado à mão, sem lib de chart)
// -- estilo inspirado no motion.dev: fundo escuro, grid sutil, linha fina
// com um ponto de destaque na ponta mais recente. Todos os valores vêm
// computados do backend (timestamps/Mbps numéricos), nunca texto livre de
// usuário, então entram direto no SVG sem passar por esc(). Retorna também
// `meta`, com as coordenadas de projeção que o hover reusa pra não duplicar
// a lógica de escala tempo/valor -> pixel.
function buildSparkline(seriesIn, seriesOut) {
  const width = 292, height = 118;
  const pad = { top: 10, right: 8, bottom: 8, left: 8 };
  const plotW = width - pad.left - pad.right;
  const plotH = height - pad.top - pad.bottom;

  const allPoints = [...seriesIn, ...seriesOut];
  if (allPoints.length < 2) {
    return { html: '<div class="chart-empty">Sem histórico suficiente para este período.</div>', meta: null };
  }

  const maxV = Math.max(...allPoints.map((p) => p[1]), 0.01);
  const times = allPoints.map((p) => p[0]);
  const minT = Math.min(...times);
  const spanT = Math.max(Math.max(...times) - minT, 1);

  function project(series) {
    return series.map(([t, v]) => [
      pad.left + ((t - minT) / spanT) * plotW,
      pad.top + (1 - v / maxV) * plotH,
    ]);
  }

  function pathFor(pts) {
    return pts.map(([x, y], i) => `${i === 0 ? 'M' : 'L'} ${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
  }

  const inPts = project(seriesIn);
  const outPts = project(seriesOut);
  const gridY = [0.25, 0.5, 0.75].map((f) => pad.top + f * plotH);

  const lastDot = (pts, cls) => pts.length
    ? `<circle cx="${pts[pts.length - 1][0].toFixed(1)}" cy="${pts[pts.length - 1][1].toFixed(1)}" r="2.6" class="chart-dot ${cls}"/>`
    : '';

  const html = `
    <svg viewBox="0 0 ${width} ${height}" class="chart-svg" preserveAspectRatio="none">
      ${gridY.map((y) => `<line x1="${pad.left}" y1="${y.toFixed(1)}" x2="${width - pad.right}" y2="${y.toFixed(1)}" class="chart-grid"/>`).join('')}
      ${inPts.length ? `<path d="${pathFor(inPts)}" class="chart-line chart-line-in" fill="none"/>` : ''}
      ${outPts.length ? `<path d="${pathFor(outPts)}" class="chart-line chart-line-out" fill="none"/>` : ''}
      ${lastDot(inPts, 'chart-dot-in')}
      ${lastDot(outPts, 'chart-dot-out')}
      <line class="chart-hover-line" x1="0" y1="${pad.top}" x2="0" y2="${height - pad.bottom}"/>
      <circle class="chart-hover-dot chart-dot-in"/>
      <circle class="chart-hover-dot chart-dot-out"/>
    </svg>
    <div class="chart-tooltip"></div>
    <div class="chart-footer">
      <span class="chart-legend-item"><span class="chart-swatch chart-swatch-in"></span>Entrada</span>
      <span class="chart-legend-item"><span class="chart-swatch chart-swatch-out"></span>Saída</span>
      <span class="chart-max">pico ${esc(fmtThroughput(maxV))}</span>
    </div>
  `;

  return { html, meta: { pad, plotW, plotH, minT, spanT, maxV, width, height, seriesIn, seriesOut } };
}

// Liga o mouseover do SVG a uma linha-guia + tooltip com os valores exatos
// sob o cursor. `meta` vem de buildSparkline -- null quando não há série
// suficiente pra desenhar (nesse caso não tem o que ligar).
function setupChartHover(container, meta) {
  if (!meta) return;
  const svg = container.querySelector('.chart-svg');
  const hoverLine = container.querySelector('.chart-hover-line');
  const hoverDotIn = container.querySelector('.chart-hover-dot.chart-dot-in');
  const hoverDotOut = container.querySelector('.chart-hover-dot.chart-dot-out');
  const tooltip = container.querySelector('.chart-tooltip');
  if (!svg || !hoverLine || !tooltip) return;

  function valueY(v) {
    return meta.pad.top + (1 - v / meta.maxV) * meta.plotH;
  }

  function onMove(evt) {
    const rect = svg.getBoundingClientRect();
    if (!rect.width) return;
    const xFrac = Math.max(0, Math.min(1, (evt.clientX - rect.left) / rect.width));
    const svgX = meta.pad.left + xFrac * meta.plotW;
    const t = meta.minT + ((svgX - meta.pad.left) / meta.plotW) * meta.spanT;

    const idxIn = nearestSeriesIndex(meta.seriesIn, t);
    const idxOut = nearestSeriesIndex(meta.seriesOut, t);
    if (idxIn < 0 && idxOut < 0) return;

    const refPoint = idxIn >= 0 ? meta.seriesIn[idxIn] : meta.seriesOut[idxOut];
    const px = meta.pad.left + ((refPoint[0] - meta.minT) / meta.spanT) * meta.plotW;

    hoverLine.setAttribute('x1', px.toFixed(1));
    hoverLine.setAttribute('x2', px.toFixed(1));
    hoverLine.style.display = '';

    let rows = '';
    if (idxIn >= 0) {
      const v = meta.seriesIn[idxIn];
      hoverDotIn.setAttribute('cx', px.toFixed(1));
      hoverDotIn.setAttribute('cy', valueY(v[1]).toFixed(1));
      hoverDotIn.style.display = '';
      rows += `<div class="chart-tooltip-row in">Entrada <b>${esc(fmtThroughput(v[1]))}</b></div>`;
    } else {
      hoverDotIn.style.display = 'none';
    }
    if (idxOut >= 0) {
      const v = meta.seriesOut[idxOut];
      hoverDotOut.setAttribute('cx', px.toFixed(1));
      hoverDotOut.setAttribute('cy', valueY(v[1]).toFixed(1));
      hoverDotOut.style.display = '';
      rows += `<div class="chart-tooltip-row out">Saída <b>${esc(fmtThroughput(v[1]))}</b></div>`;
    } else {
      hoverDotOut.style.display = 'none';
    }

    tooltip.innerHTML = `<div class="chart-tooltip-time">${esc(fmtTime(refPoint[0]))}</div>${rows}`;
    tooltip.style.display = 'block';

    // Mantém a tooltip perto do cursor sem vazar pra fora do container.
    const wrapRect = container.getBoundingClientRect();
    let left = evt.clientX - wrapRect.left + 14;
    const maxLeft = wrapRect.width - tooltip.offsetWidth - 6;
    if (left > maxLeft) left = evt.clientX - wrapRect.left - tooltip.offsetWidth - 14;
    tooltip.style.left = `${Math.max(6, left)}px`;
  }

  function onLeave() {
    hoverLine.style.display = 'none';
    hoverDotIn.style.display = 'none';
    hoverDotOut.style.display = 'none';
    tooltip.style.display = 'none';
  }

  svg.addEventListener('mousemove', onMove);
  svg.addEventListener('mouseleave', onLeave);
}

async function renderSegmentChart(segmentId) {
  const container = document.getElementById('modal-chart');
  const modal = document.getElementById('detail-modal');
  container.hidden = false;
  modal.classList.add('has-chart');
  container.innerHTML = '<div class="chart-title">Tráfego</div><div class="chart-loading">Carregando histórico…</div>';
  try {
    const resp = await fetch(`/api/segments/${segmentId}/history?hours=6`);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    // O modal pode ter sido fechado/trocado enquanto o fetch corria.
    if (container.hidden) return;
    const { html, meta } = buildSparkline(data.throughput_in_mbps || [], data.throughput_out_mbps || []);
    container.innerHTML = `<div class="chart-title">Tráfego — últimas ${esc(data.hours)}h</div>` + html;
    setupChartHover(container, meta);
  } catch (err) {
    console.error('Falha ao carregar histórico do segmento', err);
    if (container.hidden) return;
    container.innerHTML = '<div class="chart-title">Tráfego</div><div class="chart-empty">Não foi possível carregar o histórico.</div>';
  }
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
  renderLabels(state.points);

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
      line.on('click', () => {
        openModal({
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
        });
        renderSegmentChart(segment.id);
      });

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
