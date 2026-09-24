// Point d'entrée : initialisation de l'interface et chargement du catalogue.
import { PEAKS, doneSet } from './store.js';
import { applyResponsiveControlPositions, buildMarkers, setupMobileLayersPanel, syncMarkers } from './map.js';
import { initLightbox } from './lightbox.js';
import { initCramponView } from './crampon.js';
import { loadAllGpx } from './gpx.js';
import { initPeakPanel } from './panel.js';
import { initSidebar, renderChipsAll, renderList } from './sidebar.js';

initPeakPanel();
initLightbox();
initCramponView();
initSidebar();
setupMobileLayersPanel();
applyResponsiveControlPositions();
window.addEventListener('resize', applyResponsiveControlPositions);

fetch('/mountains.json?v=' + Date.now(), { cache: 'no-store' })
  .then(r => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
  .then(data => {
    PEAKS.push(...data);
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
