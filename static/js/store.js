// État partagé : catalogue chargé, sommets faits, filtres actifs.
import { DIFFS, REGIONS } from './config.js';

export const PEAKS = [];
export const doneSet = new Set();

export const state = {
  regions: new Set(REGIONS),
  difficulties: new Set(DIFFS),
  status: 'Tous',
  query: ''
};

export function passesBaseFilter(p) {
  if (!state.regions.has(p.region)) return false;
  if (!state.difficulties.has(p.difficulty)) return false;
  if (state.status === 'Fait' && !doneSet.has(p.name)) return false;
  if (state.status === 'À faire' && doneSet.has(p.name)) return false;
  if (state.query) {
    const q = state.query.toLowerCase();
    if (!(p.name.toLowerCase().includes(q) || p.massif.toLowerCase().includes(q))) return false;
  }
  return true;
}
