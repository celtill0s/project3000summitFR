// Constantes d'affichage : cotations, régions, statuts, détection mobile.
export const DIFF_COLORS = { T2: '#2e8b57', T3: '#d98c1e', T4: '#c0392b' };
export const DIFF_LABELS = {
  T2: 'T2 · Randonnée montagne',
  T3: 'T3 · Randonnée exigeante',
  T4: 'T4 · Randonnée alpine (léger hors-sentier / rocher facile)'
};
// Critères génériques de l'échelle de randonnée CAS/SAC (cf. sources.md) — non spécifiques à un sommet.
export const DIFF_CRITERIA = {
  T2: 'Sentier parfois raide, terrain par endroits irrégulier. Un minimum d\'expérience de la marche en montagne suffit, pas d\'exposition notable.',
  T3: 'Sentier étroit et/ou exposé par endroits, les mains peuvent être nécessaires ponctuellement. Terrain jugé sûr par tout temps sec, plus engagé si mouillé/enneigé.',
  T4: 'Passages hors-sentier possibles, rocher facile (mains posées, pas d\'escalade franche), terrain non assuré et exposition réelle en cas de chute — mais toujours sans corde ni matériel d\'alpinisme.'
};
export const REGIONS = ['Alpes', 'Pyrénées'];
export const DIFFS = ['T2', 'T3', 'T4'];
export const STATUSES = ['Tous', 'Fait', 'À faire'];

// Replié par défaut sur mobile (petit bouton natif Leaflet, stylé en flèche via CSS — voir
// .leaflet-control-layers-toggle), toujours déplié sur desktop comme avant. Déterminé une
// seule fois au chargement : le mode replié/déplié de Leaflet se fixe à la création du
// contrôle, pas dynamiquement — cohérent avec un usage réel (on ne redimensionne pas son
// navigateur au-delà du seuil de 760px en cours d'usage). Ne reste plus que la trace GPX ici,
// la difficulté étant désormais gérée par les puces de la barre latérale (voir plus haut).
export const startsMobile = window.matchMedia('(max-width: 760px)').matches;
