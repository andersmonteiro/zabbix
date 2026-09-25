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

function renderHosts(hosts) {
  const tbody = document.getElementById('hosts-tbody');
  tbody.innerHTML = hosts.map((h) => `
    <tr data-id="${esc(h.hostid)}">
      <td>${esc(h.host)}</td>
      <td>${esc(h.ip)}</td>
      <td>${esc(h.port)}</td>
      <td>${esc(h.vendor)}</td>
      <td>${esc(h.model)}</td>
      <td>${h.groups.map((g) => `<span class="badge">${esc(g)}</span>`).join(' ')}</td>
      <td>${esc(h.ssh_user)}</td>
      <td>${h.lat !== null && h.lng !== null ? `${esc(h.lat)}, ${esc(h.lng)}` : '—'}</td>
      <td>
        <button class="row-edit" data-id="${esc(h.hostid)}" type="button">Editar</button>
        <button class="row-delete" data-id="${esc(h.hostid)}" type="button">Remover</button>
      </td>
    </tr>
  `).join('');
  tbody.querySelectorAll('.row-delete').forEach((btn) => {
    btn.addEventListener('click', async () => {
      if (!confirm('Remover este host do Zabbix?')) return;
      try {
        await api(`/api/zabbix/hosts/${btn.dataset.id}`, { method: 'DELETE' });
        await loadHosts();
      } catch (err) {
        alert(`Falha ao remover: ${err.message}`);
      }
    });
  });
  tbody.querySelectorAll('.row-edit').forEach((btn) => {
    btn.addEventListener('click', () => {
      const host = allHosts.find((h) => String(h.hostid) === btn.dataset.id);
      if (host) openEditModal(host);
    });
  });
}

async function loadHosts() {
  allHosts = await api('/api/zabbix/hosts');
  renderHosts(allHosts);
}

async function loadGroups() {
  const groups = await api('/api/zabbix/host-groups');
  const select = document.getElementById('group-select');
  select.innerHTML = '<option value="">Selecione o grupo...</option>'
    + groups.map((g) => `<option value="${esc(g.groupid)}">${esc(g.name)}</option>`).join('');
}

document.getElementById('host-search').addEventListener('input', (e) => {
  const q = e.target.value.trim().toLowerCase();
  const filtered = q
    ? allHosts.filter((h) => [h.host, h.ip, ...h.groups].join(' ').toLowerCase().includes(q))
    : allHosts;
  renderHosts(filtered);
});

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
  try {
    if (editingHostId) {
      await api(`/api/zabbix/hosts/${editingHostId}`, { method: 'PUT', body: JSON.stringify(body) });
    } else {
      await api('/api/zabbix/hosts', { method: 'POST', body: JSON.stringify(body) });
    }
  } catch (err) {
    statusEl.textContent = `Falha ao salvar host: ${err.message}`;
    statusEl.style.color = '#e5484d';
    return;
  }
  modal.classList.remove('open');
  backdrop.classList.remove('open');
  await loadHosts();
});

(async function init() {
  await Promise.all([loadHosts(), loadGroups()]);
})();
