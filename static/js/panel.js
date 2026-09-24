// Panneau flottant de détail d'un sommet (fait, commentaire, médias, GPX).
import { escapeHtml, safeUrl } from './util.js';
import { DIFF_COLORS, DIFF_CRITERIA } from './config.js';
import { doneSet, session } from './store.js';
import { apiPost, peakApiBase } from './api.js';
import { makeIcon } from './icons.js';
import { map, markers } from './map.js';
import { bindPhotosRow, photosRowHtml } from './photos.js';
import { bindGpxRow, gpxRowHtml } from './gpx.js';
import { renderList, updateDoneCount } from './sidebar.js';

// Zone de commentaire : hauteur qui suit le contenu (dans la limite COMMENT_EXPANDED_MAX),
// repliée à COMMENT_COLLAPSED_MAX avec un "Voir plus" tant que le texte n'a pas été déplié.
const COMMENT_COLLAPSED_MAX = 160;
const COMMENT_EXPANDED_MAX = 360;

function autosizeCommentTextarea(el, expanded) {
  el.style.height = 'auto';
  const naturalHeight = el.scrollHeight;
  const overflowsCollapsed = naturalHeight > COMMENT_COLLAPSED_MAX + 2;
  const cap = expanded ? COMMENT_EXPANDED_MAX : COMMENT_COLLAPSED_MAX;
  el.style.height = Math.min(naturalHeight, cap) + 'px';
  el.style.overflowY = naturalHeight > cap ? 'auto' : 'hidden';
  return overflowsCollapsed;
}

// popupHtml() reste le nom historique, mais son HTML est injecté dans #peak-panel-body
// (panneau flottant déplaçable) et non plus dans une popup Leaflet.
function popupHtml(p) {
  const color = DIFF_COLORS[p.difficulty] || '#555';
  const checked = doneSet.has(p.name) ? 'checked' : '';
  const name = escapeHtml(p.name);
  const diff = escapeHtml(p.difficulty);
  const notes = escapeHtml(p.notes);
  const source = escapeHtml(p.source);
  const sourceUrl = safeUrl(p.source_url);
  return `
    <h3>${name}</h3>
    <div class="pop-meta">${escapeHtml(p.altitude_m)} m &middot; ${escapeHtml(p.massif)} &middot; ${escapeHtml(p.region)} &middot; <a href="https://www.google.com/maps?q=${Number(p.lat)},${Number(p.lon)}" target="_blank" rel="noopener noreferrer">Voir sur Google Maps</a></div>
    <span class="badge" style="background:${color}">${diff}</span>
    <div class="pop-notes">${notes}</div>
    <div class="pop-source">Source : ${source}</div>
    <button type="button" class="cotation-detail-toggle">Détail de la cotation ${diff}</button>
    <div class="cotation-detail-body">
      <div class="criteria"><strong>Critère général ${diff}</strong> (échelle CAS/SAC) : ${DIFF_CRITERIA[p.difficulty] || ''}</div>
      <div class="why"><strong>Pourquoi ce sommet est coté ${diff}</strong> : ${notes}</div>
      <div class="source-link">Source : ${sourceUrl ? `<a href="${escapeHtml(sourceUrl)}" target="_blank" rel="noopener noreferrer">${source}</a>` : source}. Voir <code>sources.md</code> dans le dépôt pour la méthodologie complète.</div>
    </div>
    <label class="pop-done-row"><input type="checkbox" class="pop-done-checkbox" data-name="${name}" ${checked} ${session.canEdit ? '' : 'disabled'}/> Sommet fait</label>
    <div class="pop-comment-row">
      <label>${session.viewingOther ? `Commentaire de ${escapeHtml(session.space)}` : 'Mon commentaire'}</label>
      <textarea class="pop-comment-input" placeholder="Notes perso : conditions, ressenti, conseils…" ${session.canEdit ? '' : 'readonly'}>${escapeHtml(p.comment || '')}</textarea>
      <button type="button" class="pop-comment-toggle" hidden>Voir plus</button>
      <div class="pop-comment-status"></div>
    </div>
    ${photosRowHtml(p)}
    ${gpxRowHtml(p)}
  `;
}

export function toggleDone(p) {
  if (!session.canEdit) return; // invité, ou admin consultant l'espace d'un autre
  const name = p.name;
  const wasDone = doneSet.has(name);
  if (wasDone) doneSet.delete(name); else doneSet.add(name);
  const entry = markers.get(name);
  if (entry) entry.marker.setIcon(makeIcon(DIFF_COLORS[entry.data.difficulty] || '#555', doneSet.has(name), entry.data.altitude_m));
  renderList();
  updateDoneCount();
  apiPost(`${peakApiBase(p)}/done`, { done: !wasDone }).catch(() => {
    // échec réseau : on annule l'affichage optimiste
    if (wasDone) doneSet.add(name); else doneSet.delete(name);
    if (entry) entry.marker.setIcon(makeIcon(DIFF_COLORS[entry.data.difficulty] || '#555', doneSet.has(name), entry.data.altitude_m));
    renderList();
    updateDoneCount();
    alert("Impossible d'enregistrer sur le serveur — vérifie la connexion et réessaie.");
  });
}

// --- Panneau flottant de détail d'un sommet (remplace la popup Leaflet ancrée au marqueur) ---
export let activePeakName = null;

function bindPanelContent(root, p) {
  const doneEl = root.querySelector('.pop-done-checkbox');
  if (doneEl) doneEl.addEventListener('change', () => toggleDone(p));
  const toggleBtn = root.querySelector('.cotation-detail-toggle');
  const toggleBody = root.querySelector('.cotation-detail-body');
  if (toggleBtn && toggleBody) {
    toggleBtn.addEventListener('click', () => {
      toggleBody.classList.toggle('open');
    });
  }
  const commentEl = root.querySelector('.pop-comment-input');
  const commentStatusEl = root.querySelector('.pop-comment-status');
  const commentToggleEl = root.querySelector('.pop-comment-toggle');
  if (commentEl) {
    let saveTimer = null;
    let commentExpanded = false;
    const refreshCommentUI = () => {
      const overflowsCollapsed = autosizeCommentTextarea(commentEl, commentExpanded);
      if (commentToggleEl) {
        commentToggleEl.hidden = !overflowsCollapsed;
        commentToggleEl.textContent = commentExpanded ? 'Voir moins' : 'Voir plus';
      }
    };
    refreshCommentUI();
    commentEl.addEventListener('input', () => {
      if (!session.canEdit) return;
      if (commentStatusEl) commentStatusEl.textContent = '';
      refreshCommentUI();
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        const text = commentEl.value.trim();
        p.comment = text;
        apiPost(`${peakApiBase(p)}/comment`, { comment: text })
          .then(() => { if (commentStatusEl) commentStatusEl.textContent = 'Enregistré sur le serveur.'; })
          .catch((err) => { if (commentStatusEl) commentStatusEl.textContent = `Échec de l'enregistrement (${err.message}).`; });
      }, 500);
    });
    commentEl.addEventListener('focus', () => {
      if (!commentExpanded) { commentExpanded = true; refreshCommentUI(); }
    });
    commentEl.addEventListener('blur', () => {
      if (!session.canEdit) return;
      clearTimeout(saveTimer);
      const text = commentEl.value.trim();
      p.comment = text;
      apiPost(`${peakApiBase(p)}/comment`, { comment: text })
        .then(() => { if (commentStatusEl) commentStatusEl.textContent = 'Enregistré sur le serveur.'; })
        .catch((err) => { if (commentStatusEl) commentStatusEl.textContent = `Échec de l'enregistrement (${err.message}).`; });
    });
    if (commentToggleEl) {
      commentToggleEl.addEventListener('click', () => {
        commentExpanded = !commentExpanded;
        refreshCommentUI();
      });
    }
  }
  bindPhotosRow(root, p);
  bindGpxRow(root, p);
}

// Recadre une valeur (position + taille) pour qu'elle tienne toujours entre `margin` et
// `containerSize - margin` — utilisé pour garantir qu'aucun coin du panneau ne sorte jamais
// de la zone carte, quels que soient la position du marqueur ou la taille du panneau.
function clampIntoRange(value, size, containerSize, margin) {
  const maxVal = Math.max(margin, containerSize - size - margin);
  return Math.min(Math.max(margin, value), maxVal);
}

// Positionne le panneau près du marqueur cliqué, toujours entièrement dans la zone carte —
// seulement à sa toute première ouverture : ensuite il reste où l'utilisateur l'a laissé/déplacé.
function positionPanelNear(marker) {
  if (!marker) return;
  const panel = document.getElementById('peak-panel');
  const mapEl = document.getElementById('map');
  const pt = map.latLngToContainerPoint(marker.getLatLng());
  const margin = 8;
  const mapW = mapEl.clientWidth, mapH = mapEl.clientHeight;
  const w = panel.offsetWidth, h = panel.offsetHeight;
  // Position "naturelle" (au-dessus, légèrement à droite du marqueur), puis recadrage
  // inconditionnel sur les deux axes : aucune branche ne doit pouvoir sauter ce recadrage.
  const left = clampIntoRange(pt.x + 18, w, mapW, margin);
  const top = clampIntoRange(pt.y - h - 12, h, mapH, margin);
  panel.style.left = left + 'px';
  panel.style.top = top + 'px';
}

// Filet de sécurité : si la fenêtre (ou le passage au layout mobile) redimensionne la carte
// après ouverture, on recadre le panneau déjà affiché dans les nouvelles limites.
function clampOpenPanelToMap() {
  const panel = document.getElementById('peak-panel');
  if (!panel || panel.hidden) return;
  const mapEl = document.getElementById('map');
  const margin = 8;
  panel.style.left = clampIntoRange(panel.offsetLeft, panel.offsetWidth, mapEl.clientWidth, margin) + 'px';
  panel.style.top = clampIntoRange(panel.offsetTop, panel.offsetHeight, mapEl.clientHeight, margin) + 'px';
}
export function openPeakPanel(p, marker) {
  const panel = document.getElementById('peak-panel');
  const body = document.getElementById('peak-panel-body');
  if (activePeakName === p.name && !panel.hidden) return; // déjà affiché : ne pas régénérer (édition en cours)
  const wasHidden = panel.hidden;
  body.innerHTML = popupHtml(p);
  activePeakName = p.name;
  bindPanelContent(body, p);
  panel.hidden = false;
  if (wasHidden) positionPanelNear(marker);
}

function closePeakPanel() {
  document.getElementById('peak-panel').hidden = true;
  activePeakName = null;
}

export function initPeakPanel() {
  const panel = document.getElementById('peak-panel');
  const header = document.getElementById('peak-panel-header');
  document.getElementById('peak-panel-close').addEventListener('click', closePeakPanel);
  window.addEventListener('resize', clampOpenPanelToMap);
  map.on('resize', clampOpenPanelToMap);

  // Le panneau est un enfant du conteneur Leaflet : sans ceci, tout clic/glisser dedans
  // (en-tête, mais aussi la zone de commentaire, la molette, etc.) remonte à la carte et
  // déclenche son propre panoramique/zoom en même temps que nos actions.
  L.DomEvent.disableClickPropagation(panel);
  L.DomEvent.disableScrollPropagation(panel);

  let drag = null;
  header.addEventListener('pointerdown', (e) => {
    if (e.target.closest('#peak-panel-close')) return;
    e.stopPropagation();
    e.preventDefault();
    const mapEl = document.getElementById('map');
    drag = {
      pointerId: e.pointerId,
      startX: e.clientX,
      startY: e.clientY,
      startLeft: panel.offsetLeft,
      startTop: panel.offsetTop,
      mapW: mapEl.clientWidth,
      mapH: mapEl.clientHeight
    };
    header.classList.add('dragging');
    header.setPointerCapture(e.pointerId);
  });
  header.addEventListener('pointermove', (e) => {
    if (!drag || e.pointerId !== drag.pointerId) return;
    e.stopPropagation();
    const dx = e.clientX - drag.startX;
    const dy = e.clientY - drag.startY;
    const maxLeft = Math.max(0, drag.mapW - panel.offsetWidth);
    const maxTop = Math.max(0, drag.mapH - panel.offsetHeight);
    panel.style.left = Math.min(Math.max(0, drag.startLeft + dx), maxLeft) + 'px';
    panel.style.top = Math.min(Math.max(0, drag.startTop + dy), maxTop) + 'px';
  });
  const endDrag = (e) => { drag = null; header.classList.remove('dragging'); if (e) e.stopPropagation(); };
  header.addEventListener('pointerup', endDrag);
  header.addEventListener('pointercancel', endDrag);
}
