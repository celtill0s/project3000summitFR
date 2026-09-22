let PEAKS = [];
let doneSet = new Set();

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

// --- Appels au backend : toute écriture (coché, commentaire, photos/vidéos, gpx) part
// directement vers le serveur, qui la persiste sur son propre disque (data/). Plus de
// localStorage, plus d'IndexedDB, plus de File System Access API — le serveur EST la
// persistance, quel que soit l'appareil/navigateur utilisé pour consulter le site.
const peakApiBase = name => `/api/peaks/${encodeURIComponent(name)}`;

async function apiPost(url, body) {
  const res = await fetch(url, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || ('HTTP ' + res.status));
  return res.json().catch(() => ({}));
}

async function apiDelete(url) {
  const res = await fetch(url, { method: 'DELETE' });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || ('HTTP ' + res.status));
  return res.json().catch(() => ({}));
}

async function apiUpload(url, file) {
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch(url, { method: 'POST', body: fd });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || ('HTTP ' + res.status));
  return res.json();
}

function isVideoFile(filename) {
  return /\.(mp4|webm|mov|m4v|ogv|avi|mkv)$/i.test(filename || '');
}

// items: [{src, isVideo}, ...] — toute la série de médias du sommet, pour pouvoir défiler
// (flèches, molette de nav ou touches ←/→) d'un média à l'autre sans refermer la visionneuse.
let lightboxState = { items: [], index: 0, alt: '' };

function renderLightboxMedia() {
  const item = lightboxState.items[lightboxState.index];
  const container = document.getElementById('photo-lightbox-media');
  if (!item) { container.innerHTML = ''; return; }
  container.innerHTML = item.isVideo
    ? `<video src="${item.src}" controls autoplay></video>`
    : `<img src="${item.src}" alt="${escapeHtml(lightboxState.alt)}" />`;
  const multi = lightboxState.items.length > 1;
  document.getElementById('photo-lightbox-prev').hidden = !multi;
  document.getElementById('photo-lightbox-next').hidden = !multi;
  const counter = document.getElementById('photo-lightbox-counter');
  counter.hidden = !multi;
  if (multi) counter.textContent = `${lightboxState.index + 1} / ${lightboxState.items.length}`;
}

function openLightbox(items, index, alt) {
  lightboxState = { items, index: index || 0, alt: alt || '' };
  renderLightboxMedia();
  document.getElementById('photo-lightbox').hidden = false;
}

function lightboxNav(delta) {
  const n = lightboxState.items.length;
  if (!n) return;
  lightboxState.index = (lightboxState.index + delta + n) % n;
  renderLightboxMedia();
}

function closeLightbox() {
  document.getElementById('photo-lightbox').hidden = true;
  document.getElementById('photo-lightbox-media').innerHTML = '';
  lightboxState = { items: [], index: 0, alt: '' };
}

function initLightbox() {
  const lb = document.getElementById('photo-lightbox');
  document.getElementById('photo-lightbox-close').addEventListener('click', closeLightbox);
  document.getElementById('photo-lightbox-prev').addEventListener('click', (e) => { e.stopPropagation(); lightboxNav(-1); });
  document.getElementById('photo-lightbox-next').addEventListener('click', (e) => { e.stopPropagation(); lightboxNav(1); });
  lb.addEventListener('click', (e) => { if (e.target === lb) closeLightbox(); });
  document.addEventListener('keydown', (e) => {
    if (lb.hidden) return;
    if (e.key === 'Escape') closeLightbox();
    else if (e.key === 'ArrowLeft') lightboxNav(-1);
    else if (e.key === 'ArrowRight') lightboxNav(1);
  });
}

// --- Vue cachée "crampons + piolet" (POC local) : liste manuellement vérifiée, distincte du
// champ "season" du catalogue (qui décrit la fenêtre de RANDONNÉE normale, sans matériel).
// Ici : sommets où une extension crampons+piolet à pied (pas de corde, pas de glace verticale)
// est documentée, avec le grade alpin (confirmé sur camptocamp.org, ou estimé sinon).
// Voir research/seasons.md pour le détail des sources par sommet.
const CRAMPON_PIOLET_PEAKS = [
  {
    name: 'Pic de Néouvielle', altitude: 3091, region: 'Pyrénées/Néouvielle',
    grade: 'F', confirmed: true, season: 'Juin – juillet',
    note: 'Névé consolidé jusqu\'à juillet, progression facile aux crampons ; grade F confirmé pour la section finale (topo).'
  },
  {
    name: 'Aiguille de la Grande Sassière', altitude: 3747, region: 'Alpes/Vanoise-Tarentaise',
    grade: 'F à PD', confirmed: true, season: 'Fin octobre – novembre',
    note: 'Selon conditions ; forum camptocamp : crampons+piolet obligatoires en fin de saison, pentes gelées même sans neige fraîche.'
  },
  {
    name: 'Ouille Noire', altitude: 3357, region: 'Alpes/Vanoise',
    grade: 'F', confirmed: true, season: 'Fin mai – juin',
    note: 'Pente max 40° sur 100 m (camptocamp). Choix possible entre névés tardifs ou rocher selon l\'année.'
  },
  {
    name: 'Pointe des Cerces', altitude: 3098, region: 'Alpes/Vanoise-Briançonnais',
    grade: 'F (estimé)', confirmed: false, season: 'Avant août / parfois après mi-septembre',
    note: 'Hors de la fenêtre "à sec" (août à mi-sept.), "petite course de neige" — piolet/crampons facilitent sans être strictement obligatoires.'
  },
  {
    name: 'Grand Pic de Tapou', altitude: 3150, region: 'Pyrénées/Vignemale',
    grade: 'F (estimé)', confirmed: false, season: "Jusqu'à mi-juillet",
    note: 'Pentes finales larges et faciles en ascension directe. Ne pas confondre avec la traversée de crête vers le Pic du Milieu (AD-, écartée ci-dessous).'
  },
  {
    name: "Pointe de l'Observatoire", altitude: 3015, region: 'Alpes/Vanoise',
    grade: 'F (estimé)', confirmed: false, season: 'Fin mai',
    note: 'Névés dès 2325 m signalés fin mai ; "aucune difficulté technique" en l\'absence de neige le reste de l\'année.'
  },
  {
    name: 'Petit Vignemale', altitude: 3032, region: 'Pyrénées/Vignemale',
    grade: 'F à PD- (estimé)', confirmed: false, season: 'Fin d\'été / tout début automne uniquement',
    note: '⚠️ Printemps (avril-mai) explicitement déconseillé par les topos : risque d\'avalanche important, pas une simple question de crampons.'
  }
];

function cramponRowHtml(p) {
  const gradeClass = p.confirmed ? 'confirmed' : 'estimated';
  return `<div class="crampon-row">
    <div class="name">${escapeHtml(p.name)}<div class="note" style="margin-top:2px;">${p.altitude} m · ${escapeHtml(p.region)}</div></div>
    <div class="grade ${gradeClass}">${escapeHtml(p.grade)}</div>
    <div>${escapeHtml(p.season)}</div>
    <div class="note">${escapeHtml(p.note)}</div>
  </div>`;
}

function renderCramponView() {
  const el = document.getElementById('crampon-table');
  const head = `<div class="crampon-row head"><div>Sommet</div><div>Grade</div><div>Saison</div><div>Note</div></div>`;
  el.innerHTML = head + CRAMPON_PIOLET_PEAKS.map(cramponRowHtml).join('');
}

function openCramponView() {
  renderCramponView();
  document.getElementById('crampon-view').hidden = false;
}

function closeCramponView() {
  document.getElementById('crampon-view').hidden = true;
}

function toggleCramponView() {
  const view = document.getElementById('crampon-view');
  if (view.hidden) openCramponView(); else closeCramponView();
}

// Ouverture via le bouton dédié dans l'en-tête (❄️ Vue crampons/piolet), Échap pour refermer.
function initCramponView() {
  document.getElementById('crampon-view-open').addEventListener('click', openCramponView);
  document.getElementById('crampon-view-close').addEventListener('click', closeCramponView);
  document.addEventListener('keydown', (e) => {
    const view = document.getElementById('crampon-view');
    if (e.key === 'Escape' && !view.hidden) closeCramponView();
  });
}

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

function initMobileList() {
  document.getElementById('mobile-list-toggle').addEventListener('click', toggleMobileList);
}

// Repositionne juste le zoom (le calque, lui, garde sa position fixée à la création — voir
// startsMobile — puisque Leaflet fige son mode replié/déplié à la construction du contrôle).
function applyResponsiveControlPositions() {
  const mobile = window.matchMedia('(max-width: 760px)').matches;
  map.zoomControl.setPosition(mobile ? 'bottomleft' : 'topleft');
}

function mediaThumbHtml(key, src, isVideo, alt, deleteBtnHtml) {
  const mediaTag = isVideo
    ? `<video src="${src}" muted playsinline preload="metadata"></video><span class="photos-play">&#9658;</span>`
    : `<img src="${src}" loading="lazy" alt="${escapeHtml(alt)}" />`;
  return `<div class="photos-thumb" data-id="${escapeHtml(key)}" data-video="${isVideo ? '1' : '0'}">${mediaTag}${deleteBtnHtml || ''}</div>`;
}

// Toutes les photos/vidéos viennent désormais du serveur (URLs réelles, /photos/<slug>/<fichier>) :
// plus de distinction "importé en local (Blob)" vs "fourni par le dépôt", une seule source de vérité.
function renderPhotosGrid(p, grid, highlightKeys) {
  highlightKeys = highlightKeys || [];
  let html = '';
  (p.photos || []).forEach(filename => {
    const key = `repo:${filename}`;
    const src = `/photos/${slugify(p.name)}/${encodeURIComponent(filename)}`;
    const delBtn = `<button type="button" class="photo-del" data-filename="${escapeHtml(filename)}" title="Supprimer">&#10005;</button>`;
    html += mediaThumbHtml(key, src, isVideoFile(filename), p.name, delBtn);
  });
  grid.innerHTML = html || '<div class="gpx-status">Aucune photo ou vidéo pour l\'instant.</div>';
  const thumbs = [...grid.querySelectorAll('.photos-thumb')];
  thumbs.forEach((thumb, idx) => {
    thumb.addEventListener('click', (e) => {
      if (e.target.closest('.photo-del')) return;
      const items = thumbs.map(t => ({
        src: t.querySelector('img,video').getAttribute('src'),
        isVideo: t.dataset.video === '1'
      }));
      openLightbox(items, idx, p.name);
    });
  });
  grid.querySelectorAll('.photo-del').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const statusEl = grid.parentElement.querySelector('.photos-status');
      const filename = btn.dataset.filename;
      try {
        await apiDelete(`${peakApiBase(p.name)}/photos/${encodeURIComponent(filename)}`);
        p.photos = (p.photos || []).filter(f => f !== filename);
        if (statusEl) statusEl.textContent = 'Supprimée du serveur.';
      } catch (err) {
        if (statusEl) statusEl.textContent = `Échec de la suppression (${err.message}).`;
      }
      renderPhotosGrid(p, grid);
    });
  });
  highlightKeys.forEach(key => {
    const thumb = grid.querySelector(`.photos-thumb[data-id="${CSS.escape(key)}"]`);
    if (thumb) {
      thumb.classList.add('just-added');
      setTimeout(() => thumb.classList.remove('just-added'), 1600);
    }
  });
}

function photosRowHtml(p) {
  return `<div class="photos-row" data-name="${p.name.replace(/"/g, '&quot;')}">
    <div class="photos-label">📷 Photos &amp; vidéos</div>
    <div class="photos-grid"></div>
    <button type="button" class="gpx-btn photos-add">➕ Ajouter des photos/vidéos</button>
    <input type="file" class="photos-file-input" accept="image/*,video/*" multiple hidden />
    <div class="gpx-status photos-status"></div>
  </div>`;
}

function bindPhotosRow(root, p) {
  const row = root.querySelector('.photos-row');
  if (!row) return;
  const grid = row.querySelector('.photos-grid');
  const addBtn = row.querySelector('.photos-add');
  const fileInput = row.querySelector('.photos-file-input');
  const statusEl = row.querySelector('.photos-status');
  addBtn.addEventListener('click', () => fileInput.click());
  fileInput.addEventListener('change', async (e) => {
    const files = [...e.target.files];
    fileInput.value = '';
    const addedFilenames = [];
    for (const file of files) {
      const isVideo = (file.type || '').startsWith('video/');
      statusEl.textContent = `Envoi de ${isVideo ? 'la vidéo' : 'la photo'} en cours…`;
      try {
        const result = await apiUpload(`${peakApiBase(p.name)}/photos`, file);
        if (!Array.isArray(p.photos)) p.photos = [];
        p.photos.push(result.filename);
        addedFilenames.push(result.filename);
        statusEl.textContent = `${isVideo ? 'Vidéo' : 'Photo'} enregistrée sur le serveur.`;
      } catch (err) {
        statusEl.textContent = `Échec de l'envoi (${err.message}).`;
      }
    }
    const highlightKeys = addedFilenames.map(f => `repo:${f}`);
    renderPhotosGrid(p, grid, highlightKeys);
    // Mise en avant immédiate : ouvre la visionneuse sur le dernier média ajouté, avec la
    // possibilité de défiler vers tous les autres (photos ou vidéos) de ce sommet.
    if (highlightKeys.length) {
      const thumbs = [...grid.querySelectorAll('.photos-thumb')];
      const lastKey = highlightKeys[highlightKeys.length - 1];
      const idx = thumbs.findIndex(t => t.dataset.id === lastKey);
      if (idx !== -1) {
        const items = thumbs.map(t => ({
          src: t.querySelector('img,video').getAttribute('src'),
          isVideo: t.dataset.video === '1'
        }));
        openLightbox(items, idx, p.name);
      }
    }
  });
  renderPhotosGrid(p, grid);
}

const DIFF_COLORS = { T2: '#2e8b57', T3: '#d98c1e', T4: '#c0392b' };
const DIFF_LABELS = {
  T2: 'T2 · Randonnée montagne',
  T3: 'T3 · Randonnée exigeante',
  T4: 'T4 · Randonnée alpine (léger hors-sentier / rocher facile)'
};
// Critères génériques de l'échelle de randonnée CAS/SAC (cf. sources.md) — non spécifiques à un sommet.
const DIFF_CRITERIA = {
  T2: 'Sentier parfois raide, terrain par endroits irrégulier. Un minimum d\'expérience de la marche en montagne suffit, pas d\'exposition notable.',
  T3: 'Sentier étroit et/ou exposé par endroits, les mains peuvent être nécessaires ponctuellement. Terrain jugé sûr par tout temps sec, plus engagé si mouillé/enneigé.',
  T4: 'Passages hors-sentier possibles, rocher facile (mains posées, pas d\'escalade franche), terrain non assuré et exposition réelle en cas de chute — mais toujours sans corde ni matériel d\'alpinisme.'
};
const REGIONS = ['Alpes', 'Pyrénées'];
const DIFFS = ['T2', 'T3', 'T4'];
const STATUSES = ['Tous', 'Fait', 'À faire'];

const state = {
  regions: new Set(REGIONS),
  difficulties: new Set(DIFFS),
  status: 'Tous',
  query: ''
};

const map = L.map('map', { zoomControl: true }).setView([44.8, 4.0], 6);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 18,
  attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
}).addTo(map);

// Groupe de clustering unique (toutes difficultés mélangées) : au dézoom, les sommets proches
// se regroupent sous un seul logo montagne avec le nombre total de sommets du secteur ; au
// zoom, ils se "séparent" progressivement en marqueurs individuels (comportement natif du
// plugin Leaflet.markercluster). Le filtre par difficulté (puces + ancien calque natif) agit
// maintenant en ajoutant/retirant les marqueurs de CE groupe plutôt qu'en togglant un calque —
// voir passesBaseFilter/syncMarkers.
const peaksCluster = L.markerClusterGroup({
  iconCreateFunction: (cluster) => clusterIcon(cluster.getChildCount()),
  maxClusterRadius: 28, // rayon réduit (défaut Leaflet : 80) — se sépare beaucoup plus tôt au zoom
  disableClusteringAtZoom: 11, // au-delà, toujours des marqueurs individuels, plus aucun regroupement
  spiderfyOnMaxZoom: true,
  showCoverageOnHover: false
}).addTo(map);

// Calque dédié aux traces GPX importées (itinéraires de rando par sommet).
const gpxLayer = L.layerGroup().addTo(map);

// Bouton "Voir tous" : bascule tous les sommets actuellement affichés vers leur VRAIE position
// individuelle (plus aucun regroupement), sans toucher au zoom/à la vue en cours. Groupé par
// défaut ; reste à l'état choisi (y compris si les filtres changent, voir syncMarkers) jusqu'au
// clic sur "Regrouper".
const individualLayer = L.layerGroup();
let allSeparated = false;

function separateAllPeaks() {
  if (allSeparated) return;
  markers.forEach(({ marker, data }) => {
    if (!passesBaseFilter(data)) return;
    if (peaksCluster.hasLayer(marker)) peaksCluster.removeLayer(marker);
    individualLayer.addLayer(marker);
  });
  if (!map.hasLayer(individualLayer)) individualLayer.addTo(map);
  allSeparated = true;
  updateSeparateAllButton();
}

function regroupAllPeaks() {
  if (!allSeparated) return;
  markers.forEach(({ marker, data }) => {
    if (individualLayer.hasLayer(marker)) individualLayer.removeLayer(marker);
    if (passesBaseFilter(data)) peaksCluster.addLayer(marker);
  });
  map.removeLayer(individualLayer);
  allSeparated = false;
  updateSeparateAllButton();
}

function toggleSeparateAllPeaks() {
  if (allSeparated) regroupAllPeaks(); else separateAllPeaks();
}

let separateAllBtnEl = null;
function updateSeparateAllButton() {
  if (!separateAllBtnEl) return;
  separateAllBtnEl.textContent = allSeparated ? '✕ Regrouper' : '⇲ Voir tous';
  separateAllBtnEl.title = allSeparated
    ? 'Réafficher les regroupements par zone'
    : 'Afficher tous les sommets individuellement, à leur position réelle';
}

const separateAllControl = L.control({ position: 'topleft' });
separateAllControl.onAdd = function () {
  const div = L.DomUtil.create('div', 'leaflet-bar separate-all-control');
  const btn = L.DomUtil.create('a', '', div);
  btn.href = '#';
  separateAllBtnEl = btn;
  updateSeparateAllButton();
  L.DomEvent.disableClickPropagation(div);
  L.DomEvent.on(btn, 'click', L.DomEvent.stop).on(btn, 'click', toggleSeparateAllPeaks);
  return div;
};
separateAllControl.addTo(map);

// Replié par défaut sur mobile (petit bouton natif Leaflet, stylé en flèche via CSS — voir
// .leaflet-control-layers-toggle), toujours déplié sur desktop comme avant. Déterminé une
// seule fois au chargement : le mode replié/déplié de Leaflet se fixe à la création du
// contrôle, pas dynamiquement — cohérent avec un usage réel (on ne redimensionne pas son
// navigateur au-delà du seuil de 760px en cours d'usage). Ne reste plus que la trace GPX ici,
// la difficulté étant désormais gérée par les puces de la barre latérale (voir plus haut).
const startsMobile = window.matchMedia('(max-width: 760px)').matches;
const layersControl = L.control.layers(null, {
  '<span style="color:#1f5f8b">&#9473;</span> Traces GPX': gpxLayer
}, { collapsed: startsMobile, position: startsMobile ? 'topleft' : 'topright' }).addTo(map);

const markers = new Map(); // name -> {marker, data}

// --- GPX : uploadée vers le serveur, servie ensuite depuis /gpx/<slug>.gpx (une seule source de
// vérité, plus de distinction "importé en local" vs "fourni par le dépôt"). ---
const gpxPolylines = new Map(); // name -> [L.Polyline, ...]

function parseGpxFull(gpxText) {
  const doc = new DOMParser().parseFromString(gpxText, 'application/xml');
  if (doc.querySelector('parsererror')) throw new Error('XML invalide');
  const readPt = pt => {
    const lat = parseFloat(pt.getAttribute('lat'));
    const lon = parseFloat(pt.getAttribute('lon'));
    const eleEl = pt.querySelector(':scope > ele');
    const timeEl = pt.querySelector(':scope > time');
    return {
      lat, lon,
      ele: eleEl ? parseFloat(eleEl.textContent) : null,
      time: timeEl ? new Date(timeEl.textContent) : null
    };
  };
  const segments = [];
  const segEls = doc.querySelectorAll('trkseg');
  if (segEls.length) {
    segEls.forEach(seg => {
      const pts = [...seg.querySelectorAll('trkpt')].map(readPt).filter(pt => !isNaN(pt.lat) && !isNaN(pt.lon));
      if (pts.length > 1) segments.push(pts);
    });
  } else {
    // pas de trace (trk) : on retombe sur un itinéraire (rte) si présent
    const pts = [...doc.querySelectorAll('rtept')].map(readPt).filter(pt => !isNaN(pt.lat) && !isNaN(pt.lon));
    if (pts.length > 1) segments.push(pts);
  }
  if (!segments.length) throw new Error('Aucun point de trace (trkpt/rtept) trouvé dans ce GPX');
  return segments;
}

function haversineKm(a, b) {
  const R = 6371;
  const dLat = (b.lat - a.lat) * Math.PI / 180;
  const dLon = (b.lon - a.lon) * Math.PI / 180;
  const la1 = a.lat * Math.PI / 180, la2 = b.lat * Math.PI / 180;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(la1) * Math.cos(la2) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

// Points aplatis (tous segments mis bout à bout) avec distance cumulée en km — sert au profil altimétrique.
function flattenWithDistance(segments) {
  const points = [];
  let cum = 0;
  segments.forEach(seg => {
    seg.forEach((pt, i) => {
      if (points.length && i > 0) cum += haversineKm(seg[i - 1], pt);
      points.push({ ...pt, cumKm: cum });
    });
  });
  return points;
}

function computeGpxStats(segments) {
  const points = flattenWithDistance(segments);
  const distanceKm = points.length ? points[points.length - 1].cumKm : 0;
  const elevations = points.filter(p => p.ele != null && !isNaN(p.ele));
  let elevGainM = 0, elevLossM = 0;
  for (let i = 1; i < elevations.length; i++) {
    const d = elevations[i].ele - elevations[i - 1].ele;
    if (d > 0) elevGainM += d; else elevLossM += -d;
  }
  const hasElevation = elevations.length > 1;
  const minEle = hasElevation ? Math.min(...elevations.map(p => p.ele)) : null;
  const maxEle = hasElevation ? Math.max(...elevations.map(p => p.ele)) : null;

  const timed = points.filter(p => p.time && !isNaN(p.time.getTime()));
  const hasTime = timed.length > 1;
  const recordedDurationH = hasTime
    ? (timed[timed.length - 1].time.getTime() - timed[0].time.getTime()) / 3_600_000
    : null;

  // Estimation indicative (règle de Naismith adaptée à la rando : 4 km/h à plat + 1h par 400 m de D+).
  const estimatedTimeH = distanceKm / 4 + elevGainM / 400;

  return { points, distanceKm, elevGainM, elevLossM, hasElevation, minEle, maxEle, hasTime, recordedDurationH, estimatedTimeH };
}

function formatHours(h) {
  if (h == null || !isFinite(h) || h < 0) return '—';
  const totalMin = Math.round(h * 60);
  const hh = Math.floor(totalMin / 60);
  const mm = totalMin % 60;
  return hh > 0 ? `${hh} h ${mm.toString().padStart(2, '0')}` : `${mm} min`;
}

function elevationProfileSvg(points, width, height) {
  const withEle = points.filter(p => p.ele != null && !isNaN(p.ele));
  if (withEle.length < 2) return '<div class="gpx-status">Ce fichier GPX ne contient pas de données d\'altitude exploitables.</div>';
  const minEle = Math.min(...withEle.map(p => p.ele));
  const maxEle = Math.max(...withEle.map(p => p.ele));
  const maxKm = withEle[withEle.length - 1].cumKm || 1;
  const pad = 4;
  const eleRange = Math.max(1, maxEle - minEle);
  const x = km => pad + (km / maxKm) * (width - 2 * pad);
  const y = ele => height - pad - ((ele - minEle) / eleRange) * (height - 2 * pad);
  const pathPts = withEle.map(p => `${x(p.cumKm).toFixed(1)},${y(p.ele).toFixed(1)}`).join(' ');
  const areaPts = `${x(0).toFixed(1)},${height - pad} ${pathPts} ${x(maxKm).toFixed(1)},${height - pad}`;
  return `
    <svg viewBox="0 0 ${width} ${height}" width="100%" height="${height}" preserveAspectRatio="none" style="display:block;">
      <polygon points="${areaPts}" fill="#1f5f8b" fill-opacity="0.15" />
      <polyline points="${pathPts}" fill="none" stroke="#1f5f8b" stroke-width="1.5" />
    </svg>
    <div style="display:flex;justify-content:space-between;font-size:10.5px;color:var(--muted);margin-top:2px;">
      <span>${Math.round(minEle)} m</span><span>${Math.round(maxEle)} m</span>
    </div>
  `;
}

const gpxData = new Map(); // name -> { stats, points }
const gpxRawText = new Map(); // name -> texte GPX brut (importé OU chargé depuis le dépôt), pour le bouton "Télécharger"

function clearGpxForPeak(name) {
  const existing = gpxPolylines.get(name);
  if (existing) {
    existing.forEach(line => gpxLayer.removeLayer(line));
    gpxPolylines.delete(name);
  }
  gpxData.delete(name);
  gpxRawText.delete(name);
}

function drawGpxForPeak(p, gpxText) {
  const segments = parseGpxFull(gpxText); // peut lever une exception (propagée à l'appelant)
  clearGpxForPeak(p.name);
  const lines = segments.map(seg => L.polyline(seg.map(pt => [pt.lat, pt.lon]), { color: '#1f5f8b', weight: 3, opacity: 0.85 }));
  lines.forEach(line => {
    line.bindTooltip(p.name, { sticky: true });
    gpxLayer.addLayer(line);
  });
  gpxPolylines.set(p.name, lines);
  const stats = computeGpxStats(segments);
  gpxData.set(p.name, stats);
  gpxRawText.set(p.name, gpxText);
  return lines;
}

function slugify(name) {
  return name.toLowerCase()
    .normalize('NFD').replace(/[̀-ͯ]/g, '') // enlève les accents
    .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

function downloadGpx(p) {
  const text = gpxRawText.get(p.name);
  if (!text) return;
  const blob = new Blob([text], { type: 'application/gpx+xml' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${slugify(p.name)}.gpx`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function importGpxFile(p, file, statusEl) {
  const reader = new FileReader();
  reader.onload = async () => {
    try {
      const lines = drawGpxForPeak(p, reader.result);
      const bounds = L.latLngBounds(lines.flatMap(l => l.getLatLngs()));
      map.fitBounds(bounds, { padding: [40, 40] });
      if (statusEl) statusEl.textContent = 'Envoi de la trace au serveur…';
      await apiUpload(`${peakApiBase(p.name)}/gpx`, file);
      p.gpx = `/gpx/${slugify(p.name)}.gpx`;
      if (statusEl) statusEl.textContent = 'Trace enregistrée sur le serveur.';
      refreshGpxRow(p);
    } catch (err) {
      if (statusEl) statusEl.textContent = 'Erreur : ' + err.message;
    }
  };
  reader.onerror = () => { if (statusEl) statusEl.textContent = 'Impossible de lire ce fichier.'; };
  reader.readAsText(file);
}

async function deleteGpxTrack(p) {
  const row = document.querySelector('.gpx-row .gpx-import-status');
  try {
    await apiDelete(`${peakApiBase(p.name)}/gpx`);
  } catch (err) {
    if (row) row.textContent = `Échec de la suppression (${err.message}).`;
  }
  p.gpx = null;
  clearGpxForPeak(p.name);
  refreshGpxRow(p);
}

function loadRepoGpx(p) {
  fetch(p.gpx)
    .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.text(); })
    .then(text => drawGpxForPeak(p, text))
    .catch(() => { /* pas grave : pas de trace fournie pour ce sommet, ou fichier introuvable */ });
}

function gpxRowHtml(p) {
  const hasAny = !!p.gpx || gpxPolylines.has(p.name);
  let body = '';
  if (hasAny) {
    body += `<div class="gpx-status">🧭 Trace affichée sur la carte (calque « Traces GPX »), enregistrée sur le serveur.</div>`;
    body += `<button type="button" class="gpx-btn gpx-detail-toggle">📈 Détail GPX</button>`;
    body += `<button type="button" class="gpx-btn gpx-download">⬇ Télécharger</button>`;
    body += `<button type="button" class="gpx-btn gpx-replace">Remplacer</button>`;
    body += `<button type="button" class="gpx-btn danger gpx-delete">Supprimer</button>`;
    body += `<div class="gpx-detail-body"></div>`;
  } else {
    body += `<button type="button" class="gpx-btn gpx-import">🧭 Importer un GPX</button>`;
  }
  body += `<input type="file" class="gpx-file-input" accept=".gpx,application/gpx+xml,application/xml,text/xml" hidden />`;
  body += `<div class="gpx-status gpx-import-status"></div>`;
  return `<div class="gpx-row" data-name="${p.name.replace(/"/g, '&quot;')}">${body}</div>`;
}

function gpxDetailHtml(p) {
  const d = gpxData.get(p.name);
  if (!d) return '<div class="gpx-status">Pas de données disponibles.</div>';
  const rows = [
    ['Distance', d.distanceKm > 0 ? `${d.distanceKm.toFixed(1)} km` : '—'],
    ['Dénivelé positif', d.hasElevation ? `+${Math.round(d.elevGainM)} m` : '—'],
    ['Dénivelé négatif', d.hasElevation ? `−${Math.round(d.elevLossM)} m` : '—'],
    ['Altitude min / max', d.hasElevation ? `${Math.round(d.minEle)} m / ${Math.round(d.maxEle)} m` : '—'],
    ['Temps estimé', `${formatHours(d.estimatedTimeH)} (indicatif — 4 km/h + 1h/400 m D+)`]
  ];
  if (d.hasTime) rows.push(['Temps enregistré dans le GPX', formatHours(d.recordedDurationH)]);
  const rowsHtml = rows.map(([k, v]) => `<div class="gpx-stat-row"><span>${k}</span><strong>${v}</strong></div>`).join('');
  return `
    <div class="gpx-stats">${rowsHtml}</div>
    <div class="gpx-profile-title">Profil altimétrique</div>
    ${elevationProfileSvg(d.points, 280, 70)}
  `;
}

function bindGpxRow(root, p) {
  const row = root.querySelector('.gpx-row');
  if (!row) return;
  const fileInput = row.querySelector('.gpx-file-input');
  const statusEl = row.querySelector('.gpx-import-status');
  const trigger = () => fileInput.click();
  const importBtn = row.querySelector('.gpx-import');
  const replaceBtn = row.querySelector('.gpx-replace');
  const deleteBtn = row.querySelector('.gpx-delete');
  const downloadBtn = row.querySelector('.gpx-download');
  const detailToggle = row.querySelector('.gpx-detail-toggle');
  const detailBody = row.querySelector('.gpx-detail-body');
  if (importBtn) importBtn.addEventListener('click', trigger);
  if (replaceBtn) replaceBtn.addEventListener('click', trigger);
  if (deleteBtn) deleteBtn.addEventListener('click', () => deleteGpxTrack(p));
  if (downloadBtn) downloadBtn.addEventListener('click', () => downloadGpx(p));
  if (detailToggle && detailBody) {
    detailToggle.addEventListener('click', () => {
      const open = detailBody.classList.toggle('open');
      if (open && !detailBody.dataset.built) {
        detailBody.innerHTML = gpxDetailHtml(p);
        detailBody.dataset.built = '1';
      }
      // NB : pas de popup.update() ici, cf. le toggle "Détail de la cotation" —
      // ça régénérerait tout le HTML de la popup et annulerait ce toggle.
    });
  }
  fileInput.addEventListener('change', e => {
    const file = e.target.files[0];
    if (file) importGpxFile(p, file, statusEl);
    e.target.value = '';
  });
}

function refreshGpxRow(p) {
  if (activePeakName !== p.name) return;
  const root = document.getElementById('peak-panel-body');
  const row = root.querySelector('.gpx-row');
  if (row) {
    row.outerHTML = gpxRowHtml(p);
    bindGpxRow(root, p);
  }
}

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

// Silhouette "montagne" (deux pointes) réutilisée pour les marqueurs individuels ET les
// bulles de cluster, dans un viewBox 24x24.
const MOUNTAIN_PATH = 'M2 20 L9 8 L13 14 L16 9 L22 20 Z';

// Marqueur individuel : logo montagne colorié selon la difficulté (T2/T3/T4), coche verte en
// haut à gauche si le sommet est fait, altitude en petit en bas à droite du logo.
// Plus grand sur PC (espace disponible, pas de doigt qui masque le point) qu'en mobile.
const PEAK_ICON_SCALE = startsMobile ? 1 : 1.4;
function makeIcon(color, done, altitudeM) {
  const s = PEAK_ICON_SCALE;
  const w = Math.round(34 * s), h = Math.round(36 * s);
  const svgSize = Math.round(30 * s), svgLeft = Math.round(2 * s);
  const checkSize = Math.round(13 * s), checkFont = Math.round(9 * s), checkOff = Math.round(-2 * s);
  const altFont = Math.round(8 * s);
  const check = done ? `<div class="peak-icon-check" style="width:${checkSize}px;height:${checkSize}px;top:${checkOff}px;left:${checkOff}px;font-size:${checkFont}px;">&#10003;</div>` : '';
  const alt = altitudeM != null ? `<div class="peak-icon-alt" style="font-size:${altFont}px;">${altitudeM}</div>` : '';
  return L.divIcon({
    className: '',
    html: `<div class="peak-icon-wrap" style="width:${w}px;height:${h}px;">
      <svg viewBox="0 0 24 24" class="peak-icon-svg" style="width:${svgSize}px;height:${svgSize}px;left:${svgLeft}px;"><path d="${MOUNTAIN_PATH}" fill="${color}" stroke="${done ? '#1b3a2c' : '#fff'}" stroke-width="1.4" stroke-linejoin="round"/></svg>
      ${check}${alt}
    </div>`,
    iconSize: [w, h],
    iconAnchor: [w / 2, h / 2]
  });
}

// Bulle de cluster (dézoom) : même logo montagne, couleur neutre (mélange de difficultés),
// avec le nombre total de sommets du secteur affiché par-dessus. Taille légèrement croissante
// selon l'effectif du groupe, purement visuel.
// Badge (rond + chiffre) dessiné DANS le même SVG que la montagne, peint après elle (donc
// forcément au-dessus, sans dépendre d'un empilement CSS/HTML qui peut être perturbé par le
// contexte d'empilement créé par le filter drop-shadow du logo).
function clusterIcon(count) {
  const size = Math.round((count >= 25 ? 46 : count >= 10 ? 40 : 34) * PEAK_ICON_SCALE);
  const label = String(count);
  const r = label.length > 2 ? 6.5 : 5.5; // un peu plus large pour 3 chiffres
  const cx = 24 - r - 1;
  const cy = 24 - r - 1;
  return L.divIcon({
    className: '',
    html: `<svg viewBox="0 0 24 24" width="${size}" height="${size}" style="display:block; filter: drop-shadow(0 1px 3px rgba(0,0,0,.4));">
      <path d="${MOUNTAIN_PATH}" fill="#2c5f4a" stroke="#1b3a2c" stroke-width="1.2" stroke-linejoin="round"/>
      <circle cx="${cx}" cy="${cy}" r="${r}" fill="#fff" stroke="#1b3a2c" stroke-width="1.3"/>
      <text x="${cx}" y="${cy}" text-anchor="middle" dominant-baseline="central" font-size="${label.length > 2 ? 6 : 7}" font-weight="800" fill="#1b3a2c">${label}</text>
    </svg>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size / 2]
  });
}

// popupHtml() reste le nom historique, mais son HTML est injecté dans #peak-panel-body
// (panneau flottant déplaçable) et non plus dans une popup Leaflet.
function popupHtml(p) {
  const color = DIFF_COLORS[p.difficulty] || '#555';
  const checked = doneSet.has(p.name) ? 'checked' : '';
  return `
    <h3>${p.name}</h3>
    <div class="pop-meta">${p.altitude_m} m &middot; ${p.massif} &middot; ${p.region} &middot; <a href="https://www.google.com/maps?q=${p.lat},${p.lon}" target="_blank" rel="noopener noreferrer">Voir sur Google Maps</a></div>
    <span class="badge" style="background:${color}">${p.difficulty}</span>
    <div class="pop-notes">${p.notes}</div>
    <div class="pop-source">Source : ${p.source}</div>
    <button type="button" class="cotation-detail-toggle">Détail de la cotation ${p.difficulty}</button>
    <div class="cotation-detail-body">
      <div class="criteria"><strong>Critère général ${p.difficulty}</strong> (échelle CAS/SAC) : ${DIFF_CRITERIA[p.difficulty] || ''}</div>
      <div class="why"><strong>Pourquoi ce sommet est coté ${p.difficulty}</strong> : ${p.notes}</div>
      <div class="source-link">Source : ${p.source_url ? `<a href="${p.source_url}" target="_blank" rel="noopener noreferrer">${p.source}</a>` : p.source}. Voir <code>sources.md</code> dans le dépôt pour la méthodologie complète.</div>
    </div>
    <label class="pop-done-row"><input type="checkbox" class="pop-done-checkbox" data-name="${p.name.replace(/"/g, '&quot;')}" ${checked}/> Sommet fait</label>
    <div class="pop-comment-row">
      <label>Mon commentaire</label>
      <textarea class="pop-comment-input" placeholder="Notes perso : conditions, ressenti, conseils…">${escapeHtml(p.comment || '')}</textarea>
      <button type="button" class="pop-comment-toggle" hidden>Voir plus</button>
      <div class="pop-comment-status"></div>
    </div>
    ${photosRowHtml(p)}
    ${gpxRowHtml(p)}
  `;
}

function toggleDone(name) {
  const wasDone = doneSet.has(name);
  if (wasDone) doneSet.delete(name); else doneSet.add(name);
  const entry = markers.get(name);
  if (entry) entry.marker.setIcon(makeIcon(DIFF_COLORS[entry.data.difficulty] || '#555', doneSet.has(name), entry.data.altitude_m));
  renderList();
  updateDoneCount();
  apiPost(`${peakApiBase(name)}/done`, { done: !wasDone }).catch(() => {
    // échec réseau : on annule l'affichage optimiste
    if (wasDone) doneSet.add(name); else doneSet.delete(name);
    if (entry) entry.marker.setIcon(makeIcon(DIFF_COLORS[entry.data.difficulty] || '#555', doneSet.has(name), entry.data.altitude_m));
    renderList();
    updateDoneCount();
    alert("Impossible d'enregistrer sur le serveur — vérifie la connexion et réessaie.");
  });
}

// --- Panneau flottant de détail d'un sommet (remplace la popup Leaflet ancrée au marqueur) ---
let activePeakName = null;

function bindPanelContent(root, p) {
  const doneEl = root.querySelector('.pop-done-checkbox');
  if (doneEl) doneEl.addEventListener('change', () => toggleDone(p.name));
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
      if (commentStatusEl) commentStatusEl.textContent = '';
      refreshCommentUI();
      clearTimeout(saveTimer);
      saveTimer = setTimeout(() => {
        const text = commentEl.value.trim();
        p.comment = text;
        apiPost(`${peakApiBase(p.name)}/comment`, { comment: text })
          .then(() => { if (commentStatusEl) commentStatusEl.textContent = 'Enregistré sur le serveur.'; })
          .catch((err) => { if (commentStatusEl) commentStatusEl.textContent = `Échec de l'enregistrement (${err.message}).`; });
      }, 500);
    });
    commentEl.addEventListener('focus', () => {
      if (!commentExpanded) { commentExpanded = true; refreshCommentUI(); }
    });
    commentEl.addEventListener('blur', () => {
      clearTimeout(saveTimer);
      const text = commentEl.value.trim();
      p.comment = text;
      apiPost(`${peakApiBase(p.name)}/comment`, { comment: text })
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
window.addEventListener('resize', clampOpenPanelToMap);
map.on('resize', clampOpenPanelToMap);

function openPeakPanel(p, marker) {
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

function initPeakPanel() {
  const panel = document.getElementById('peak-panel');
  const header = document.getElementById('peak-panel-header');
  document.getElementById('peak-panel-close').addEventListener('click', closePeakPanel);

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

function buildMarkers() {
  PEAKS.forEach(p => {
    const color = DIFF_COLORS[p.difficulty] || '#555';
    const marker = L.marker([p.lat, p.lon], { icon: makeIcon(color, doneSet.has(p.name), p.altitude_m) });
    marker.on('click', () => openPeakPanel(p, marker));
    markers.set(p.name, { marker, data: p });
  });
}

function loadAllGpx() {
  PEAKS.forEach(p => { if (p.gpx) loadRepoGpx(p); });
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

function passesBaseFilter(p) {
  if (!state.regions.has(p.region)) return false;
  if (!state.difficulties.has(p.difficulty)) return false;
  if (state.status === 'Fait' && !doneSet.has(p.name)) return false;
  if (state.status === 'À faire' && doneSet.has(p.name)) return false;
  if (state.query) {
    const q = state.query.toLowerCase();
    if (!(p.name.toLowerCase().includes(q) || p.massif.toLowerCase().includes(q))) return false;
  }
  return true;
}

function updateDoneCount() {
  const el = document.getElementById('count');
  const visible = PEAKS.filter(passesBaseFilter);
  const doneVisible = visible.filter(p => doneSet.has(p.name)).length;
  el.textContent = `${visible.length} sommet${visible.length > 1 ? 's' : ''} affiché${visible.length > 1 ? 's' : ''} sur ${PEAKS.length} · ${doneSet.size} fait${doneSet.size > 1 ? 's' : ''} au total`;
  const toggleBtn = document.getElementById('mobile-list-toggle');
  if (toggleBtn && !document.getElementById('app').classList.contains('mobile-list-open')) {
    toggleBtn.textContent = `📋 Liste (${visible.length})`;
  }
}

function renderList() {
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
          <input type="checkbox" class="done-check" ${done ? 'checked' : ''} title="Marquer comme fait" />
          <span class="name">${p.name}</span>
        </span>
        <span class="alt">${p.altitude_m} m</span>
      </div>
      <div class="meta"><span class="badge" style="background:${color}">${p.difficulty}</span>${p.massif} &middot; ${p.region}</div>
    `;
    item.querySelector('.done-check').addEventListener('click', (e) => {
      e.stopPropagation();
      toggleDone(p.name);
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

function syncMarkers() {
  // Respecte l'état "éclaté"/"groupé" choisi via le bouton Voir tous/Regrouper : un changement
  // de filtre ne doit pas le réinitialiser, juste ajuster quels sommets sont visibles dans le
  // calque actif.
  const activeLayer = allSeparated ? individualLayer : peaksCluster;
  markers.forEach(({ marker, data }) => {
    const show = passesBaseFilter(data);
    if (show && !activeLayer.hasLayer(marker)) activeLayer.addLayer(marker);
    if (!show && activeLayer.hasLayer(marker)) activeLayer.removeLayer(marker);
  });
}

function renderChipsAll() {
  renderChips('region-chips', REGIONS, v => state.regions.has(v), v => v, null, toggleRegion);
  renderChips('diff-chips', DIFFS, v => state.difficulties.has(v), v => v, v => DIFF_COLORS[v], toggleDifficulty);
  renderChips('status-chips', STATUSES, v => state.status === v, v => v, null, setStatus);
}

map.on('overlayadd overlayremove', () => {
  renderChipsAll();
  renderList();
});

document.getElementById('search').addEventListener('input', e => {
  state.query = e.target.value.trim();
  syncMarkers();
  renderList();
});

// Légende (rappel des couleurs). Sur desktop : boîte fixe en bas à droite, comme avant. Sur
// mobile : masquée en tant que contrôle séparé (une seule flèche voulue, pas deux) — son
// contenu est plutôt fusionné dans le panneau du sélecteur de calques (voir
// setupMobileLayersPanel), qui ouvre/ferme les deux à la fois.
function legendContentHtml() {
  return `
    <div class="legend-title">Cotation randonnée</div>
    ${DIFFS.map(d => `<div class="legend-row"><span class="legend-dot" style="background:${DIFF_COLORS[d]}"></span>${DIFF_LABELS[d]}</div>`).join('')}
    <div class="legend-row" style="margin-top:6px;"><span style="color:#1b3a2c">&#10003;</span>&nbsp;Sommet fait</div>
  `;
}

const legend = L.control({ position: 'bottomright' });
legend.onAdd = function () {
  const div = L.DomUtil.create('div', '');
  div.id = 'legend';
  div.innerHTML = legendContentHtml();
  L.DomEvent.disableClickPropagation(div);
  return div;
};
legend.addTo(map);

// Une seule flèche sur mobile (celle du sélecteur de calques) : on y ajoute la légende + un
// vrai bouton "fermer" visible (Leaflet masque son propre bouton une fois le panneau ouvert,
// sans offrir de moyen de le refermer autrement qu'en tapant ailleurs sur la carte).
function setupMobileLayersPanel() {
  if (!startsMobile) return;
  const container = layersControl.getContainer();
  if (!container) return;

  const closeBtn = document.createElement('button');
  closeBtn.type = 'button';
  closeBtn.className = 'leaflet-control-layers-close';
  closeBtn.setAttribute('aria-label', 'Fermer');
  closeBtn.textContent = '✕';
  closeBtn.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    layersControl.collapse();
  });
  container.insertBefore(closeBtn, container.firstChild);

  const list = container.querySelector('.leaflet-control-layers-list') || container;
  const legendBlock = document.createElement('div');
  legendBlock.className = 'legend-in-layers';
  legendBlock.innerHTML = legendContentHtml();
  list.appendChild(legendBlock);
}

initPeakPanel();
initLightbox();
initCramponView();
initMobileList();
setupMobileLayersPanel();
applyResponsiveControlPositions();
window.addEventListener('resize', applyResponsiveControlPositions);

fetch('/mountains.json?v=' + Date.now(), { cache: 'no-store' })
  .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
  .then(data => {
    PEAKS = data;
    // "done" fusionné par le serveur depuis data/progress.json (overlay privé) — une seule
    // source de vérité, partagée par tous les appareils qui consultent ce serveur.
    PEAKS.filter(p => p.done).forEach(p => doneSet.add(p.name));
    buildMarkers();
    renderChipsAll();
    syncMarkers();
    renderList();
    loadAllGpx();
  })
  .catch(err => {
    document.getElementById('list').innerHTML =
      `<div id="loading" class="error">Impossible de charger mountains.json (${err.message}).<br><br>
       Vérifie que le serveur (backend) tourne bien.</div>`;
  });
