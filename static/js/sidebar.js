// Barre latérale : filtres, recherche, liste des sommets, liste mobile.
import { escapeHtml } from './util.js';
import { DIFFS, DIFF_COLORS, REGIONS, STATUSES } from './config.js';
import { PEAKS, doneSet, passesBaseFilter, session, state } from './store.js';
import { map, markers, syncMarkers } from './map.js';
import { openPeakPanel, toggleDone } from './panel.js';

// --- Mobile : carte plein écran, barre latérale en panneau flottant (filtres), liste masquée
// par défaut et ouverte en plein écran via ce bouton (option "b" retenue). ---
function closeMobileList() {
  const app = document.getElementById('app');
  app.classList.remove('mobile-list-open');
  const btn = document.getElementById('mobile-list-toggle');
  if (btn) btn.textContent = `📋 Liste (${PEAKS.filter(passesBaseFilter).length})`;
}

function toggleMobileList() {
  const app = document.getElementById('app');
  const open = app.classList.toggle('mobile-list-open');
  const btn = document.getElementById('mobile-list-toggle');
  btn.textContent = open ? '✕ Fermer' : `📋 Liste (${PEAKS.filter(passesBaseFilter).length})`;
}

function renderChips(containerId, values, activeCheckFn, labelFn, colorFn, onToggle) {
  const el = document.getElementById(containerId);
  el.innerHTML = '';
  values.forEach(v => {
    const chip = document.createElement('div');
    chip.className = 'chip' + (activeCheckFn(v) ? ' active' : '');
    const dotColor = colorFn ? colorFn(v) : null;
    chip.innerHTML = (dotColor ? `<span class="dot" style="background:${dotColor}"></span>` : '') + labelFn(v);
    chip.onclick = () => { onToggle(v); };
    el.appendChild(chip);
  });
}

function toggleRegion(v) {
  if (state.regions.has(v)) state.regions.delete(v); else state.regions.add(v);
  if (state.regions.size === 0) REGIONS.forEach(r => state.regions.add(r));
  renderChipsAll();
  syncMarkers();
  renderList();
}

function toggleDifficulty(v) {
  if (state.difficulties.has(v)) state.difficulties.delete(v); else state.difficulties.add(v);
  if (state.difficulties.size === 0) DIFFS.forEach(d => state.difficulties.add(d));
  renderChipsAll();
  syncMarkers();
  renderList();
}

function setStatus(v) {
  state.status = v;
  renderChipsAll();
  renderList();
}

export function updateDoneCount() {
  const el = document.getElementById('count');
  const visible = PEAKS.filter(passesBaseFilter);
  const shown = `${visible.length} sommet${visible.length > 1 ? 's' : ''} affiché${visible.length > 1 ? 's' : ''} sur ${PEAKS.length}`;
  // Invité : pas d'espace personnel, donc pas de « faits ».
  el.textContent = session.space === null ? shown : `${shown} · ${doneSet.size} fait${doneSet.size > 1 ? 's' : ''} au total`;
  const toggleBtn = document.getElementById('mobile-list-toggle');
  if (toggleBtn && !document.getElementById('app').classList.contains('mobile-list-open')) {
    toggleBtn.textContent = `📋 Liste (${visible.length})`;
  }
}

export function renderList() {
  const list = document.getElementById('list');
  list.innerHTML = '';
  // En filtre "Tous", les sommets faits remontent en premier (regroupés), altitude décroissante
  // dans chaque groupe ; en filtre "Fait"/"À faire" tous les éléments partagent déjà le même
  // statut, donc l'altitude seule suffit.
  const groupDoneFirst = state.status === 'Tous';
  const filtered = PEAKS.filter(passesBaseFilter).sort((a, b) => {
    if (groupDoneFirst) {
      const doneDiff = (doneSet.has(b.name) ? 1 : 0) - (doneSet.has(a.name) ? 1 : 0);
      if (doneDiff !== 0) return doneDiff;
    }
    return b.altitude_m - a.altitude_m;
  });
  updateDoneCount();

  filtered.forEach(p => {
    const item = document.createElement('div');
    const done = doneSet.has(p.name);
    item.className = 'peak-item' + (done ? ' is-done' : '');
    const color = DIFF_COLORS[p.difficulty];
    item.innerHTML = `
      <div class="row1">
        <span>
          <input type="checkbox" class="done-check" ${done ? 'checked' : ''} ${session.canEdit ? '' : 'disabled'} title="Marquer comme fait" />
          <span class="name">${escapeHtml(p.name)}</span>
        </span>
        <span class="alt">${escapeHtml(p.altitude_m)} m</span>
      </div>
      <div class="meta"><span class="badge" style="background:${color}">${escapeHtml(p.difficulty)}</span>${escapeHtml(p.massif)} &middot; ${escapeHtml(p.region)}</div>
    `;
    item.querySelector('.done-check').addEventListener('click', (e) => {
      e.stopPropagation();
      toggleDone(p);
    });
    item.addEventListener('click', () => {
      const m = markers.get(p.name);
      closeMobileList(); // sur mobile, sélectionner un sommet referme la liste plein écran
      map.flyTo([p.lat, p.lon], 12, { duration: 0.6 });
      // Attend la fin de l'animation pour positionner correctement le panneau à sa première ouverture
      // (il est en coordonnées écran, pas géographiques, donc pas suivi automatiquement pendant le flyTo).
      map.once('moveend', () => openPeakPanel(p, m.marker));
    });
    list.appendChild(item);
  });
}

export function renderChipsAll() {
  renderChips('region-chips', REGIONS, v => state.regions.has(v), v => v, null, toggleRegion);
  renderChips('diff-chips', DIFFS, v => state.difficulties.has(v), v => v, v => DIFF_COLORS[v], toggleDifficulty);
  renderChips('status-chips', STATUSES, v => state.status === v, v => v, null, setStatus);
}

export function initSidebar() {
  document.getElementById('mobile-list-toggle').addEventListener('click', toggleMobileList);
  document.getElementById('search').addEventListener('input', e => {
    state.query = e.target.value.trim();
    syncMarkers();
    renderList();
  });
  map.on('overlayadd overlayremove', () => {
    renderChipsAll();
    renderList();
  });
}
