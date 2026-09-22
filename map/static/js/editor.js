let segmentLayersBySegmentId = {};

window.renderCircuitOnEditorMap = function renderCircuitOnEditorMap(circuit, points) {
  Object.values(segmentLayersBySegmentId).forEach((layer) => editorMap.removeLayer(layer));
  segmentLayersBySegmentId = {};

  const pointsById = Object.fromEntries(points.map((p) => [p.id, p]));

  circuit.segments.forEach((segment) => {
    const origin = pointsById[segment.origin_point_id];
    const dest = pointsById[segment.destination_point_id];
    if (!origin || !dest) return;
    const waypoints = segment.waypoint_ids.map((id) => pointsById[id]).filter(Boolean);
    const latlngs = [origin, ...waypoints, dest].map((p) => [p.lat, p.lng]);

    const line = L.polyline(latlngs, { color: '#3b7ef0', weight: 4 }).addTo(editorMap);
    segmentLayersBySegmentId[segment.id] = line;
  });

  if (circuit.segments.length > 0) {
    const bounds = L.featureGroup(Object.values(segmentLayersBySegmentId)).getBounds();
    if (bounds.isValid()) editorMap.fitBounds(bounds, { padding: [30, 30] });
  }
};

let editingSegmentId = null;

document.getElementById('edit-path-btn').addEventListener('click', () => {
  const circuit = window.currentCircuit;
  if (!circuit || circuit.segments.length === 0) return;
  const segment = circuit.segments[circuit.segments.length - 1]; // edits the most recently added segment
  const layer = segmentLayersBySegmentId[segment.id];
  if (!layer) return;

  if (editingSegmentId === segment.id) {
    // Already editing — save and exit
    layer.pm.disable();
    const latlngs = layer.getLatLngs();
    saveEditedPath(segment, latlngs);
    editingSegmentId = null;
    document.getElementById('edit-path-btn').textContent = 'Editar trajeto';
    return;
  }

  layer.pm.enable({ allowSelfIntersection: true, draggable: true });
  editingSegmentId = segment.id;
  document.getElementById('edit-path-btn').textContent = 'Salvar trajeto';
});

async function saveEditedPath(segment, latlngs) {
  // The first and last vertices are the origin/destination equipment points
  // (not editable — Leaflet-Geoman lets the user drag them visually, but we
  // only persist the middle vertices as the segment's waypoint_ids; moving
  // an equipment point's real location happens via the Pontos form instead).
  const middleLatLngs = latlngs.slice(1, -1);

  const newWaypoints = [];
  for (const ll of middleLatLngs) {
    const point = await api('/api/points', {
      method: 'POST',
      body: JSON.stringify({ name: 'Trajeto', lat: ll.lat, lng: ll.lng, point_type: 'waypoint' }),
    });
    newWaypoints.push(point.id);
  }

  await api(`/api/segments/${segment.id}`, {
    method: 'PUT',
    body: JSON.stringify({ waypoint_ids: newWaypoints }),
  });

  await selectCircuit(selectedCircuitId);
}
