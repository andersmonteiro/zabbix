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

async function api(path, options) {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!resp.ok) throw new Error(`${path} -> HTTP ${resp.status}`);
  if (resp.status === 204) return null;
  return resp.json();
}

async function loadPoints() {
  allPoints = await api('/api/points');
  const list = document.getElementById('points-list');
  list.innerHTML = allPoints.map((p) => `<div class="list-item">${p.name} <small>(${p.point_type})</small></div>`).join('');

  const originSel = document.getElementById('origin-select');
  const destSel = document.getElementById('destination-select');
  const equipmentOptions = allPoints
    .filter((p) => p.point_type === 'equipment')
    .map((p) => `<option value="${p.id}">${p.name}</option>`).join('');
  originSel.innerHTML = equipmentOptions;
  destSel.innerHTML = equipmentOptions;
}

async function loadCircuits() {
  const circuits = await api('/api/circuits');
  const list = document.getElementById('circuits-list');
  list.innerHTML = circuits.map((c) => `
    <div class="list-item${c.id === selectedCircuitId ? ' selected' : ''}" data-id="${c.id}">${c.name}</div>
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
  await api('/api/points', { method: 'POST', body: JSON.stringify(body) });
  e.target.reset();
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
