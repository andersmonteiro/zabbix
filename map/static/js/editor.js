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
        ? { color: '#3ecf6a', weight: 5, className: 'circuit-line-highlighted' }
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

  // Cada lado tem sua própria interface, com seus próprios contadores --
  // um problema (sinal ruim, erro) pode aparecer só de um lado, então os
  // dois ganham seu próprio bloco de dados em vez de um valor só.
  const sideBlock = (label, pointName, ifaceName, status, speedMbps, inMbps, outMbps, rxDbm, txDbm) => `
    <div class="cl-section-label">Lado ${label}</div>
    <div class="cl-side">
      <strong>${esc(pointName)}</strong>
      <small>${esc(ifaceName || '—')}</small>
    </div>
    <div class="cl-row"><span>Status</span><strong>${esc(liveSegment ? status : '—')}</strong></div>
    <div class="cl-row"><span>Capacidade</span><strong>${esc(liveSegment ? fmtMbps(speedMbps) : '—')}</strong></div>
    <div class="cl-row"><span>Download</span><strong>${esc(liveSegment ? fmtMbps(inMbps) : '—')}</strong></div>
    <div class="cl-row"><span>Upload</span><strong>${esc(liveSegment ? fmtMbps(outMbps) : '—')}</strong></div>
    <div class="cl-row"><span>Sinal RX</span><strong>${esc(liveSegment ? fmtDbm(rxDbm) : '—')}</strong></div>
    <div class="cl-row"><span>Sinal TX</span><strong>${esc(liveSegment ? fmtDbm(txDbm) : '—')}</strong></div>
  `;

  document.getElementById('circuit-legend-content').innerHTML = `
    <div class="circuit-legend">
      <div class="cl-title">${esc(circuit.name)}</div>
      ${sideBlock(
        'A', origin.name, ifaceA,
        liveSegment && liveSegment.status, liveSegment && liveSegment.speed_mbps,
        liveSegment && liveSegment.throughput_in_mbps, liveSegment && liveSegment.throughput_out_mbps,
        liveSegment && liveSegment.optical_rx_dbm, liveSegment && liveSegment.optical_tx_dbm,
      )}
      ${sideBlock(
        'B', dest.name, ifaceB,
        liveSegment && liveSegment.status_b, liveSegment && liveSegment.speed_mbps_b,
        liveSegment && liveSegment.throughput_in_mbps_b, liveSegment && liveSegment.throughput_out_mbps_b,
        liveSegment && liveSegment.optical_rx_dbm_b, liveSegment && liveSegment.optical_tx_dbm_b,
      )}
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
  attachLiveSnap(layer);
  editingSegmentId = segment.id;
  document.getElementById('edit-path-btn').textContent = 'Salvar trajeto';
});

// Encaixe "ao vivo" durante o arrasto -- em vez de só ajustar quando o
// operador solta o vértice (pm:edit, no fim de qualquer edição), escuta
// pm:markerdrag (dispara continuamente enquanto o vértice se move) e
// faz o snap pela via mais próxima com um pequeno debounce. Sem o debounce
// seria uma chamada de rede por pixel de movimento -- lento e sobrecarrega
// o servidor OSRM público sem necessidade; com ele, o traçado vai se
// "colando" na estrada pouco depois de cada pausa no arrasto, em vez de só
// no final.
const DRAG_SNAP_DEBOUNCE_MS = 180;
let dragSnapTimer = null;

function attachLiveSnap(layer) {
  layer.off('pm:markerdrag', onLiveDrag); // evita acumular o listener se chamado mais de uma vez na mesma layer
  layer.on('pm:markerdrag', onLiveDrag);
}

function onLiveDrag(e) {
  const marker = e.markerEvent ? e.markerEvent.target : e.target;
  if (!marker || typeof marker.setLatLng !== 'function') return;
  clearTimeout(dragSnapTimer);
  dragSnapTimer = setTimeout(async () => {
    const current = marker.getLatLng();
    try {
      const snapped = await snapVertexToRoad(current);
      if (snapped.lat !== current.lat || snapped.lng !== current.lng) {
        marker.setLatLng(snapped);
      }
    } catch (err) {
      // Falha de rede/OSRM fora do ar durante o arrasto -- não interrompe a
      // edição, o encaixe final ao soltar (saveEditedPath) ainda tenta de novo.
    }
  }, DRAG_SNAP_DEBOUNCE_MS);
}

// "Laço magnético" (mesma ideia do Photoshop: o traçado vai se colando à
// borda mais próxima enquanto o operador desenha, não recalculando um
// caminho ótimo do zero) -- cada vértice arrastado é puxado individualmente
// pra via mais próxima via OSRM Nearest, dentro de SNAP_RADIUS_METERS.
//
// Chegou aqui depois de duas tentativas que não funcionavam:
// - Route (/route/v1/driving, todos os vértices como waypoints
//   obrigatórios): calcula o MELHOR CAMINHO entre os extremos, e numa área
//   com malha viária esparsa (zona rural da Amazônia) isso às vezes
//   "inventava" uma ligação reta entre dois pontos sem via real nenhuma
//   entre eles -- exatamente o bug relatado.
// - Match (/match/v1/driving, map matching): pensado pra um RASTRO GPS
//   denso (ponto a cada poucos metros); com só 2-4 vértices bem espaçados
//   (o caso normal aqui -- origem, um ou dois pontos arrastados, destino)
//   ele simplesmente devolve "NoMatch" na maioria das vezes, confirmado
//   testando contra a API pública.
// Nearest resolve ponto a ponto, sem tentar inferir rota nenhuma entre
// eles -- exatamente "colar esse vértice na borda mais próxima", e nada
// além disso. Vértice sem via a menos de SNAP_RADIUS_METERS fica exatamente
// onde o operador arrastou (ex: enlace de rádio sobre mata, sem estrada
// nenhuma por baixo) em vez de ser puxado pra longe por engano.
const SNAP_RADIUS_METERS = 60;

async function snapVertexToRoad(ll) {
  const url = `https://router.project-osrm.org/nearest/v1/driving/${ll.lng},${ll.lat}?number=1`;
  const resp = await fetch(url);
  if (!resp.ok) throw new Error(`OSRM HTTP ${resp.status}`);
  const data = await resp.json();
  const nearest = data.code === 'Ok' ? data.waypoints?.[0] : null;
  if (!nearest || nearest.distance > SNAP_RADIUS_METERS) return ll;
  const [lng, lat] = nearest.location;
  return L.latLng(lat, lng);
}

async function snapPathToRoad(latlngs) {
  return Promise.all(latlngs.map((ll) => snapVertexToRoad(ll).catch(() => ll)));
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
