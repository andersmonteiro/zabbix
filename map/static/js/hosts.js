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

// Tri-state (true/false/null) -> pill de status. Só a cor já diz tudo (ok
// /falha/sem teste) -- o texto fica só com o nome do protocolo, sem repetir
// "OK"/"Falha" que seria redundante com a própria cor.
function statusPill(label, state) {
  const cls = state === null || state === undefined ? 'unknown' : (state ? 'ok' : 'fail');
  return `<span class="status-pill ${cls}" data-proto="${label}">${esc(label)}</span>`;
}

function sshState(h) {
  return h.ssh_last_ok === null || h.ssh_last_ok === undefined ? null : h.ssh_last_ok;
}

function snmpState(h) {
  // snmp_offline: null = sem dado/não monitorado, true = offline, false = ok.
  if (h.snmp_offline === null || h.snmp_offline === undefined) return null;
  return !h.snmp_offline;
}

function renderHosts(hosts) {
  const list = document.getElementById('hosts-list');
  if (hosts.length === 0) {
    list.innerHTML = '<div class="hosts-empty">Nenhum host encontrado.</div>';
    return;
  }
  list.innerHTML = hosts.map((h) => {
    const id = esc(h.hostid);
    return `
    <div class="host-item" data-id="${id}">
      <div class="host-row" data-id="${id}" title="Clique para editar, botão direito para ações rápidas">
        <div class="host-col host-col-name" title="${esc(h.host)}">${esc(h.host)}</div>
        <div class="host-col" title="${esc(h.vendor)}">${esc(h.vendor) || '—'}</div>
        <div class="host-col" title="${esc(h.groups.join(', '))}">${esc(h.groups.join(', ')) || '—'}</div>
        <div class="host-col host-col-ip">${esc(h.ip) || '—'}</div>
        <div class="host-col">${statusPill('SSH', sshState(h))}</div>
        <div class="host-col">${statusPill('SNMP', snmpState(h))}</div>
        <button class="host-expand-btn" type="button" aria-label="Editar host" title="Editar host">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg>
        </button>
      </div>
    </div>
  `;
  }).join('');

  const openEdit = (hostid) => {
    const host = allHosts.find((h) => String(h.hostid) === hostid);
    if (host) openEditModal(host);
  };
  list.querySelectorAll('.host-expand-btn').forEach((btn) => {
    btn.addEventListener('click', (e) => {
      e.stopPropagation();
      openEdit(btn.closest('.host-item').dataset.id);
    });
  });
  list.querySelectorAll('.host-row').forEach((row) => {
    row.addEventListener('click', () => openEdit(row.dataset.id));
    row.addEventListener('contextmenu', (e) => {
      e.preventDefault();
      openContextMenu(e.clientX, e.clientY, row.dataset.id);
    });
  });

  autoTestVisibleHosts(hosts);
}

// Pill de status de um host específico, sem re-renderizar a lista inteira
// (evita perder scroll/seleção enquanto os testes automáticos vão chegando).
function updatePill(hostid, proto, ok) {
  const row = document.querySelector(`.host-row[data-id="${CSS.escape(hostid)}"]`);
  if (!row) return;
  const pill = row.querySelector(`.status-pill[data-proto="${proto}"]`);
  if (!pill) return;
  pill.className = `status-pill ${ok ? 'ok' : 'fail'}`;
}

// Testa SSH (só hosts com credencial já cadastrada) e SNMP (todos, já que
// community/porta sempre têm um valor) de cada host visível, automaticamente
// ao carregar a lista -- em vez de depender de alguém clicar "Testar" host
// por host. Concorrência limitada pra não abrir dezenas de conexões SSH/SNMP
// de uma vez só.
const AUTO_TEST_CONCURRENCY = 4;

async function autoTestVisibleHosts(hosts) {
  const queue = [];
  hosts.forEach((h) => {
    queue.push(async () => {
      try {
        const r = await api(`/api/zabbix/hosts/${h.hostid}/test-snmp`, { method: 'POST' });
        updatePill(h.hostid, 'SNMP', r.ok);
      } catch (err) { /* mantém o estado anterior se a chamada falhar */ }
    });
    if (h.ssh_user) {
      queue.push(async () => {
        try {
          const r = await api(`/api/zabbix/hosts/${h.hostid}/test-ssh`, { method: 'POST' });
          updatePill(h.hostid, 'SSH', r.ok);
        } catch (err) { /* idem */ }
      });
    }
  });

  let next = 0;
  async function worker() {
    while (next < queue.length) {
      const task = queue[next++];
      await task();
    }
  }
  await Promise.all(Array.from({ length: AUTO_TEST_CONCURRENCY }, worker));
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

// Re-teste manual avulso via menu de clique-direito -- atualiza só o pill
// daquele host (sem recarregar a lista inteira e sem re-disparar o teste
// automático dos outros hosts).
async function testSsh(hostid) {
  try {
    const result = await api(`/api/zabbix/hosts/${hostid}/test-ssh`, { method: 'POST' });
    updatePill(hostid, 'SSH', result.ok);
    if (!result.ok) alert(`SSH falhou: ${result.message}`);
  } catch (err) {
    alert(`Falha ao testar SSH: ${err.message}`);
  }
}

async function testSnmp(hostid) {
  try {
    const result = await api(`/api/zabbix/hosts/${hostid}/test-snmp`, { method: 'POST' });
    updatePill(hostid, 'SNMP', result.ok);
    if (!result.ok) alert(`SNMP falhou: ${result.message}`);
  } catch (err) {
    alert(`Falha ao testar SNMP: ${err.message}`);
  }
}

// Menu de clique-direito -- editar/testar SSH/testar SNMP/remover sem
// precisar abrir o modal de edição primeiro.
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
      testSsh(hostid);
    } else if (action === 'test-snmp') {
      testSnmp(hostid);
    } else if (action === 'delete') {
      deleteHost(hostid);
    }
  });
});

async function loadHosts() {
  allHosts = await api('/api/zabbix/hosts');
  applyFilters();
}

function applyFilters() {
  const q = document.getElementById('host-search').value.trim().toLowerCase();
  const filtered = q
    ? allHosts.filter((h) => [h.host, h.ip, ...h.groups].join(' ').toLowerCase().includes(q))
    : allHosts;
  renderHosts(filtered);
}

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

// Mesmo intervalo de 30s das outras telas. O modal de editar host é um
// overlay independente da lista (os valores já estão nos campos quando
// abre), então recarregar a lista por baixo não afeta um cadastro em
// andamento -- diferente do editor de trajeto em Circuitos, que de fato
// pausa durante a edição.
const HOSTS_REFRESH_INTERVAL_MS = 30000;
setInterval(loadHosts, HOSTS_REFRESH_INTERVAL_MS);
