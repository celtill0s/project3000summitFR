// Vue « crampons + piolet » (sommets avec un champ crampon dans le catalogue).
import { escapeHtml } from './util.js';
import { PEAKS } from './store.js';

// --- Vue "crampons + piolet" (POC) : sommets où une extension crampons+piolet à pied (pas de
// corde, pas de glace verticale) est documentée hors de la fenêtre de randonnée normale, avec
// le grade alpin (confirmé sur camptocamp.org, ou estimé sinon). Données : champ "crampon" des
// sommets concernés dans static/mountains.json (validé par tests/test_catalog.py).
function cramponRowHtml(p) {
  const c = p.crampon;
  const gradeClass = c.confirmed ? 'confirmed' : 'estimated';
  return `<div class="crampon-row">
    <div class="name">${escapeHtml(p.name)}<div class="note" style="margin-top:2px;">${escapeHtml(p.altitude_m)} m · ${escapeHtml(p.region)} / ${escapeHtml(p.massif)}</div></div>
    <div class="grade ${gradeClass}">${escapeHtml(c.grade)}</div>
    <div>${escapeHtml(c.season)}</div>
    <div class="note">${escapeHtml(c.note)}</div>
  </div>`;
}

function renderCramponView() {
  const el = document.getElementById('crampon-table');
  const head = `<div class="crampon-row head"><div>Sommet</div><div>Grade</div><div>Saison</div><div>Note</div></div>`;
  el.innerHTML = head + PEAKS.filter(p => p.crampon).map(cramponRowHtml).join('');
}

function openCramponView() {
  renderCramponView();
  document.getElementById('crampon-view').hidden = false;
}

function closeCramponView() {
  document.getElementById('crampon-view').hidden = true;
}

// Ouverture via le bouton dédié dans l'en-tête (❄️ Vue crampons/piolet), Échap pour refermer.
export function initCramponView() {
  document.getElementById('crampon-view-open').addEventListener('click', openCramponView);
  document.getElementById('crampon-view-close').addEventListener('click', closeCramponView);
  document.addEventListener('keydown', (e) => {
    const view = document.getElementById('crampon-view');
    if (e.key === 'Escape' && !view.hidden) closeCramponView();
  });
}
