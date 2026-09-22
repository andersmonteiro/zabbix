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

const map = L.map('map').setView([-23.5629, -46.6544], 13);

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

function glowIcon(color) {
  return L.divIcon({
    className: '',
    html:
      '<div style="position:relative;width:26px;height:26px;">' +
        '<div style="position:absolute;inset:0;border-radius:50%;background:' + color + ';opacity:0.35;filter:blur(4px)"></div>' +
        '<div style="position:absolute;top:5px;left:5px;width:16px;height:16px;border-radius:50%;background:' + color + ';border:2px solid rgba(255,255,255,0.85);box-shadow:0 0 4px rgba(0,0,0,0.4)"></div>' +
      '</div>',
    iconSize: [26, 26], iconAnchor: [13, 13],
  });
}

function drawGlowLine(latlngs, color, dashed) {
  const opts = { weight: 5, color, opacity: 0.95, lineCap: 'round', lineJoin: 'round', smoothFactor: 3 };
  if (dashed) opts.dashArray = '1 10';
  L.polyline(latlngs, { weight: 14, color, opacity: 0.18, lineCap: 'round', lineJoin: 'round', smoothFactor: 3 }).addTo(lineLayer);
  return L.polyline(latlngs, opts).addTo(lineLayer);
}

function fmt(value, unit) {
  if (value === null || value === undefined) return '—';
  return `${value}${unit || ''}`;
}

function openModal({ photoUrl, title, statusClass, rows }) {
  document.getElementById('modal-photo-img').src = photoUrl;
  const titleEl = document.getElementById('modal-title');
  titleEl.innerHTML = `<span class="status-dot ${esc(statusClass)}"></span>${esc(title)}`;
  const table = document.getElementById('modal-table');
  table.innerHTML = rows
    .map(([label, value]) => `<tr><td>${esc(label)}</td><td>${esc(value)}</td></tr>`)
    .join('');
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
      const line = drawGlowLine(latlngs, color, segment.status === 'down');

      line.bindTooltip(
        `${esc(circuit.name)}<br>${esc(segment.status)} · sinal ${esc(fmt(segment.optical_rx_dbm, ' dBm'))} · ` +
        `${esc(fmt(segment.throughput_in_mbps, ' Mbps'))} / ${esc(fmt(segment.throughput_out_mbps, ' Mbps'))}`,
        { className: 'mini-tip', sticky: true },
      );
      line.on('click', () => openModal({
        photoUrl: equipmentPhotoUrl(null),
        title: circuit.name,
        statusClass: segment.status,
        rows: [
          ['Status', segment.status],
          ['Velocidade', fmt(segment.speed_mbps, ' Mbps')],
          ['Throughput', `${fmt(segment.throughput_in_mbps, ' Mbps')} ↓ / ${fmt(segment.throughput_out_mbps, ' Mbps')} ↑`],
          ['Sinal óptico', fmt(segment.optical_rx_dbm, ' dBm')],
          ['Limiar configurado', fmt(segment.signal_warn_threshold_dbm, ' dBm')],
          ['Erros', fmt(segment.error_count, '')],
        ],
      }));
    });
  });

  state.points.forEach((point) => {
    if (point.point_type === 'waypoint') {
      L.circleMarker([point.lat, point.lng], { radius: 4, color: '#888', fillOpacity: 1 })
        .addTo(markerLayer)
        .bindTooltip('Poste / caixa (só trajeto)', { className: 'mini-tip' });
      return;
    }
    const color = STATUS_COLOR[point.status] || STATUS_COLOR.unknown;
    const marker = L.marker([point.lat, point.lng], { icon: glowIcon(color) }).addTo(markerLayer);
    marker.bindTooltip(
      `<b>${esc(point.name)}</b><br>${esc(point.equipment_ip || '')} · ${esc(point.status)}`,
      { className: 'mini-tip' },
    );
    marker.on('click', () => openModal({
      photoUrl: equipmentPhotoUrl(point.equipment_model),
      title: point.name,
      statusClass: point.status,
      rows: [
        ['Modelo', point.equipment_model || '—'],
        ['IP', point.equipment_ip || '—'],
        ['Status', point.status],
        ['CPU', fmt(point.cpu_percent, '%')],
      ],
    }));
  });
}

refresh();
setInterval(refresh, REFRESH_INTERVAL_MS);
