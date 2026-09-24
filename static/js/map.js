// Carte Leaflet : fond, clusters, calques, contrôles, légende, marqueurs.
import { DIFF_COLORS, DIFF_LABELS, DIFFS, startsMobile } from './config.js';
import { PEAKS, doneSet, passesBaseFilter } from './store.js';
import { clusterIcon, makeIcon } from './icons.js';
import { openPeakPanel } from './panel.js';

// Repositionne juste le zoom (le calque, lui, garde sa position fixée à la création — voir
// startsMobile — puisque Leaflet fige son mode replié/déplié à la construction du contrôle).
export function applyResponsiveControlPositions() {
  const mobile = window.matchMedia('(max-width: 760px)').matches;
  map.zoomControl.setPosition(mobile ? 'bottomleft' : 'topleft');
}

export const map = L.map('map', { zoomControl: true }).setView([44.8, 4.0], 6);

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
  opacity: 0.55
});

// Le fond choisi est mémorisé dans le navigateur (simple confort : sans stockage disponible,
// on retombe sur le fond par défaut).
const BASE_LAYER_KEY = 'summitfr.baseLayer';
function savedBaseLayerName() {
  try {
    const name = localStorage.getItem(BASE_LAYER_KEY);
    return name in baseLayers ? name : DEFAULT_BASE_LAYER;
  } catch {
    return DEFAULT_BASE_LAYER;
  }
}
baseLayers[savedBaseLayerName()].addTo(map);
map.on('baselayerchange', (e) => {
  try { localStorage.setItem(BASE_LAYER_KEY, e.name); } catch { /* stockage indisponible */ }
});

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
export const gpxLayer = L.layerGroup().addTo(map);

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

// Échelle métrique (km/m), en bas à gauche.
L.control.scale({ imperial: false, position: 'bottomleft' }).addTo(map);

const layersControl = L.control.layers(baseLayers, {
  '<span style="color:#1f5f8b">&#9473;</span> Traces GPX': gpxLayer,
  'Pentes &gt; 30° (IGN)': slopesLayer
}, { collapsed: startsMobile, position: startsMobile ? 'topleft' : 'topright' }).addTo(map);

export const markers = new Map(); // name -> {marker, data}

export function buildMarkers() {
  PEAKS.forEach(p => {
    const color = DIFF_COLORS[p.difficulty] || '#555';
    const marker = L.marker([p.lat, p.lon], { icon: makeIcon(color, doneSet.has(p.name), p.altitude_m) });
    marker.on('click', () => openPeakPanel(p, marker));
    markers.set(p.name, { marker, data: p });
  });
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
export function setupMobileLayersPanel() {
  if (!startsMobile) return;
  const container = layersControl.getContainer();
  if (!container) return;

  // Pas d'ouverture/fermeture au « survol » sur écran tactile : un tap émule mouseenter (le
  // panneau s'ouvre), puis l'ouverture change la mise en page sous le doigt et le navigateur
  // émet aussitôt mouseleave — Leaflet refermait le panneau 2 ms après l'avoir ouvert. On ne
  // garde que les gestes explicites : tap sur la flèche, bouton ✕, tap sur la carte.
  // (_expandSafely : méthode interne de Leaflet 1.9.4, version figée dans static/vendor/.)
  L.DomEvent.off(container, { mouseenter: layersControl._expandSafely, mouseleave: layersControl.collapse }, layersControl);

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
