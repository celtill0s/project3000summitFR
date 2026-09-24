// Point d'entrée : initialisation de l'interface et chargement du catalogue.
import { PEAKS, doneSet, session } from './store.js';
import { apiGet } from './api.js';
import { escapeHtml } from './util.js';
import { initAccount } from './account.js';
import { initAdmin } from './admin.js';
import { applyResponsiveControlPositions, buildMarkers, setupMobileLayersPanel, syncMarkers } from './map.js';
import { initLightbox } from './lightbox.js';
import { initCramponView } from './crampon.js';
import { initLocateControl } from './locate.js';
import { initAppBridge } from './app-bridge.js';
import { loadAllGpx } from './gpx.js';
import { initPeakPanel } from './panel.js';
import { initSidebar, renderChipsAll, renderList } from './sidebar.js';

initPeakPanel();
initLightbox();
initCramponView();
initSidebar();
setupMobileLayersPanel();
initLocateControl();
initAppBridge();
applyResponsiveControlPositions();
window.addEventListener('resize', applyResponsiveControlPositions);

// Démarrage : qui est connecté ? puis catalogue + espace affiché. Un admin peut consulter
// l'espace d'un autre utilisateur via ?space=<identifiant> (lecture seule).
async function start() {
  const me = await apiGet('/api/me');
  const requested = new URLSearchParams(location.search).get('space');
  session.me = me;
  session.space = me.role === 'guest' ? null : (me.role === 'admin' && requested) || me.username;
  session.viewingOther = session.space !== null && session.space !== me.username;
  session.canEdit = session.space !== null && !session.viewingOther;
  document.body.classList.toggle('no-space', session.space === null);
  document.body.classList.toggle('readonly', !session.canEdit);
  initAccount();
  initAdmin();

  const query = session.viewingOther ? `?space=${encodeURIComponent(session.space)}` : '';
  const data = await apiGet(`/mountains.json${query}`);
  PEAKS.push(...data);
  PEAKS.filter(p => p.done).forEach(p => doneSet.add(p.name));
  buildMarkers();
  renderChipsAll();
  syncMarkers();
  renderList();
  loadAllGpx();
}

start().catch(err => {
  if (err.message === 'session expirée') return; // redirection vers /login en cours
  document.getElementById('list').innerHTML =
    `<div id="loading" class="error">Impossible de charger les données (${escapeHtml(err.message)}).<br><br>
     Vérifie ta connexion, ou que le serveur tourne bien.</div>`;
});

// PWA : service worker (démarrage instantané, hors-ligne partiel — voir /sw.js). Ignoré si le
// navigateur ne le gère pas, ou hors contexte sécurisé (http:// ailleurs que sur localhost).
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => {
    navigator.serviceWorker.register('/sw.js')
      .then(() => navigator.serviceWorker.ready)
      .then(reg => {
        // Les modules JS importés par main.js n'apparaissent pas dans le HTML : on transmet au
        // service worker tout ce que la page a réellement chargé sous /v/, pour le hors-ligne.
        const urls = performance.getEntriesByType('resource')
          .map(e => e.name)
          .filter(u => u.startsWith(`${location.origin}/v/`));
        reg.active?.postMessage({ type: 'cache-assets', urls });
      })
      .catch(err => console.warn('Service worker non enregistré :', err));
  });
}
