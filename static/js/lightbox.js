// Visionneuse plein écran des photos/vidéos d'un sommet.
import { escapeHtml } from './util.js';

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

export function openLightbox(items, index, alt) {
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

export function initLightbox() {
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
