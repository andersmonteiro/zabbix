const editorMap = L.map('editor-map').setView([-23.5629, -46.6544], 13);

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
    ).addTo(editorMap);
  } else {
    // Genuine OpenStreetMap tile server — no account, no API key, no quota
    // risk, matching the spec's "grátis, sem conta" requirement for the
    // default path. (CARTO's basemaps, used here in earlier drafts, now
    // require a registered API key even for their free tier — that would
    // have silently broken the "no account needed" default for every new
    // client install, so it was replaced with the real OSM tile server.)
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors', maxZoom: 19, subdomains: 'abc',
    }).addTo(editorMap);
  }
}
addTileLayer();

let allPoints = [];
let selectedCircuitId = null;

// Same helper as app.js — DB-sourced strings are attacker-controllable through
// the unauthenticated CRUD API, so nothing untrusted reaches innerHTML raw.
// (Deliberately duplicated: both files are plain <script> tags with no module
// system, and a build step is not worth six lines.)
function esc(str) {
  if (str === null || str === undefined) return '';
  return String(str).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

async function api(path, options) {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!resp.ok) {
    // Surface the server's Portuguese message (e.g. "lat deve ser um número
    // entre -90 e 90") instead of a bare status code.
    let detail = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      if (body && body.error) detail = body.error;
    } catch (err) {
      /* non-JSON error body — keep the status code */
    }
    throw new Error(detail);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

function setFormStatus(elementId, message, isError) {
  const el = document.getElementById(elementId);
  if (!el) return;
  el.textContent = message;
  el.style.color = isError ? '#e5484d' : 'rgba(255,255,255,0.5)';
}

async function loadPoints() {
  allPoints = await api('/api/points');
  const list = document.getElementById('points-list');
  list.innerHTML = allPoints
    .map((p) => `<div class="list-item">${esc(p.name)} <small>(${esc(p.point_type)})</small></div>`)
    .join('');

  const originSel = document.getElementById('origin-select');
  const destSel = document.getElementById('destination-select');
  const equipmentOptions = allPoints
    .filter((p) => p.point_type === 'equipment')
    .map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
  originSel.innerHTML = equipmentOptions;
  destSel.innerHTML = equipmentOptions;
}

async function loadCircuits() {
  const circuits = await api('/api/circuits');
  const list = document.getElementById('circuits-list');
  list.innerHTML = circuits.map((c) => `
    <div class="list-item${c.id === selectedCircuitId ? ' selected' : ''}" data-id="${esc(c.id)}">${esc(c.name)}</div>
  `).join('');
  list.querySelectorAll('.list-item').forEach((el) => {
    el.addEventListener('click', () => selectCircuit(Number(el.dataset.id)));
  });
}

async function selectCircuit(circuitId) {
  selectedCircuitId = circuitId;
  document.getElementById('segment-panel').style.display = 'block';
  await loadCircuits();
  window.currentCircuit = await api(`/api/circuits/${circuitId}`);

  const pointIds = new Set(allPoints.map((p) => p.id));
  const brokenSegments = window.currentCircuit.segments.filter(
    (s) => !pointIds.has(s.origin_point_id) || !pointIds.has(s.destination_point_id),
  );
  const warningEl = document.getElementById('segment-warning') || (() => {
    const el = document.createElement('p');
    el.id = 'segment-warning';
    el.style.color = '#f5a623';
    document.getElementById('segment-panel').prepend(el);
    return el;
  })();
  warningEl.textContent = brokenSegments.length > 0
    ? `${brokenSegments.length} segmento(s) referenciam um ponto que não existe mais — corrija ou remova.`
    : '';

  window.renderCircuitOnEditorMap(window.currentCircuit, allPoints);
}

document.getElementById('point-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const body = {
    name: form.get('name'), lat: parseFloat(form.get('lat')), lng: parseFloat(form.get('lng')),
    point_type: form.get('point_type'),
    zabbix_hostid: form.get('zabbix_hostid') || null,
    zabbix_status_itemid: form.get('zabbix_status_itemid') || null,
    zabbix_cpu_itemid: form.get('zabbix_cpu_itemid') || null,
    equipment_model: form.get('equipment_model') || null,
    equipment_ip: form.get('equipment_ip') || null,
  };
  setFormStatus('point-status', '', false);
  try {
    await api('/api/points', { method: 'POST', body: JSON.stringify(body) });
  } catch (err) {
    // Without this the api() rejection was swallowed and the form simply did
    // nothing visible — e.g. a non-numeric latitude looked like a dead button.
    console.error('Falha ao criar ponto', err);
    setFormStatus('point-status', `Falha ao criar ponto: ${err.message}`, true);
    return;
  }
  e.target.reset();
  setFormStatus('point-status', 'Ponto criado.', false);
  await loadPoints();
});

document.getElementById('circuit-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const circuit = await api('/api/circuits', { method: 'POST', body: JSON.stringify({ name: form.get('name') }) });
  e.target.reset();
  await loadCircuits();
  await selectCircuit(circuit.id);
});

document.getElementById('segment-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  if (!selectedCircuitId) return;
  const form = new FormData(e.target);
  const nextOrderIndex = (window.currentCircuit?.segments?.length) || 0;
  const body = {
    order_index: nextOrderIndex,
    origin_point_id: Number(form.get('origin_point_id')),
    destination_point_id: Number(form.get('destination_point_id')),
    waypoint_ids: [],
    zabbix_operstatus_itemid: form.get('zabbix_operstatus_itemid') || null,
    zabbix_speed_itemid: form.get('zabbix_speed_itemid') || null,
    zabbix_throughput_in_itemid: form.get('zabbix_throughput_in_itemid') || null,
    zabbix_throughput_out_itemid: form.get('zabbix_throughput_out_itemid') || null,
    zabbix_optical_rx_itemid: form.get('zabbix_optical_rx_itemid') || null,
    zabbix_error_itemid: form.get('zabbix_error_itemid') || null,
    signal_warn_threshold_dbm: form.get('signal_warn_threshold_dbm') ? parseFloat(form.get('signal_warn_threshold_dbm')) : null,
  };
  await api(`/api/circuits/${selectedCircuitId}/segments`, { method: 'POST', body: JSON.stringify(body) });
  e.target.reset();
  await selectCircuit(selectedCircuitId);
});

(async function init() {
  await loadPoints();
  await loadCircuits();
})();
