// Panneau ⚙ Paramètres (à droite) : compte (rempli par account.js), filtres d'affichage (puces
// rendues par sidebar.js), fond de carte et calques (traces GPX, pentes).
import { BASE_LAYER_NAMES, getBaseLayer, isOverlayVisible, setBaseLayer, setOverlayVisible } from './map.js';
import { escapeHtml } from './util.js';

function renderBaseLayerOptions() {
  const container = document.getElementById('base-layer-options');
  const current = getBaseLayer();
  container.innerHTML = BASE_LAYER_NAMES.map(name => `
    <label class="settings-check"><input type="radio" name="base-layer" value="${escapeHtml(name)}"${name === current ? ' checked' : ''}> ${escapeHtml(name)}</label>`).join('');
  container.querySelectorAll('input').forEach(input => {
    input.addEventListener('change', () => { if (input.checked) setBaseLayer(input.value); });
  });
}

function bindOverlay(id, name) {
  const input = document.getElementById(id);
  input.checked = isOverlayVisible(name);
  input.addEventListener('change', () => setOverlayVisible(name, input.checked));
}

export function initSettings() {
  const panel = document.getElementById('settings-panel');
  const openBtn = document.getElementById('settings-open');
  const setOpen = (open) => {
    panel.hidden = !open;
    openBtn.setAttribute('aria-expanded', String(open));
    openBtn.classList.toggle('active', open);
  };
  openBtn.addEventListener('click', () => setOpen(panel.hidden));
  document.getElementById('settings-close').addEventListener('click', () => setOpen(false));
  document.addEventListener('keydown', (e) => {
    // Échap ferme d'abord les fenêtres ouvertes par-dessus (mot de passe, utilisateurs…).
    if (e.key === 'Escape' && !panel.hidden && !document.querySelector('.modal:not([hidden]), #admin-view:not([hidden])')) setOpen(false);
  });
  renderBaseLayerOptions();
  bindOverlay('overlay-gpx', 'gpx');
  bindOverlay('overlay-slopes', 'slopes');
}
