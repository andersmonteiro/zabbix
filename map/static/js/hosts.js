function esc(str) {
  if (str === null || str === undefined) return '';
  return String(str).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

let allHosts = [];

async function api(path, options) {
  const resp = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`;
    try {
      const body = await resp.json();
      if (body && body.error) detail = body.error;
    } catch (err) { /* non-JSON error body */ }
    throw new Error(detail);
  }
  if (resp.status === 204) return null;
  return resp.json();
}

// Tri-state (true/false/null) -> pill de status, usado tanto pra SSH
// (ssh_last_ok) quanto SNMP (snmp_offline, invertido: null/false = ok).
function statusPill(label, state) {
  const cls = state === null || state === undefined ? 'unknown' : (state ? 'ok' : 'fail');
  const text = state === null || state === undefined ? label : (state ? `${label} OK` : `${label} Falha`);
  return `<span class="status-pill ${cls}">${esc(text)}</span>`;
}

function sshState(h) {
  return h.ssh_last_ok === null || h.ssh_last_ok === undefined ? null : h.ssh_last_ok;
}

function snmpState(h) {
  // snmp_offline: null = sem dado/não monitorado, true = offline, false = ok.
  if (h.snmp_offline === null || h.snmp_offline === undefined) return null;
  return !h.snmp_offline;
}

// Ids de host atualmente expandidos (mostrando o painel "Mais detalhes") --
// guardado fora do HTML pra sobreviver a um re-render (busca/filtro não deve
// fechar o que o operador já tinha aberto.
const expandedHosts = new Set();

function renderHosts(hosts) {
  const list = document.getElementById('hosts-list');
  if (hosts.length === 0) {
    list.innerHTML = '<div class="hosts-empty">Nenhum host encontrado.</div>';
    return;
  }
  list.innerHTML = hosts.map((h) => {
    const id = esc(h.hostid);
    const expanded = expandedHosts.has(String(h.hostid));
    const coords = h.lat !== null && h.lng !== null ? `${esc(h.lat)}, ${esc(h.lng)}` : '—';
    const sshWhen = h.ssh_last_checked_at ? new Date(h.ssh_last_checked_at).toLocaleString('pt-BR') : 'nunca testado';
    return `
    <div class="host-item${expanded ? ' expanded' : ''}" data-id="${id}">
      <div class="host-row" data-id="${id}" title="Clique para mais detalhes, botão direito para ações">
        <div class="host-col host-col-name" title="${esc(h.host)}">${esc(h.host)}</div>
        <div class="host-col" title="${esc(h.vendor)}">${esc(h.vendor) || '—'}</div>
        <div class="host-col" title="${esc(h.groups.join(', '))}">${esc(h.groups.join(', ')) || '—'}</div>
        <div class="host-col host-col-ip">${esc(h.ip) || '—'}</div>
        <div class="host-col">${statusPill('SSH', sshState(h))}</div>
        <div class="host-col">${statusPill('SNMP', snmpState(h))}</div>
        <button class="host-expand-btn" type="button" aria-label="Mais detalhes" title="Mais detalhes">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
        </button>
      </div>
      <div class="host-detail" ${expanded ? '' : 'hidden'}>
        <div><div class="host-detail-label">Modelo</div><div class="host-detail-value">${esc(h.model) || '—'}</div></div>
        <div><div class="host-detail-label">Usuário SSH</div><div class="host-detail-value">${esc(h.ssh_user) || '—'}</div></div>
        <div><div class="host-detail-label">Porta SSH</div><div class="host-detail-value">${esc(h.ssh_port) || '—'}</div></div>
        <div><div class="host-detail-label">Último teste SSH</div><div class="host-detail-value">${esc(sshWhen)}</div></div>
        <div><div class="host-detail-label">Comunidade SNMP</div><div class="host-detail-value">${esc(h.community) || '—'}</div></div>
        <div><div class="host-detail-label">Porta SNMP</div><div class="host-detail-value">${esc(h.port) || '—'}</div></div>
        <div><div class="host-detail-label">Coordenadas</div><div class="host-detail-value">${coords}</div></div>
        <div class="host-detail-actions">
          <button class="btn-secondary test-ssh" data-id="${id}" type="button">Testar SSH</button>
          <button class="btn-secondary test-snmp" data-id="${id}" type="button">Testar SNMP</button>
          <button class="btn-secondary edit" data-id="${id}" type="button">Editar</button>
          <button class="btn-secondary delete" data-id="${id}" type="button" style="color: var(--red);">Remover</button>
        </div>
      </div>
    </div>
  `;
  }).join('');

  list.querySelectorAll('.host-expand-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      toggleExpanded(btn.closest('.host-item').dataset.id);
    });
  });
  list.querySelectorAll('.host-row').forEach((row) => {
    row.addEventListener('click', () => toggleExpanded(row.dataset.id));
    row.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      openContextMenu(e.clientX, e.clientY, row.dataset.id);
    });
  });
  list.querySelectorAll('.delete').forEach((btn) => {
    btn.addEventListener('click', (e) => { e.stopPropagation(); deleteHost(btn.dataset.id); });
  });
  list.querySelectorAll('.test-ssh').forEach((btn) => {
    btn.addEventListener('click', (e) => { e.stopPropagation(); testSsh(btn.dataset.id, btn); });
  });
  list.querySelectorAll('.test-snmp').forEach((btn) => {
    btn.addEventListener('click', (e) => { e.stopPropagation(); testSnmp(btn.dataset.id, btn); });
  });
  list.querySelectorAll('.edit').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      const host = allHosts.find((h) => String(h.hostid) === btn.dataset.id);
      if (host) openEditModal(host);
    });
  });
}

function toggleExpanded(hostid) {
  const item = document.querySelector(`.host-item[data-id="${CSS.escape(hostid)}"]`);
  if (!item) return;
  const detail = item.querySelector('.host-detail');
  const nowExpanded = !item.classList.contains('expanded');
  item.classList.toggle('expanded', nowExpanded);
  detail.hidden = !nowExpanded;
  if (nowExpanded) expandedHosts.add(String(hostid));
  else expandedHosts.delete(String(hostid));
}

async function deleteHost(hostid) {
  if (!confirm('Remover este host do Zabbix?')) return;
  try {
    await api(`/api/zabbix/hosts/${hostid}`, { method: 'DELETE' });
    await loadHosts();
  } catch (err) {
    alert(`Falha ao remover: ${err.message}`);
  }
}

async function testSsh(hostid, btn) {
  const original = btn ? btn.textContent : null;
  if (btn) { btn.textContent = 'Testando...'; btn.disabled = true; }
  try {
    const result = await api(`/api/zabbix/hosts/${hostid}/test-ssh`, { method: 'POST' });
    alert(result.ok ? `OK: ${result.message}` : `Falhou: ${result.message}`);
  } catch (err) {
    alert(`Falha ao testar: ${err.message}`);
  } finally {
    if (btn) { btn.textContent = original; btn.disabled = false; }
    await loadHosts();
  }
}

async function testSnmp(hostid, btn) {
  const original = btn ? btn.textContent : null;
  if (btn) { btn.textContent = 'Testando...'; btn.disabled = true; }
  try {
    const result = await api(`/api/zabbix/hosts/${hostid}/test-snmp`, { method: 'POST' });
    alert(result.ok ? `OK: ${result.message}` : `Falhou: ${result.message}`);
  } catch (err) {
    alert(`Falha ao testar: ${err.message}`);
  } finally {
    if (btn) { btn.textContent = original; btn.disabled = false; }
  }
}

// Menu de clique-direito -- reusa as mesmas três ações já disponíveis no
// painel "Mais detalhes" (editar/testar SSH/remover), só que sem precisar
// expandir a linha primeiro.
const ctxMenu = document.getElementById('host-ctx-menu');
let ctxMenuHostId = null;

function openContextMenu(x, y, hostid) {
  ctxMenuHostId = hostid;
  ctxMenu.hidden = false;
  const { innerWidth, innerHeight } = window;
  const rect = ctxMenu.getBoundingClientRect();
  ctxMenu.style.left = `${Math.min(x, innerWidth - rect.width - 8)}px`;
  ctxMenu.style.top = `${Math.min(y, innerHeight - rect.height - 8)}px`;
}

function closeContextMenu() {
  ctxMenu.hidden = true;
  ctxMenuHostId = null;
}

document.addEventListener('click', (e) => {
  if (!ctxMenu.hidden && !ctxMenu.contains(e.target)) closeContextMenu();
});
document.addEventListener('scroll', closeContextMenu, true);

ctxMenu.querySelectorAll('button[data-action]').forEach((btn) => {
  btn.addEventListener('click', () => {
    const hostid = ctxMenuHostId;
    const action = btn.dataset.action;
    closeContextMenu();
    if (!hostid) return;
    if (action === 'edit') {
      const host = allHosts.find((h) => String(h.hostid) === hostid);
      if (host) openEditModal(host);
    } else if (action === 'test-ssh') {
      testSsh(hostid, null);
    } else if (action === 'test-snmp') {
      testSnmp(hostid, null);
    } else if (action === 'delete') {
      deleteHost(hostid);
    }
  });
});

async function loadHosts() {
  allHosts = await api('/api/zabbix/hosts');
  applyFilters();
}

let currentStatusFilter = 'all';

function applyFilters() {
  const q = document.getElementById('host-search').value.trim().toLowerCase();
  let filtered = q
    ? allHosts.filter((h) => [h.host, h.ip, ...h.groups].join(' ').toLowerCase().includes(q))
    : allHosts;
  if (currentStatusFilter === 'ssh-ok') filtered = filtered.filter((h) => h.ssh_last_ok === true);
  else if (currentStatusFilter === 'ssh-fail') filtered = filtered.filter((h) => h.ssh_last_ok === false);
  else if (currentStatusFilter === 'ssh-unknown') filtered = filtered.filter((h) => h.ssh_last_ok === null || h.ssh_last_ok === undefined);
  renderHosts(filtered);
}

document.getElementById('host-filter-pills').addEventListener('click', (e) => {
  const btn = e.target.closest('.filter-pill');
  if (!btn) return;
  document.querySelectorAll('.filter-pill').forEach((p) => p.classList.remove('active'));
  btn.classList.add('active');
  currentStatusFilter = btn.dataset.filter;
  applyFilters();
});

async function loadGroups() {
  const groups = await api('/api/zabbix/host-groups');
  const select = document.getElementById('group-select');
  select.innerHTML = '<option value="">Selecione o grupo...</option>'
    + groups.map((g) => `<option value="${esc(g.groupid)}">${esc(g.name)}</option>`).join('');
}

document.getElementById('host-search').addEventListener('input', applyFilters);

const modal = document.getElementById('host-modal');
const backdrop = document.getElementById('backdrop');
const modalTitle = document.getElementById('host-modal-title');
const submitBtn = document.getElementById('host-form-submit');

// null = criando um host novo; caso contrário, hostid do host sendo editado.
// Alterna o form entre POST /hosts e PUT /hosts/:id sem duplicar o modal.
let editingHostId = null;

function openModal() {
  modal.classList.add('open');
  backdrop.classList.add('open');
}

document.getElementById('new-host-btn').addEventListener('click', () => {
  editingHostId = null;
  document.getElementById('host-form').reset();
  document.getElementById('host-form-status').textContent = '';
  modalTitle.textContent = 'Novo host';
  submitBtn.textContent = 'Criar host';
  openModal();
});

function openEditModal(host) {
  editingHostId = host.hostid;
  const form = document.getElementById('host-form');
  form.reset();
  form.name.value = host.host || '';
  form.ip.value = host.ip || '';
  form.vendor.value = host.vendor || '';
  form.model.value = host.model || '';
  form.community.value = host.community || 'public';
  form.port.value = host.port || '161';
  form.ssh_user.value = host.ssh_user || '';
  form.ssh_port.value = host.ssh_port || '';
  form.lat.value = host.lat !== null && host.lat !== undefined ? host.lat : '';
  form.lng.value = host.lng !== null && host.lng !== undefined ? host.lng : '';
  // group_id e ssh_pass não voltam da API (host.get não devolve senha, e o
  // grupo é sempre o mesmo salvo se o operador não mexer) -- deixa em
  // branco; o backend só troca o que vier preenchido.
  document.getElementById('host-form-status').textContent = '';
  modalTitle.textContent = `Editar ${host.host}`;
  submitBtn.textContent = 'Salvar alterações';
  openModal();
}

backdrop.addEventListener('click', () => {
  modal.classList.remove('open');
  backdrop.classList.remove('open');
});

// Depois de salvar, testa SSH (só se uma credencial foi informada) e SNMP
// (sempre tem community/porta, mesmo que seja o default "public"/161) na
// hora -- é o "faz um teste rápido pra saber se tá acessível" pedido, em vez
// de precisar abrir a linha e clicar em "Testar SSH" manualmente depois.
async function runPostSaveChecks(hostid, hasSsh, statusEl) {
  statusEl.style.color = '';
  statusEl.textContent = 'Host salvo. Testando conectividade...';

  const [sshResult, snmpResult] = await Promise.all([
    hasSsh
      ? api(`/api/zabbix/hosts/${hostid}/test-ssh`, { method: 'POST' }).catch((err) => ({ ok: false, message: err.message }))
      : Promise.resolve(null),
    api(`/api/zabbix/hosts/${hostid}/test-snmp`, { method: 'POST' }).catch((err) => ({ ok: false, message: err.message })),
  ]);

  const parts = [];
  let allOk = true;
  if (sshResult) {
    parts.push(`SSH ${sshResult.ok ? 'OK' : 'falhou'}`);
    if (!sshResult.ok) allOk = false;
  } else {
    parts.push('SSH não configurado');
  }
  parts.push(`SNMP ${snmpResult.ok ? 'OK' : 'falhou'}`);
  if (!snmpResult.ok) allOk = false;

  statusEl.textContent = `Host salvo. ${parts.join(' · ')}.`;
  statusEl.style.color = allOk ? '#3ecf6a' : '#e5484d';
  statusEl.title = [sshResult ? sshResult.message : '', snmpResult.message].filter(Boolean).join(' | ');

  await loadHosts();
  if (allOk) {
    setTimeout(() => {
      modal.classList.remove('open');
      backdrop.classList.remove('open');
    }, 1800);
  }
}

document.getElementById('host-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const body = {
    name: form.get('name'),
    ip: form.get('ip'),
    group_id: form.get('group_id') || null,
    vendor: form.get('vendor') || null,
    model: form.get('model') || null,
    community: form.get('community') || null,
    port: form.get('port') || null,
    ssh_user: form.get('ssh_user') || null,
    ssh_pass: form.get('ssh_pass') || null,
    ssh_port: form.get('ssh_port') || null,
    lat: form.get('lat') || null,
    lng: form.get('lng') || null,
  };
  const statusEl = document.getElementById('host-form-status');
  const hasSsh = !!(form.get('ssh_user') || '').trim() || !!(allHosts.find((h) => String(h.hostid) === editingHostId)?.ssh_user);
  let hostid = editingHostId;
  try {
    if (editingHostId) {
      await api(`/api/zabbix/hosts/${editingHostId}`, { method: 'PUT', body: JSON.stringify(body) });
    } else {
      const result = await api('/api/zabbix/hosts', { method: 'POST', body: JSON.stringify(body) });
      hostid = result.hostid;
    }
  } catch (err) {
    statusEl.textContent = `Falha ao salvar host: ${err.message}`;
    statusEl.style.color = '#e5484d';
    return;
  }
  runPostSaveChecks(hostid, hasSsh, statusEl);
});

(async function init() {
  await Promise.all([loadHosts(), loadGroups()]);
})();
