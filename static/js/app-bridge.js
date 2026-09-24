// Intégration avec l'appli Android (android/) : inactive dans un navigateur normal. L'appli
// expose window.SommetsApp (pont natif) et appelle window.__appBack() au bouton retour.

export const nativeApp = window.SommetsApp || null;

// Bouton retour Android : ferme d'abord ce qui est ouvert, du plus « au-dessus » au plus en
// dessous, en cliquant sur les boutons de fermeture existants. Renvoie false s'il n'y avait rien
// à fermer (l'appli quitte alors).
const CLOSABLES = [
  ['#photo-lightbox:not([hidden])', '#photo-lightbox-close'],
  ['#crampon-view:not([hidden])', '#crampon-view-close'],
  ['.leaflet-control-layers-expanded', '.leaflet-control-layers-close'],
  ['#peak-panel:not([hidden])', '#peak-panel-close'],
  ['#app.mobile-list-open', '#mobile-list-toggle'],
];

function appBack() {
  for (const [openSelector, closeSelector] of CLOSABLES) {
    const closeBtn = document.querySelector(openSelector) && document.querySelector(closeSelector);
    if (closeBtn) {
      closeBtn.click();
      return true;
    }
  }
  return false;
}

// Fichier généré par la page (trace GPX) → « Téléchargements » du téléphone : la vue web de
// l'appli ne sait pas enregistrer un lien blob: comme le ferait un navigateur.
export function saveFileNatively(filename, mimeType, text) {
  const bytes = new TextEncoder().encode(text);
  let binary = '';
  for (let i = 0; i < bytes.length; i += 0x8000) binary += String.fromCharCode(...bytes.subarray(i, i + 0x8000));
  return nativeApp.saveFile(filename, mimeType, btoa(binary));
}

export function initAppBridge() {
  if (!nativeApp) return;
  window.__appBack = appBack;
  const logout = document.getElementById('app-logout');
  logout.hidden = false;
  logout.addEventListener('click', () => {
    if (confirm('Se déconnecter ? Le mot de passe sera redemandé au prochain lancement.')) nativeApp.logout();
  });
}
