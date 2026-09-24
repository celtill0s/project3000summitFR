// Compte connecté : nom et rôle, changement de mot de passe, déconnexion, et bandeau quand un
// admin consulte l'espace d'un autre utilisateur.
import { session } from './store.js';
import { apiPost } from './api.js';
import { CSRF_HEADERS, clearPersonalCaches } from './session-utils.js';
import { nativeApp } from './app-bridge.js';

const ROLE_LABELS = { admin: 'administrateur', member: 'membre', guest: 'invité' };

async function logout() {
  if (!confirm('Se déconnecter ?')) return;
  try {
    await fetch('/api/logout', { method: 'POST', headers: CSRF_HEADERS });
  } catch { /* hors-ligne : la session expirera d'elle-même côté serveur */ }
  await clearPersonalCaches();
  location.replace('/login');
}

function initPasswordDialog() {
  const dialog = document.getElementById('password-dialog');
  const form = document.getElementById('password-form');
  const status = document.getElementById('pw-status');
  const fields = ['pw-current', 'pw-new', 'pw-confirm'].map(id => document.getElementById(id));
  const close = () => { dialog.hidden = true; };

  document.getElementById('account-password').addEventListener('click', () => {
    fields.forEach(f => { f.value = ''; });
    status.textContent = '';
    status.classList.remove('ok');
    dialog.hidden = false;
    fields[0].focus();
  });
  document.getElementById('pw-cancel').addEventListener('click', close);
  dialog.addEventListener('click', (e) => { if (e.target === dialog) close(); });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !dialog.hidden) close(); });

  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const [current, next, confirmation] = fields.map(f => f.value);
    status.classList.remove('ok');
    if (next !== confirmation) {
      status.textContent = 'Les deux nouveaux mots de passe diffèrent.';
      return;
    }
    try {
      await apiPost('/api/me/password', { current, new: next });
      status.textContent = 'Mot de passe changé. Tes autres appareils devront se reconnecter.';
      status.classList.add('ok');
      setTimeout(close, 1800);
    } catch (err) {
      status.textContent = `Échec : ${err.message}.`;
    }
  });
}

export function initAccount() {
  document.getElementById('account-name').textContent =
    `👤 ${session.me.username} · ${ROLE_LABELS[session.me.role] || session.me.role}`;
  document.getElementById('account-bar').hidden = false;
  // Dans l'appli Android, la déconnexion passe par son icône native « porte de sortie ».
  const logoutBtn = document.getElementById('account-logout');
  logoutBtn.hidden = !!nativeApp;
  logoutBtn.addEventListener('click', logout);
  if (session.viewingOther) {
    document.getElementById('space-banner-name').textContent = session.space;
    document.getElementById('space-banner').hidden = false;
  }
  initPasswordDialog();
}
