# Sources et méthodologie

Ce document explique comment chaque sommet listé dans `mountains.json` a été
sélectionné et coté, et avec quelles sources.

## 1. Périmètre

- **Zone géographique** : Alpes françaises + Pyrénées françaises (les deux
  seuls massifs métropolitains dépassant 3000 m — Corse : 2706 m, Massif
  central : 1886 m, Vosges : 1424 m, Jura : 1720 m).
- **Altitude** : sommets ≥ 3000 m.
- **Accessibilité** : uniquement des sommets atteignables **à pied, sans
  matériel technique d'alpinisme** — pas de passage glaciaire obligatoire,
  pas de corde/encordement, pas de via ferrata équipée. Un peu de rocher
  facile (mains posées, pas d'escalade franche) est toléré jusqu'à la
  cotation T4.

## 2. Barème de cotation utilisé

Toutes les fiches utilisent la **même échelle**, l'échelle de randonnée
CAS/SAC (Club Alpin Suisse), référence standard reprise par la plupart des
topoguides et sites francophones (camptocamp.org, FFRandonnée, etc.) :

| Cotation | Signification | Terrain type |
|---|---|---|
| T1 | Randonnée | Sentier bien tracé, aucun risque de chute |
| T2 | Randonnée montagne | Sentier parfois raide, un peu de terrain irrégulier |
| T3 | Randonnée exigeante | Sentier étroit/exposé par endroits, mains parfois nécessaires |
| T4 | Randonnée alpine | Hors-sentier possible, rocher facile, exposition, terrain non assuré |
| T5+ | Alpinisme | Escalade, corde, glacier — **exclu de cette liste** |

Seuls des sommets cotés **T2 à T4** figurent dans `mountains.json`. Aucun T5+
n'est inclus.

## 3. Comment la cotation de chaque sommet a été déterminée

Pour chaque sommet, la cotation et les notes d'accès ont été établies par
recherche croisée sur des sites de randonnée francophones de référence,
indiqués individuellement dans le champ `"source"` de chaque entrée de
`mountains.json` :

- **ffrandonnee.fr** — Fédération française de la randonnée pédestre,
  fiches itinéraires officielles.
- **altituderando.com** — site de comptes-rendus de randonnées/sommets en
  France, très complet sur les 3000 m alpins et pyrénéens, souvent avec
  photos du terrain et retours d'expérience qui permettent d'évaluer
  l'engagement réel.
- **outside.fr** — magazine outdoor, articles dédiés aux "3000 pyrénéens
  accessibles sans alpinisme".
- **hexatrek.com** — contenu rando/trek longue distance, utilisé pour
  quelques sommets alpins (Mont Buet, Aiguille de la Grande Sassière, Mont
  Chaberton).
- **bivouak.net**, **skitour.fr**, **pyrandonnees.fr** — sites de topos et
  comptes-rendus, utilisés en complément lors d'une recherche de suivi pour
  compléter le secteur du Queyras.

**Important — degré de confiance** : pour la majorité des sommets, la
cotation T2/T3/T4 est une **estimation construite à partir de la
description du terrain** trouvée sur ces sites (type de sentier, passages
rocheux mentionnés, exposition, présence de névés), et non une cotation
CAS/SAC officielle vérifiée pic par pic sur camptocamp.org. Ce n'est donc
pas un niveau de certification alpine, mais une aide au tri/à la
priorisation. **Avant une sortie réelle**, recroiser la cotation avec :
- une recherche dédiée sur [camptocamp.org](https://www.camptocamp.org)
  (topos avec cotation CAS officielle et commentaires à jour),
- les conditions du moment (les névés en début de saison peuvent rendre un
  T3 "sur le papier" plus engagé qu'un T4 sec en fin d'été),
- une carte IGN au 1:25000 de l'itinéraire.

## 4. Sommets volontairement exclus

Des sommets > 3000 m bien connus ont été **exclus** de la liste car leur
voie normale nécessite réellement de l'alpinisme (glacier, corde, via
ferrata équipée) :

- **Pic d'Aneto** (3404 m, côté espagnol) — glacier obligatoire.
- **Posets** (3375 m, côté espagnol) — glacier/névé engagé.
- **Mont Perdu** côté espagnol — très engagé, souvent glacier résiduel.
- **Casque du Marboré** — équipé de chaînes (via ferrata).
- Les grands sommets du massif du Mont-Blanc et des Écrins (Barre des
  Écrins, Dôme de Neige des Écrins, Grande Casse, Mont Pourri, Grande
  Motte, Meije, etc.) — glacier et/ou corde obligatoires sur la voie
  normale.
- **Massif du Néouvielle** : Pic Long (3192 m, arête NE cotée AD+/IV avec
  rappels), Pic Badet (3160 m, passages II/III) et l'Aiguille Badet — de
  l'alpinisme réel malgré des résumés parfois rassurants, exclus après
  vérification.
- **Chambeyron** : Brec de Chambeyron (3389 m, PD, rappels de 45-50 m) et
  Aiguille de Chambeyron (3412 m, PD, couloir à 40-45°) — alpinisme
  confirmé.
- **Queyras** : Rochebrune (3320 m, escalade II, cordes fixes) et Rocca
  Bianca (3059 m, PD, escalade I sup./II inf., cordes fixes) — trop
  techniques malgré des comptes-rendus initiaux plus optimistes.

## 5. Coordonnées

Les coordonnées (`lat`/`lon`) ont été géocodées via OpenStreetMap/Nominatim
à partir du nom du sommet et, quand nécessaire, du massif pour lever les
ambiguïtés (plusieurs sommets homonymes existent en France). Elles pointent
vers le sommet lui-même, à la précision permise par les données
OpenStreetMap disponibles pour chaque point coté.

## 6. Limites connues

- Une recherche de suivi (2026-09-01) a vérifié spécifiquement les massifs
  du Néouvielle et de l'Ubaye/Queyras, initialement cités comme
  potentiellement sous-représentés. Résultat : le Néouvielle et l'Ubaye
  étaient déjà couverts pour ce qui est réellement non-technique — les
  candidats supplémentaires plausibles (Pic Long, Pic Badet, Brec/Aiguille
  de Chambeyron) se sont révélés être de l'alpinisme confirmé une fois
  vérifiés (voir section 4). Le Queyras avait en revanche 5 sommets
  supplémentaires réellement accessibles, ajoutés à la liste (Tête de la
  Cula, Tête de Longet, Pointe Joanne, Grand Queyras, Pointe des Sagnes
  Longues).
- La liste reste **indicative, pas garantie exhaustive à 100 %** : malgré
  cette vérification, d'autres 3000 m confidentiels peuvent exister et ne
  pas encore être répertoriés ici.
- Les cotations sont indicatives et peuvent nécessiter un ajustement selon
  la saison, l'enneigement et la météo du jour.
- Toute contribution/correction est bienvenue en éditant `mountains.json`
  (même structure de champs) — merci d'indiquer la source utilisée dans le
  champ `"source"` de la nouvelle entrée.
