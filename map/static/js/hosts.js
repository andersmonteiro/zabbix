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
      <td>${esc(h.community)}</td>
      <td>${esc(h.port)}</td>
      <td>${esc(h.vendor)}</td>
      <td>${esc(h.model)}</td>
      <td>${h.groups.map((g) => `<span class="badge">${esc(g)}</span>`).join(' ')}</td>
      <td>${esc(h.ssh_user)}</td>
      <td><button class="row-delete" data-id="${esc(h.hostid)}" type="button">Remover</button></td>
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
document.getElementById('new-host-btn').addEventListener('click', () => {
  document.getElementById('host-form').reset();
  document.getElementById('host-form-status').textContent = '';
  modal.classList.add('open');
  backdrop.classList.add('open');
});
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
    group_id: form.get('group_id'),
    vendor: form.get('vendor') || null,
    model: form.get('model') || null,
    community: form.get('community') || null,
    port: form.get('port') || null,
    ssh_user: form.get('ssh_user') || null,
    ssh_pass: form.get('ssh_pass') || null,
    ssh_port: form.get('ssh_port') || null,
  };
  const statusEl = document.getElementById('host-form-status');
  try {
    await api('/api/zabbix/hosts', { method: 'POST', body: JSON.stringify(body) });
  } catch (err) {
    statusEl.textContent = `Falha ao criar host: ${err.message}`;
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
