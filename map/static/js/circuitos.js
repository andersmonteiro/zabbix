// Corredor BR-163 (PA/MT) — região de cobertura do cliente.
const editorMap = L.map('editor-map').setView([-8.3, -55.4], 7);

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
    // className: 'tiles-dark' reaplica o mesmo filtro CSS que o mapa
    // principal usa pra escurecer o OSM sem precisar de conta/token --
    // ver .tiles-dark .leaflet-tile em app.css. Mesmo tile, mesma cara.
    L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; OpenStreetMap contributors', maxZoom: 19, subdomains: 'abc', className: 'tiles-dark',
    }).addTo(editorMap);
  }
}
addTileLayer();

let allPoints = [];
let allCircuits = [];
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

// A tela só precisa de Points pra alimentar os selects de Lado A/B e pro
// roteamento OSRM (lat/lng) -- a listagem manual de pontos (e o CRUD que
// vinha junto) saiu da tela: equipamentos já ganham coordenada no cadastro
// de Hosts, e pontos de trajeto nascem sozinhos ao criar/ajustar um circuito.
async function loadPoints() {
  allPoints = await api('/api/points');
  const originSel = document.getElementById('origin-select');
  const destSel = document.getElementById('destination-select');
  const equipmentOptions = allPoints
    .filter((p) => p.point_type === 'equipment')
    .map((p) => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
  originSel.innerHTML = equipmentOptions;
  destSel.innerHTML = equipmentOptions;
  if (destSel.options.length > 1) destSel.selectedIndex = 1; // evita A e B começarem no mesmo host
}

// Interfaces já resolvidas do host escolhido em cada lado -- alimentadas por
// onSideHostChange, consultadas no submit do formulário pra montar os
// itemids do segmento sem o operador precisar saber nenhum deles de cor.
let originInterfaces = [];
let destinationInterfaces = [];

async function fetchHostInterfaces(hostid) {
  if (!hostid) return [];
  try {
    return await api(`/api/zabbix/hosts/${hostid}/interfaces`);
  } catch (err) {
    console.error('Falha ao buscar interfaces do host', hostid, err);
    return [];
  }
}

function populateIfaceSelect(selectEl, interfaces, emptyLabel) {
  if (interfaces.length === 0) {
    selectEl.innerHTML = `<option value="">${esc(emptyLabel)}</option>`;
    selectEl.disabled = true;
    return;
  }
  selectEl.innerHTML = interfaces
    .map((i) => {
      const desc = i.description ? ` — ${i.description}` : '';
      return `<option value="${esc(i.name)}">${esc(i.name)}${esc(desc)}</option>`;
    })
    .join('');
  selectEl.disabled = false;
}

function updateSegmentIfaceHint() {
  const hint = document.getElementById('segment-iface-hint');
  const originName = document.getElementById('origin-iface-select').value;
  const destName = document.getElementById('destination-iface-select').value;
  const originIface = originInterfaces.find((i) => i.name === originName);
  const destIface = destinationInterfaces.find((i) => i.name === destName);
  if (!originIface || !destIface) {
    hint.textContent = '';
    return;
  }
  // Lado A é a ponta monitorada por convenção -- só cai pro lado B se A não
  // tiver status coletado ainda (ex: host sem sinal óptico coletado ainda).
  const monitoredSide = originIface.operstatus_itemid ? 'A' : 'B';
  hint.textContent = `Dados de tráfego/sinal virão do Lado ${monitoredSide}.`;
}

async function onSideHostChange(pointSelectEl, ifaceSelectEl, isOrigin) {
  const pointId = Number(pointSelectEl.value);
  const point = allPoints.find((p) => p.id === pointId);
  if (!point || !point.zabbix_hostid) {
    populateIfaceSelect(ifaceSelectEl, [], 'Host sem vínculo com o Zabbix');
    if (isOrigin) originInterfaces = []; else destinationInterfaces = [];
    updateSegmentIfaceHint();
    return;
  }
  ifaceSelectEl.disabled = true;
  ifaceSelectEl.innerHTML = '<option value="">Buscando interfaces…</option>';
  const interfaces = await fetchHostInterfaces(point.zabbix_hostid);
  if (isOrigin) originInterfaces = interfaces; else destinationInterfaces = interfaces;
  populateIfaceSelect(ifaceSelectEl, interfaces, 'Nenhuma interface monitorada encontrada');
  updateSegmentIfaceHint();
}

document.getElementById('origin-select').addEventListener('change', (e) => {
  onSideHostChange(e.target, document.getElementById('origin-iface-select'), true);
});
document.getElementById('destination-select').addEventListener('change', (e) => {
  onSideHostChange(e.target, document.getElementById('destination-iface-select'), false);
});
document.getElementById('origin-iface-select').addEventListener('change', updateSegmentIfaceHint);
document.getElementById('destination-iface-select').addEventListener('change', updateSegmentIfaceHint);

async function loadCircuits() {
  allCircuits = await api('/api/circuits');
  renderCircuitChips();
}

function renderCircuitChips() {
  const wrap = document.getElementById('circuits-chips');
  wrap.innerHTML = allCircuits.map((c) => `
    <div class="circuit-chip${c.id === selectedCircuitId ? ' selected' : ''}" data-id="${esc(c.id)}">${esc(c.name)}</div>
  `).join('');
  wrap.querySelectorAll('.circuit-chip').forEach((el) => {
    el.addEventListener('click', () => editCircuit(Number(el.dataset.id)));
  });
}

// Acha, entre as interfaces já resolvidas de um lado, qual bate com o
// itemid de status gravado no segmento -- é assim que a tela sabe qual
// interface pré-selecionar ao reabrir um circuito existente pra edição,
// já que o segmento guarda itemids, não o nome da interface escolhida.
// port_name (formato "IFACE_A ↔ IFACE_B") cobre o lado que não é o
// monitorado, e também circuitos antigos cadastrados manualmente antes
// dessa tela existir.
function resolveIfaceName(interfaces, itemid, portNameFallback) {
  const byItemid = itemid && interfaces.find((i) => i.operstatus_itemid === String(itemid));
  if (byItemid) return byItemid.name;
  if (portNameFallback && interfaces.some((i) => i.name === portNameFallback)) return portNameFallback;
  return '';
}

// Modal Lado A/B -- desfoca o fundo (backdrop-filter, ver CSS) em vez de
// competir por espaço permanente na tela com o mapa/lista de circuitos.
function openAbModal(title) {
  document.getElementById('ab-modal-title').textContent = title;
  document.getElementById('ab-modal-overlay').hidden = false;
}
function closeAbModal() {
  document.getElementById('ab-modal-overlay').hidden = true;
}
document.getElementById('ab-modal-close').addEventListener('click', closeAbModal);
document.getElementById('ab-modal-overlay').addEventListener('click', (e) => {
  if (e.target.id === 'ab-modal-overlay') closeAbModal();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && !document.getElementById('ab-modal-overlay').hidden) closeAbModal();
});

// Reseta os campos do modal pro estado "novo circuito" -- não abre o modal
// sozinho, quem chama decide (o botão abre na hora; loadPoints() só prepara
// o estado padrão de antemão pra abrir já populado na primeira vez).
function resetFormForNewCircuit() {
  selectedCircuitId = null;
  window.currentCircuit = null;
  renderCircuitChips();
  document.getElementById('segment-submit-btn').textContent = 'Criar circuito';
  document.getElementById('segment-warning').textContent = '';
  document.getElementById('circuit-name-input').value = '';
  setFormStatus('segment-status', '', false);
  const originSel = document.getElementById('origin-select');
  const destSel = document.getElementById('destination-select');
  originSel.selectedIndex = 0;
  destSel.selectedIndex = destSel.options.length > 1 ? 1 : 0;
  onSideHostChange(originSel, document.getElementById('origin-iface-select'), true);
  onSideHostChange(destSel, document.getElementById('destination-iface-select'), false);
  window.renderCircuitOnEditorMap(allCircuits, allPoints, null);
}
document.getElementById('new-circuit-btn').addEventListener('click', () => {
  resetFormForNewCircuit();
  openAbModal('Novo circuito');
});

// Carrega um circuito existente nos campos do formulário e no mapa -- usado
// tanto ao abrir o modal de edição quanto pra atualizar a tela depois de
// salvar (sem reabrir o modal nesse segundo caso, ver o submit handler).
async function loadCircuitIntoForm(circuitId) {
  selectedCircuitId = circuitId;
  // Recarrega a lista inteira (não só renderCircuitChips) -- o mapa desenha
  // TODOS os circuitos, então precisa dos segmentos atualizados de todo
  // mundo, não só do que está sendo editado agora.
  await loadCircuits();
  window.currentCircuit = await api(`/api/circuits/${circuitId}`);
  const segment = window.currentCircuit.segments[0];
  document.getElementById('segment-submit-btn').textContent = 'Salvar circuito';
  document.getElementById('circuit-name-input').value = window.currentCircuit.name || '';
  setFormStatus('segment-status', '', false);

  const originSel = document.getElementById('origin-select');
  const destSel = document.getElementById('destination-select');
  if (segment) {
    originSel.value = String(segment.origin_point_id);
    destSel.value = String(segment.destination_point_id);
  }
  await Promise.all([
    onSideHostChange(originSel, document.getElementById('origin-iface-select'), true),
    onSideHostChange(destSel, document.getElementById('destination-iface-select'), false),
  ]);

  if (segment) {
    const [ifaceAName, ifaceBName] = (segment.port_name || '').split('↔').map((s) => (s || '').trim());
    const originIfaceSel = document.getElementById('origin-iface-select');
    const destIfaceSel = document.getElementById('destination-iface-select');
    originIfaceSel.value = resolveIfaceName(originInterfaces, segment.zabbix_operstatus_itemid, ifaceAName);
    destIfaceSel.value = resolveIfaceName(destinationInterfaces, segment.zabbix_operstatus_itemid, ifaceBName);
    updateSegmentIfaceHint();
  }

  const pointIds = new Set(allPoints.map((p) => p.id));
  const broken = segment && (!pointIds.has(segment.origin_point_id) || !pointIds.has(segment.destination_point_id));
  document.getElementById('segment-warning').textContent = broken
    ? 'Esse circuito referencia um ponto que não existe mais — corrija ou recrie.'
    : '';

  window.renderCircuitOnEditorMap(allCircuits, allPoints, circuitId);
}

async function editCircuit(circuitId) {
  await loadCircuitIntoForm(circuitId);
  openAbModal('Editar circuito');
}

// Traça a rota pela estrada real via OSRM (servidor demo público, grátis,
// sem conta) -- chamado sozinho ao criar/mudar as pontas de um circuito, não
// é uma ação manual separada. O ajuste fino (arrastar no mini-mapa) é só pra
// corrigir os trechos onde a rota automática não bater com a realidade, não
// pra desenhar do zero. Lança em caso de falha -- quem chama decide o
// fallback (linha reta).
async function fetchRoadRoute(originLat, originLng, destLat, destLng) {
  const url = `https://router.project-osrm.org/route/v1/driving/${originLng},${originLat};${destLng},${destLat}?overview=simplified&geometries=geojson`;
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`OSRM HTTP ${resp.status}`);
  const data = await resp.json();
  if (data.code !== 'Ok' || !data.routes || !data.routes.length) {
    throw new Error(`OSRM: ${data.code || 'sem rota encontrada'}`);
  }
  // GeoJSON vem como [lng, lat]. As duas pontas da rota já são os próprios
  // hosts (origem/destino) -- só o miolo vira waypoint do segmento.
  return data.routes[0].geometry.coordinates.slice(1, -1).map(([lng, lat]) => ({ lat, lng }));
}

document.getElementById('segment-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const originId = Number(document.getElementById('origin-select').value);
  const destinationId = Number(document.getElementById('destination-select').value);

  if (!originId || !destinationId) {
    setFormStatus('segment-status', 'Escolha o host dos dois lados.', true);
    return;
  }
  if (originId === destinationId) {
    setFormStatus('segment-status', 'Lado A e Lado B não podem ser o mesmo host.', true);
    return;
  }

  const originIfaceName = document.getElementById('origin-iface-select').value;
  const destinationIfaceName = document.getElementById('destination-iface-select').value;
  const originIface = originInterfaces.find((i) => i.name === originIfaceName);
  const destinationIface = destinationInterfaces.find((i) => i.name === destinationIfaceName);
  if (!originIface || !destinationIface) {
    setFormStatus('segment-status', 'Escolha a interface dos dois lados antes de salvar.', true);
    return;
  }
  // Lado A é a ponta monitorada por convenção -- só cai pro lado B se A não
  // tiver status coletado ainda (ver updateSegmentIfaceHint).
  const monitored = originIface.operstatus_itemid ? originIface : destinationIface;

  const origin = allPoints.find((p) => p.id === originId);
  const destination = allPoints.find((p) => p.id === destinationId);
  const isNew = selectedCircuitId === null;
  const existingSegment = !isNew && window.currentCircuit?.segments?.[0];
  const endpointsChanged = !existingSegment
    || existingSegment.origin_point_id !== originId
    || existingSegment.destination_point_id !== destinationId;

  const submitBtn = document.getElementById('segment-submit-btn');
  setFormStatus('segment-status', '', false);

  let waypointIds = existingSegment ? (existingSegment.waypoint_ids || []) : [];
  if (endpointsChanged) {
    submitBtn.disabled = true;
    submitBtn.textContent = 'Traçando rota pela estrada…';
    try {
      const routePoints = await fetchRoadRoute(origin.lat, origin.lng, destination.lat, destination.lng);
      // route_point (não waypoint) -- geometria pura da linha, o mesmo tipo
      // usado no ajuste fino manual; 'waypoint' criaria marcador fantasma
      // de poste/caixa (bug já corrigido antes nesta sessão).
      const created = await Promise.all(routePoints.map((rp) => api('/api/points', {
        method: 'POST',
        body: JSON.stringify({ name: 'Trajeto', lat: rp.lat, lng: rp.lng, point_type: 'route_point' }),
      })));
      waypointIds = created.map((p) => p.id);
    } catch (err) {
      console.warn('Rota automática pela estrada falhou, criando linha reta', err);
      setFormStatus('segment-status', 'Rota automática indisponível — criado em linha reta; ajuste no mapa.', true);
      waypointIds = [];
    }
    submitBtn.disabled = false;
    submitBtn.textContent = isNew ? 'Criar circuito' : 'Salvar circuito';
  }

  const segmentBody = {
    order_index: 0,
    origin_point_id: originId,
    destination_point_id: destinationId,
    waypoint_ids: waypointIds,
    port_name: `${originIface.name} ↔ ${destinationIface.name}`,
    zabbix_operstatus_itemid: monitored.operstatus_itemid || null,
    zabbix_speed_itemid: monitored.speed_itemid || null,
    zabbix_throughput_in_itemid: monitored.throughput_in_itemid || null,
    zabbix_throughput_out_itemid: monitored.throughput_out_itemid || null,
    zabbix_optical_rx_itemid: monitored.optical_rx_itemid || null,
    zabbix_optical_tx_itemid: monitored.optical_tx_itemid || null,
    signal_warn_threshold_dbm: form.get('signal_warn_threshold_dbm') ? parseFloat(form.get('signal_warn_threshold_dbm')) : null,
  };
  // Nome manual é opcional -- em branco, cai no padrão "Lado A + Lado B".
  const customName = (form.get('circuit_name') || '').trim();
  const circuitName = customName || `${origin.name} + ${destination.name}`;

  try {
    if (isNew) {
      const circuit = await api('/api/circuits', { method: 'POST', body: JSON.stringify({ name: circuitName }) });
      await api(`/api/circuits/${circuit.id}/segments`, { method: 'POST', body: JSON.stringify(segmentBody) });
      await loadCircuitIntoForm(circuit.id);
    } else {
      await api(`/api/circuits/${selectedCircuitId}`, { method: 'PUT', body: JSON.stringify({ name: circuitName }) });
      await api(`/api/segments/${existingSegment.id}`, { method: 'PUT', body: JSON.stringify(segmentBody) });
      // Só limpa waypoints antigos se a rota foi refeita de verdade -- senão
      // waypointIds é a mesma lista de existingSegment e isso apagaria a
      // própria rota que acabou de ser salva.
      if (endpointsChanged) {
        const oldWaypointIds = existingSegment.waypoint_ids || [];
        for (const oldId of oldWaypointIds) {
          if (waypointIds.includes(oldId)) continue;
          try {
            await api(`/api/points/${oldId}`, { method: 'DELETE' });
          } catch (err) {
            console.warn(`Não foi possível remover o waypoint ${oldId} substituído`, err);
          }
        }
      }
      await loadCircuitIntoForm(selectedCircuitId);
    }
    setFormStatus('segment-status', 'Circuito salvo.', false);
    closeAbModal();
  } catch (err) {
    console.error('Falha ao salvar circuito', err);
    setFormStatus('segment-status', `Falha ao salvar: ${err.message}`, true);
  }
});

(async function init() {
  await loadPoints();
  await loadCircuits();
  resetFormForNewCircuit();
})();
