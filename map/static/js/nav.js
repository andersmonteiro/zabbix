(async function () {
  try {
    const resp = await fetch('/api/session');
    const data = await resp.json();
    const userEl = document.getElementById('nav-user');
    if (userEl && data.username) userEl.textContent = data.username;
    const avatarEl = document.getElementById('nav-avatar');
    if (avatarEl && data.username) avatarEl.textContent = data.username[0].toUpperCase();
  } catch (err) {
    console.error('Falha ao buscar sessão', err);
  }

  const logoutBtn = document.getElementById('nav-logout');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', async () => {
      await fetch('/api/logout', { method: 'POST' });
      window.location.href = '/login';
    });
  }
})();
