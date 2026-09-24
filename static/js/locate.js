// Bouton « me localiser » : position GPS en direct sur la carte (point bleu + cercle de précision).
import { map } from './map.js';

let watching = false;
let centeredOnce = false;
let dot = null;
let accuracyCircle = null;
let button = null;

function setActive(active) {
  watching = active;
  button.classList.toggle('active', active);
  button.title = active ? 'Arrêter la localisation' : 'Me localiser';
  button.setAttribute('aria-pressed', String(active));
}

function clearPosition() {
  if (dot) map.removeLayer(dot);
  if (accuracyCircle) map.removeLayer(accuracyCircle);
  dot = accuracyCircle = null;
}

function start() {
  centeredOnce = false;
  setActive(true);
  // watch : la position suit le déplacement (sur le sentier) ; haute précision = GPS.
  map.locate({ watch: true, enableHighAccuracy: true, maximumAge: 10000, timeout: 20000 });
}

function stop() {
  map.stopLocate();
  clearPosition();
  setActive(false);
}

function onLocationFound(e) {
  if (!watching) return;
  if (!dot) {
    accuracyCircle = L.circle(e.latlng, { radius: e.accuracy, color: '#1a73e8', weight: 1, fillOpacity: 0.12, interactive: false }).addTo(map);
    dot = L.circleMarker(e.latlng, { radius: 7, color: '#fff', weight: 2, fillColor: '#1a73e8', fillOpacity: 1 }).addTo(map);
    dot.bindTooltip('Vous êtes ici');
  } else {
    dot.setLatLng(e.latlng);
    accuracyCircle.setLatLng(e.latlng).setRadius(e.accuracy);
  }
  // Recentre une seule fois : ensuite l'utilisateur doit pouvoir explorer la carte librement.
  if (!centeredOnce) {
    centeredOnce = true;
    map.setView(e.latlng, Math.max(map.getZoom(), 14));
  }
}

function onLocationError(e) {
  if (!watching) return;
  stop();
  // code 1 = refusé, 2 = position indisponible, 3 = délai dépassé (API Geolocation)
  const reasons = {
    1: "l'accès à la position a été refusé (autorise-le dans les réglages du navigateur pour ce site)",
    2: 'position indisponible (GPS désactivé ?)',
    3: 'le GPS met trop de temps à répondre, réessaie à découvert'
  };
  alert(`Localisation impossible : ${reasons[e.code] || e.message}.`);
}

function position() {
  // Même coin que le zoom (voir applyResponsiveControlPositions dans map.js).
  return window.matchMedia('(max-width: 760px)').matches ? 'bottomleft' : 'topleft';
}

export function initLocateControl() {
  if (!('geolocation' in navigator)) return;
  const control = L.control({ position: position() });
  control.onAdd = () => {
    const div = L.DomUtil.create('div', 'leaflet-bar locate-control');
    button = L.DomUtil.create('a', '', div);
    button.href = '#';
    button.setAttribute('role', 'button');
    button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/><circle cx="12" cy="12" r="8" fill="none"/></svg>';
    setActive(false);
    L.DomEvent.disableClickPropagation(div);
    L.DomEvent.on(button, 'click', L.DomEvent.stop).on(button, 'click', () => (watching ? stop() : start()));
    return div;
  };
  control.addTo(map);
  map.on('locationfound', onLocationFound);
  map.on('locationerror', onLocationError);
  window.matchMedia('(max-width: 760px)').addEventListener('change', () => control.setPosition(position()));
}
