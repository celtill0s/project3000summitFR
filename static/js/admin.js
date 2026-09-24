// Gestion des utilisateurs (administrateurs uniquement) : création, rôle, mot de passe,
// suppression, et consultation de l'espace d'un membre. Le serveur vérifie lui-même que
// l'appelant est administrateur : cette vue n'est qu'une interface.
import { session } from './store.js';
import { apiDelete, apiGet, apiPost } from './api.js';
import { escapeHtml } from './util.js';

const ROLES = [['member', 'Membre'], ['guest', 'Invité'], ['admin', 'Administrateur']];

// Mot de passe provisoire lisible (sans caractères ambigus comme l/1/O/0), tiré au hasard.
function randomPassword(length = 14) {
  const alphabet = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  const bytes = crypto.getRandomValues(new Uint8Array(length));
  return [...bytes].map(b => alphabet[b % alphabet.length]).join('');
}

function statsText(u) {
  if (u.role === 'guest') return 'catalogue seul';
  const plural = (n, word) => `${n} ${word}${n > 1 ? 's' : ''}`;
  return `${plural(u.done, 'sommet')} fait${u.done > 1 ? 's' : ''} · ${plural(u.photos, 'photo')} · ${u.gpx} GPX`;
}

function userRowHtml(u) {
  const me = u.username === session.me.username;
  const options = ROLES.map(([value, label]) =>
    `<option value="${value}"${value === u.role ? ' selected' : ''}>${label}</option>`).join('');
  return `<div class="admin-user" data-user="${escapeHtml(u.username)}">
    <div class="admin-user-name">${escapeHtml(u.username)}${me ? ' <span class="admin-me">(toi)</span>' : ''}
      <div class="admin-user-stats">${escapeHtml(statsText(u))}</div></div>
    <select class="admin-role" aria-label="Rôle de ${escapeHtml(u.username)}">${options}</select>
    <div class="admin-actions">
      ${u.role !== 'guest' && !me ? '<button type="button" class="btn-secondary admin-view-space">👁 Voir son espace</button>' : ''}
      <button type="button" class="btn-secondary admin-reset">🔑 Nouveau mot de passe</button>
      ${me ? '' : '<button type="button" class="btn-danger admin-delete">Supprimer</button>'}
    </div>
  </div>`;
}

async function loadUsers() {
  const container = document.getElementById('admin-users');
  const status = document.getElementById('admin-list-status');
  status.textContent = '';
  try {
    const { users } = await apiGet('/api/admin/users');
    container.innerHTML = users.map(userRowHtml).join('');
  } catch (err) {
    status.textContent = `Impossible de charger les comptes : ${err.message}.`;
    return;
  }
  container.querySelectorAll('.admin-user').forEach(row => {
    const user = row.dataset.user;
    const path = `/api/admin/users/${encodeURIComponent(user)}`;
    row.querySelector('.admin-role').addEventListener('change', async (e) => {
      try {
        await apiPost(`${path}/role`, { role: e.target.value });
      } catch (err) {
        alert(`Rôle non modifié : ${err.message}.`);
      }
      loadUsers();
    });
    row.querySelector('.admin-view-space')?.addEventListener('click', () => {
      location.href = `/?space=${encodeURIComponent(user)}`;
    });
    row.querySelector('.admin-reset').addEventListener('click', async () => {
      const pw = prompt(`Nouveau mot de passe pour « ${user} » (10 caractères minimum).\nNote-le pour le lui transmettre :`, randomPassword());
      if (!pw) return;
      try {
        await apiPost(`${path}/password`, { password: pw });
        alert(`Mot de passe de « ${user} » changé. Ses sessions ouvertes ont été fermées.`);
      } catch (err) {
        alert(`Mot de passe non modifié : ${err.message}.`);
      }
    });
    row.querySelector('.admin-delete')?.addEventListener('click', async () => {
      const typed = prompt(`Supprimer « ${user} » et TOUTES ses données (photos, traces GPX, commentaires) ?\nC'est définitif. Tape son identifiant pour confirmer :`);
      if (typed === null) return;
      if (typed.trim() !== user) {
        alert('Identifiant différent : rien n\'a été supprimé.');
        return;
      }
      try {
        await apiDelete(path);
      } catch (err) {
        alert(`Suppression impossible : ${err.message}.`);
      }
      loadUsers();
    });
  });
}

export function initAdmin() {
  if (session.me.role !== 'admin') return;
  const view = document.getElementById('admin-view');
  const openBtn = document.getElementById('admin-open');
  const close = () => { view.hidden = true; };
  openBtn.hidden = false;
  openBtn.addEventListener('click', () => {
    view.hidden = false;
    loadUsers();
  });
  document.getElementById('admin-view-close').addEventListener('click', close);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !view.hidden) close(); });

  const form = document.getElementById('admin-create');
  const status = document.getElementById('admin-create-status');
  document.getElementById('new-password-generate').addEventListener('click', () => {
    document.getElementById('new-password').value = randomPassword();
  });
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const username = document.getElementById('new-username').value.trim().toLowerCase();
    const password = document.getElementById('new-password').value;
    status.classList.remove('ok');
    try {
      await apiPost('/api/admin/users', { username, password, role: document.getElementById('new-role').value });
      status.textContent = `Compte « ${username} » créé. Transmets-lui son mot de passe provisoire : ${password}`;
      status.classList.add('ok');
      form.reset();
      loadUsers();
    } catch (err) {
      status.textContent = `Création impossible : ${err.message}.`;
    }
  });
}
