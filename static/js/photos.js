// Photos/vidéos d'un sommet : grille de miniatures, upload, suppression.
import { escapeHtml, isVideoFile } from './util.js';
import { apiDelete, apiUpload, mediaUrls, peakApiBase } from './api.js';
import { openLightbox } from './lightbox.js';

function mediaThumbHtml(key, urls, isVideo, alt, deleteBtnHtml) {
  const mediaTag = isVideo
    ? `<video src="${urls.thumb}" muted playsinline preload="metadata"></video><span class="photos-play">&#9658;</span>`
    : `<img src="${urls.thumb}" loading="lazy" alt="${escapeHtml(alt)}" />`;
  return `<div class="photos-thumb" data-id="${escapeHtml(key)}" data-full="${urls.full}" data-video="${isVideo ? '1' : '0'}">${mediaTag}${deleteBtnHtml || ''}</div>`;
}

function lightboxItems(thumbs) {
  return thumbs.map(t => ({ src: t.dataset.full, isVideo: t.dataset.video === '1' }));
}

// Toutes les photos/vidéos viennent désormais du serveur (URLs réelles, /photos/<id>/<fichier>) :
// plus de distinction "importé en local (Blob)" vs "fourni par le dépôt", une seule source de vérité.
function renderPhotosGrid(p, grid, highlightKeys) {
  highlightKeys = highlightKeys || [];
  let html = '';
  (p.photos || []).forEach(filename => {
    const key = `repo:${filename}`;
    const delBtn = `<button type="button" class="photo-del" data-filename="${escapeHtml(filename)}" title="Supprimer">&#10005;</button>`;
    html += mediaThumbHtml(key, mediaUrls(p, filename), isVideoFile(filename), p.name, delBtn);
  });
  grid.innerHTML = html || '<div class="gpx-status">Aucune photo ou vidéo pour l\'instant.</div>';
  const thumbs = [...grid.querySelectorAll('.photos-thumb')];
  thumbs.forEach((thumb, idx) => {
    thumb.addEventListener('click', (e) => {
      if (e.target.closest('.photo-del')) return;
      openLightbox(lightboxItems(thumbs), idx, p.name);
    });
  });
  grid.querySelectorAll('.photo-del').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.stopPropagation();
      const statusEl = grid.parentElement.querySelector('.photos-status');
      const filename = btn.dataset.filename;
      try {
        await apiDelete(`${peakApiBase(p)}/photos/${encodeURIComponent(filename)}`);
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

export function photosRowHtml(p) {
  return `<div class="photos-row" data-id="${escapeHtml(p.id)}">
    <div class="photos-label">📷 Photos &amp; vidéos</div>
    <div class="photos-grid"></div>
    <button type="button" class="gpx-btn photos-add">➕ Ajouter des photos/vidéos</button>
    <input type="file" class="photos-file-input" accept="image/*,video/*" multiple hidden />
    <div class="gpx-status photos-status"></div>
  </div>`;
}

export function bindPhotosRow(root, p) {
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
        const result = await apiUpload(`${peakApiBase(p)}/photos`, file);
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
        openLightbox(lightboxItems(thumbs), idx, p.name);
      }
    }
  });
  renderPhotosGrid(p, grid);
}
