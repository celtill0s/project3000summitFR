// Traces GPX : parsing, statistiques, profil altimétrique, import/export.
import { escapeHtml } from './util.js';
import { PEAKS } from './store.js';
import { apiDelete, apiUpload, peakApiBase } from './api.js';
import { gpxLayer, map } from './map.js';
import { activePeakName } from './panel.js';

// --- GPX : uploadée vers le serveur, servie ensuite depuis /gpx/<id>.gpx (une seule source de
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
    line.bindTooltip(escapeHtml(p.name), { sticky: true });
    gpxLayer.addLayer(line);
  });
  gpxPolylines.set(p.name, lines);
  const stats = computeGpxStats(segments);
  gpxData.set(p.name, stats);
  gpxRawText.set(p.name, gpxText);
  return lines;
}

function downloadGpx(p) {
  const text = gpxRawText.get(p.name);
  if (!text) return;
  const blob = new Blob([text], { type: 'application/gpx+xml' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = `${p.id}.gpx`;
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
      await apiUpload(`${peakApiBase(p)}/gpx`, file);
      p.gpx = `/gpx/${encodeURIComponent(p.id)}.gpx`;
      refreshGpxRow(p);
      // La ligne GPX vient d'être régénérée : le message va dans son nouvel élément de statut.
      const newStatusEl = document.querySelector('#peak-panel-body .gpx-import-status');
      if (newStatusEl) newStatusEl.textContent = 'Trace enregistrée sur le serveur.';
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
    await apiDelete(`${peakApiBase(p)}/gpx`);
  } catch (err) {
    // La trace est toujours sur le serveur : on la laisse affichée.
    if (row) row.textContent = `Échec de la suppression (${err.message}).`;
    return;
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

export function gpxRowHtml(p) {
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
  return `<div class="gpx-row" data-id="${escapeHtml(p.id)}">${body}</div>`;
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

export function bindGpxRow(root, p) {
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

export function loadAllGpx() {
  PEAKS.forEach(p => { if (p.gpx) loadRepoGpx(p); });
}
