// Carte Leaflet : fond, clusters, calques, contrôles, légende, marqueurs.
import { DIFF_COLORS, DIFF_LABELS, DIFFS } from './config.js';
import { PEAKS, doneSet, passesBaseFilter } from './store.js';
import { clusterIcon, makeIcon } from './icons.js';
import { openPeakPanel } from './panel.js';

// Contrôles de la carte : à droite sur ordinateur (la liste occupe tout le côté gauche), sous la
// barre d'outils ➕ ⛏ ⚙ ; sur mobile, en bas à gauche (la liste s'y ouvre en plein écran).
export function applyResponsiveControlPositions() {
  const mobile = window.matchMedia('(max-width: 760px)').matches;
  map.zoomControl.setPosition(mobile ? 'bottomleft' : 'topright');
  separateAllControl.setPosition(mobile ? 'bottomleft' : 'topright');
  legend.setPosition(mobile ? 'topleft' : 'bottomright');
  if (mobile) {
    // Sur mobile, l'œil (voir tous / regrouper) se place juste au-dessus du bouton « me
    // localiser » (js/locate.js), dans la colonne du bas à gauche.
    const corner = map.getContainer().querySelector('.leaflet-bottom.leaflet-left');
    const locate = corner?.querySelector('.locate-control');
    if (locate) corner.insertBefore(separateAllControl.getContainer(), locate);
  }
}

export const map = L.map('map', { zoomControl: true });

// Sur ordinateur, la liste (verre dépoli) recouvre la gauche de la carte : la zone vraiment
// visible est décalée vers la droite d'une demi-largeur de liste. Les recentrages en tiennent
// compte pour que le point visé tombe au milieu de ce qu'on voit, pas sous la liste.
function hiddenLeftWidth() {
  const sidebar = document.getElementById('sidebar');
  return !sidebar || window.matchMedia('(max-width: 760px)').matches ? 0 : sidebar.offsetWidth;
}

export function visibleCenter(latlng, zoom) {
  const shift = hiddenLeftWidth() / 2;
  if (!shift) return L.latLng(latlng);
  return map.unproject(map.project(latlng, zoom).subtract([shift, 0]), zoom);
}

export function flyToVisible(latlng, zoom, options) {
  map.flyTo(visibleCenter(latlng, zoom), zoom, options);
}

map.setView(visibleCenter([44.8, 4.0], 6), 6);

// --- Fonds de carte ---
// IGN : flux WMTS public de la Géoplateforme (data.geopf.fr), gratuit et sans clé. Le SCAN 25
// (carte topo « randonnée ») n'y est pas : il exige une clé personnelle. Les tuiles IGN sont
// vides hors de France (versant espagnol des sommets frontaliers) : OSM reste proposé.
// crossOrigin : tuiles demandées en CORS (les deux serveurs l'autorisent), pour que le service
// worker puisse les garder en cache hors-ligne (une réponse opaque ne se met pas en cache).
const IGN_ATTRIBUTION = '&copy; <a href="https://www.ign.fr/">IGN</a> – Géoplateforme';
function ignLayer(layer, format, options) {
  return L.tileLayer(
    'https://data.geopf.fr/wmts?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&STYLE=normal' +
    `&TILEMATRIXSET=PM&LAYER=${layer}&FORMAT=${format}&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}`,
    { maxZoom: 19, attribution: IGN_ATTRIBUTION, crossOrigin: true, ...options }
  );
}

// URL sans sous-domaine a/b/c : recommandée par OSM depuis leur passage au CDN.
function osmLayer(options) {
  return L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    crossOrigin: true,
    ...options
  });
}

// Fond « Auto » : OSM tant qu'on voit tout un massif (plus lisible à petite échelle), Plan IGN
// dès qu'on zoome sur un secteur (relief, sentiers, courbes de niveau). Chaque couche n'affiche
// ses tuiles que dans sa plage de zoom : la bascule se fait toute seule. Les tuiles IGN étant
// opaques (blanches hors de France), pas de repli automatique sur OSM pour le versant espagnol
// ou italien : choisir « OpenStreetMap » à la main dans ce cas.
// Zoom 9 = premier niveau où l'échelle affiche « 20 km » (entre 42° et 46° de latitude, soit
// tous nos sommets) ; au zoom 8 elle affiche « 30 km ».
const IGN_FROM_ZOOM = 9;
const planIgnPath = ['GEOGRAPHICALGRIDSYSTEMS.PLANIGNV2', 'image/png'];

const baseLayers = {
  'Auto (OSM, puis IGN en zoomant)': L.layerGroup([
    osmLayer({ maxZoom: IGN_FROM_ZOOM - 1 }),
    ignLayer(...planIgnPath, { minZoom: IGN_FROM_ZOOM })
  ]),
  'Plan IGN': ignLayer(...planIgnPath),
  'Photos aériennes IGN': ignLayer('ORTHOIMAGERY.ORTHOPHOTOS', 'image/jpeg'),
  'OpenStreetMap': osmLayer()
};
const DEFAULT_BASE_LAYER = 'Auto (OSM, puis IGN en zoomant)';

// Surcouche IGN des pentes > 30° en montagne (zones avalancheuses potentielles) : servie
// jusqu'au zoom 17, agrandie au-delà.
const slopesLayer = ignLayer('GEOGRAPHICALGRIDSYSTEMS.SLOPES.MOUNTAIN', 'image/png', {
  maxNativeZoom: 17,
  opacity: 0.55,
  zIndex: 10 // toujours au-dessus du fond, même après un changement de fond
});

// Fond et calques choisis dans le panneau ⚙ (js/settings.js), mémorisés dans le navigateur
// (simple confort : sans stockage disponible, on retombe sur les valeurs par défaut).
const BASE_LAYER_KEY = 'summitfr.baseLayer';
const OVERLAYS_KEY = 'summitfr.overlays';
function readSetting(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function writeSetting(key, value) {
  try { localStorage.setItem(key, value); } catch { /* stockage indisponible */ }
}

export const BASE_LAYER_NAMES = Object.keys(baseLayers);
let currentBaseLayer = baseLayers[readSetting(BASE_LAYER_KEY)] ? readSetting(BASE_LAYER_KEY) : DEFAULT_BASE_LAYER;
baseLayers[currentBaseLayer].addTo(map);

export function getBaseLayer() {
  return currentBaseLayer;
}

export function setBaseLayer(name) {
  if (!baseLayers[name] || name === currentBaseLayer) return;
  map.removeLayer(baseLayers[currentBaseLayer]);
  baseLayers[name].addTo(map);
  currentBaseLayer = name;
  writeSetting(BASE_LAYER_KEY, name);
}

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
export const gpxLayer = L.layerGroup();

// Surcouches activables dans le panneau ⚙ : traces GPX (affichées par défaut), pentes > 30°.
const overlays = { gpx: gpxLayer, slopes: slopesLayer };
const overlayState = { gpx: true, slopes: false, ...JSON.parse(readSetting(OVERLAYS_KEY) || '{}') };

export function isOverlayVisible(name) {
  return !!overlayState[name];
}

export function setOverlayVisible(name, visible) {
  overlayState[name] = visible;
  if (visible) overlays[name].addTo(map); else map.removeLayer(overlays[name]);
  writeSetting(OVERLAYS_KEY, JSON.stringify(overlayState));
}
Object.keys(overlays).forEach(name => { if (overlayState[name]) overlays[name].addTo(map); });

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
// Icône d'œil : ouvert = « voir tous les sommets » (regroupés pour l'instant), barré =
// « regrouper » (tous affichés pour l'instant). L'icône montre ce que fait le clic.
const EYE_OPEN = '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" />';
const EYE_CLOSED = '<path d="M9.9 4.2A10 10 0 0 1 12 4c6.4 0 10 8 10 8a17 17 0 0 1-2.2 3.2M6.6 6.6A17 17 0 0 0 2 12s3.6 8 10 8a9.6 9.6 0 0 0 5.4-1.6" /><path d="M14.1 14.1a3 3 0 1 1-4.2-4.2" /><path d="m2 2 20 20" />';
function updateSeparateAllButton() {
  if (!separateAllBtnEl) return;
  const label = allSeparated
    ? 'Regrouper les sommets par zone'
    : 'Voir tous les sommets, à leur position réelle';
  separateAllBtnEl.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${allSeparated ? EYE_CLOSED : EYE_OPEN}</svg>`;
  separateAllBtnEl.title = label;
  separateAllBtnEl.setAttribute('aria-label', label);
  separateAllBtnEl.classList.toggle('active', allSeparated);
}

const separateAllControl = L.control({ position: 'topleft' });
separateAllControl.onAdd = function () {
  const div = L.DomUtil.create('div', 'leaflet-bar separate-all-control');
  const btn = L.DomUtil.create('a', '', div);
  btn.href = '#';
  btn.setAttribute('role', 'button');
  separateAllBtnEl = btn;
  updateSeparateAllButton();
  L.DomEvent.disableClickPropagation(div);
  L.DomEvent.on(btn, 'click', L.DomEvent.stop).on(btn, 'click', toggleSeparateAllPeaks);
  return div;
};
separateAllControl.addTo(map);

// Échelle métrique (km/m), en bas à gauche.
L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(map);

export const markers = new Map(); // id -> {marker, data}

export function buildMarkers() {
  PEAKS.forEach(addPeakMarker);
}

function peakIcon(p) {
  return makeIcon(DIFF_COLORS[p.difficulty] || '#555', doneSet.has(p.id), p.altitude_m);
}

export function addPeakMarker(p) {
  const marker = L.marker([p.lat, p.lon], { icon: peakIcon(p) });
  marker.on('click', () => openPeakPanel(p, marker));
  markers.set(p.id, { marker, data: p });
  return marker;
}

// Après un changement de statut, de cotation, d'altitude ou de position.
export function refreshPeakMarker(p) {
  const entry = markers.get(p.id);
  if (!entry) return;
  entry.marker.setIcon(peakIcon(p));
  entry.marker.setLatLng([p.lat, p.lon]);
  if (peaksCluster.hasLayer(entry.marker)) peaksCluster.refreshClusters(entry.marker);
}

export function removePeakMarker(p) {
  const entry = markers.get(p.id);
  if (!entry) return;
  peaksCluster.removeLayer(entry.marker);
  individualLayer.removeLayer(entry.marker);
  markers.delete(p.id);
}

export function syncMarkers() {
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

// Légende (rappel des couleurs), repliée par défaut : juste « Cotation randonnée ▾ » ; un clic
// déplie le détail T2/T3/T4. En bas à droite sur ordinateur, en haut à gauche sur mobile (le
// bouton « Liste » occupe le bas à droite).
function legendContentHtml() {
  return `
    <button type="button" class="legend-toggle" aria-expanded="false" aria-controls="legend-body">
      <span class="legend-title">Cotation randonnée</span><span class="legend-arrow" aria-hidden="true">▾</span>
    </button>
    <div class="legend-body" id="legend-body" hidden>
      ${DIFFS.map(d => `<div class="legend-row"><span class="legend-dot" style="background:${DIFF_COLORS[d]}"></span>${DIFF_LABELS[d]}</div>`).join('')}
      <div class="legend-row" style="margin-top:6px;"><span style="color:#1b3a2c">&#10003;</span>&nbsp;Sommet fait</div>
    </div>
  `;
}

const legend = L.control({ position: 'bottomright' });
legend.onAdd = function () {
  const div = L.DomUtil.create('div', '');
  div.id = 'legend';
  div.innerHTML = legendContentHtml();
  const toggle = div.querySelector('.legend-toggle');
  const body = div.querySelector('.legend-body');
  toggle.addEventListener('click', () => {
    body.hidden = !body.hidden;
    toggle.setAttribute('aria-expanded', String(!body.hidden));
    div.classList.toggle('open', !body.hidden);
  });
  L.DomEvent.disableClickPropagation(div);
  return div;
};
legend.addTo(map);
