let segmentLayersBySegmentId = {};

// Desenha TODOS os circuitos cadastrados de uma vez (o backbone inteiro
// continua visível mesmo enquanto você edita/cria outro) -- o circuito
// identificado por highlightCircuitId entra em destaque (verde, mais
// grosso); os demais ficam num azul apagado, só de contexto. Sem nenhum
// circuito cadastrado ainda, o mapa fica genuinamente vazio -- não é bug.
window.renderCircuitOnEditorMap = function renderCircuitOnEditorMap(circuits, points, highlightCircuitId) {
  Object.values(segmentLayersBySegmentId).forEach((layer) => editorMap.removeLayer(layer));
  segmentLayersBySegmentId = {};

  const pointsById = Object.fromEntries(points.map((p) => [p.id, p]));
  const highlightLayers = [];

  circuits.forEach((circuit) => {
    const isHighlighted = circuit.id === highlightCircuitId;
    (circuit.segments || []).forEach((segment) => {
      const origin = pointsById[segment.origin_point_id];
      const dest = pointsById[segment.destination_point_id];
      if (!origin || !dest) return;
      const waypoints = (segment.waypoint_ids || []).map((id) => pointsById[id]).filter(Boolean);
      const latlngs = [origin, ...waypoints, dest].map((p) => [p.lat, p.lng]);

      const line = L.polyline(latlngs, isHighlighted
        ? { color: '#91dc0a', weight: 5 }
        : { color: '#3b7ef0', weight: 3, opacity: 0.55 }).addTo(editorMap);
      segmentLayersBySegmentId[segment.id] = line;
      if (isHighlighted) highlightLayers.push(line);
    });
  });

  // Dá zoom só no circuito em destaque quando existe um; sem destaque (ex:
  // formulário de "novo circuito" aberto), mostra o backbone inteiro. Com um
  // circuito em destaque, o cartão de legenda vai ocupar uma faixa de
  // ~340px na direita -- mais padding aí evita que a própria linha
  // destacada fique escondida atrás do cartão.
  const boundsSource = highlightLayers.length > 0 ? highlightLayers : Object.values(segmentLayersBySegmentId);
  if (boundsSource.length > 0) {
    const bounds = L.featureGroup(boundsSource).getBounds();
    if (bounds.isValid()) {
      const padding = highlightLayers.length > 0
        ? { paddingTopLeft: [30, 30], paddingBottomRight: [350, 30] }
        : { padding: [30, 30] };
      editorMap.fitBounds(bounds, padding);
    }
  }
};

window.closeCircuitLegend = function closeCircuitLegend() {
  document.getElementById('circuit-legend-card').hidden = true;
};
document.getElementById('circuit-legend-close').addEventListener('click', () => window.closeCircuitLegend());

// Legenda do circuito selecionado -- um cartão fixo encostado na direita do
// mapa (não um popup Leaflet preso às coordenadas do trecho, por pedido
// explícito: tampava a linha e pulava de lugar a cada pan/zoom). Selecionar
// um circuito dá zoom nele (ver renderCircuitOnEditorMap) e o cartão mostra
// lado A/B, status, capacidade, throughput e sinal óptico ao lado do mapa.
window.showCircuitLegend = function showCircuitLegend(circuit, points, liveSegment) {
  const segment = circuit.segments && circuit.segments[0];
  if (!segment) {
    window.closeCircuitLegend();
    return;
  }

  const pointsById = Object.fromEntries(points.map((p) => [p.id, p]));
  const origin = pointsById[segment.origin_point_id];
  const dest = pointsById[segment.destination_point_id];
  if (!origin || !dest) {
    window.closeCircuitLegend();
    return;
  }

  const [ifaceA, ifaceB] = (segment.port_name || '').split('↔').map((s) => (s || '').trim());
  // >=1000 Mbps mostra em Gbps (40000 Mbps lido como "40 Gbps" é bem mais
  // direto que forçar Mbps pra capacidades de link grandes).
  const fmtMbps = (v) => {
    if (v === null || v === undefined) return '—';
    return v >= 1000 ? `${(v / 1000).toFixed(1)} Gbps` : `${v.toFixed(1)} Mbps`;
  };
  const fmtDbm = (v) => (v === null || v === undefined ? '—' : `${v.toFixed(1)} dBm`);

  document.getElementById('circuit-legend-content').innerHTML = `
    <div class="circuit-legend">
      <div class="cl-title">${esc(circuit.name)}</div>
      <div class="cl-row"><span>Status</span><strong>${esc(liveSegment ? liveSegment.status : '—')}</strong></div>
      <div class="cl-sides">
        <div class="cl-side"><span>Lado A</span><strong>${esc(origin.name)}</strong><small>${esc(ifaceA || '—')}</small></div>
        <div class="cl-side"><span>Lado B</span><strong>${esc(dest.name)}</strong><small>${esc(ifaceB || '—')}</small></div>
      </div>
      <div class="cl-section-label">Capacidade</div>
      <div class="cl-row"><span>Link</span><strong>${esc(liveSegment ? fmtMbps(liveSegment.speed_mbps) : '—')}</strong></div>

      <div class="cl-section-label">Tráfego</div>
      <div class="cl-row"><span>Download</span><strong>${esc(liveSegment ? fmtMbps(liveSegment.throughput_in_mbps) : '—')}</strong></div>
      <div class="cl-row"><span>Upload</span><strong>${esc(liveSegment ? fmtMbps(liveSegment.throughput_out_mbps) : '—')}</strong></div>

      <div class="cl-section-label">Sinal óptico</div>
      <div class="cl-row"><span>RX</span><strong>${esc(liveSegment ? fmtDbm(liveSegment.optical_rx_dbm) : '—')}</strong></div>
      <div class="cl-row"><span>TX</span><strong>${esc(liveSegment ? fmtDbm(liveSegment.optical_tx_dbm) : '—')}</strong></div>
    </div>
  `;
  document.getElementById('circuit-legend-card').hidden = false;
};

let editingSegmentId = null;

document.getElementById('edit-path-btn').addEventListener('click', async () => {
  const circuit = window.currentCircuit;
  if (!circuit || circuit.segments.length === 0) return;
  const segment = circuit.segments[circuit.segments.length - 1]; // edits the most recently added segment
  const layer = segmentLayersBySegmentId[segment.id];
  if (!layer) return;

  if (editingSegmentId === segment.id) {
    // Already editing — save and exit
    layer.pm.disable();
    const latlngs = layer.getLatLngs();
    editingSegmentId = null;
    await saveEditedPath(segment, latlngs);
    document.getElementById('edit-path-btn').textContent = 'Editar trajeto';
    return;
  }

  layer.pm.enable({ allowSelfIntersection: true, draggable: true });
  editingSegmentId = segment.id;
  document.getElementById('edit-path-btn').textContent = 'Salvar trajeto';
});

// Reencaixa o traçado desenhado à mão na rua/estrada real mais próxima --
// passa TODOS os vértices (incluindo os que o operador acabou de arrastar)
// pro OSRM como pontos de passagem obrigatórios, na ordem, e usa a geometria
// de rua que ele devolve entre eles. Assim o ajuste manual continua servindo
// pra corrigir a ROTA (por onde passar), mas o traçado final sempre gruda na
// via real, em vez de ficar em linha reta entre os pontos arrastados.
async function snapPathToRoad(latlngs) {
  if (latlngs.length < 2) return latlngs;
  const coordsParam = latlngs.map((ll) => `${ll.lng},${ll.lat}`).join(';');
  const url = `https://router.project-osrm.org/route/v1/driving/${coordsParam}?overview=simplified&geometries=geojson`;
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`OSRM HTTP ${resp.status}`);
  const data = await resp.json();
  if (data.code !== 'Ok' || !data.routes || !data.routes.length) {
    throw new Error(`OSRM: ${data.code || 'sem rota encontrada'}`);
  }
  return data.routes[0].geometry.coordinates.map(([lng, lat]) => L.latLng(lat, lng));
}

async function saveEditedPath(segment, latlngs) {
  const btn = document.getElementById('edit-path-btn');
  let snappedLatLngs = latlngs;
  try {
    btn.textContent = 'Encaixando na estrada…';
    snappedLatLngs = await snapPathToRoad(latlngs);
  } catch (err) {
    // Sem estrada encontrada (área rural sem cobertura OSM, ou OSRM fora do
    // ar) -- mantém exatamente o traçado desenhado à mão em vez de travar o
    // salvamento.
    console.warn('Encaixe na estrada falhou, mantendo o traçado desenhado manualmente', err);
  }

  // The first and last vertices are the origin/destination equipment points
  // (not editable — Leaflet-Geoman lets the user drag them visually, but we
  // only persist the middle vertices as the segment's waypoint_ids; moving
  // an equipment point's real location happens via the Pontos form instead).
  const middleLatLngs = snappedLatLngs.slice(1, -1);

  // Captured BEFORE the segment is repointed: each save used to mint a fresh
  // waypoint Point per vertex and abandon the previous ones, and since
  // build_map_state returns every point regardless of whether any segment still
  // references it, those orphans piled up as permanent grey dots on the live
  // map. Origin/destination points are never in waypoint_ids, so they are safe.
  const previousWaypointIds = (segment.waypoint_ids || []).slice();

  const newWaypoints = [];
  for (const ll of middleLatLngs) {
    // route_point (não waypoint) -- geometria pura da linha, o mesmo tipo
    // usado no traçado automático ao criar um circuito; 'waypoint' cria um
    // marcador visível de poste/caixa (o mesmo bug de "marcador fantasma"
    // já corrigido no fluxo de criação, reproduzido aqui até agora).
    const point = await api('/api/points', {
      method: 'POST',
      body: JSON.stringify({ name: 'Trajeto', lat: ll.lat, lng: ll.lng, point_type: 'route_point' }),
    });
    newWaypoints.push(point.id);
  }

  await api(`/api/segments/${segment.id}`, {
    method: 'PUT',
    body: JSON.stringify({ waypoint_ids: newWaypoints }),
  });

  // Only after the segment no longer references them. A failure here (e.g. the
  // point is still used by another segment -> 409) is logged and skipped: the
  // path itself is already saved, so it must not abort the rest of the flow.
  for (const oldId of previousWaypointIds) {
    if (newWaypoints.includes(oldId)) continue;
    try {
      await api(`/api/points/${oldId}`, { method: 'DELETE' });
    } catch (err) {
      console.warn(`Não foi possível remover o waypoint ${oldId} substituído`, err);
    }
  }

  await loadCircuitIntoForm(selectedCircuitId);
}
