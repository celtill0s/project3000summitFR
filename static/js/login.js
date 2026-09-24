// Page de connexion : ouvre une session (cookie posé par le serveur) puis affiche la carte.
import { CSRF_HEADERS, clearPersonalCaches } from './session-utils.js';

const form = document.getElementById('login-form');
const status = document.getElementById('login-status');
const submit = document.getElementById('login-submit');

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  status.textContent = '';
  submit.disabled = true;
  try {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...CSRF_HEADERS },
      body: JSON.stringify({
        username: document.getElementById('login-username').value.trim(),
        password: document.getElementById('login-password').value
      })
    });
    if (res.ok) {
      // Rien du compte précédent ne doit rester dans le cache hors-ligne de cet appareil.
      await clearPersonalCaches();
      location.replace('/');
      return;
    }
    const body = await res.json().catch(() => ({}));
    status.textContent = res.status === 401 ? 'Identifiant ou mot de passe incorrect.'
      : res.status === 429 ? `Trop de tentatives : ${body.error || 'réessaie plus tard'}.`
      : `Connexion impossible (${body.error || 'erreur ' + res.status}).`;
    if (res.status === 401) {
      const pw = document.getElementById('login-password');
      pw.value = '';
      pw.focus();
    }
  } catch {
    status.textContent = 'Serveur injoignable : vérifie ta connexion.';
  } finally {
    submit.disabled = false;
  }
});
