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
- **Pyrénées** (retirés lors de l'audit critique du 2026-09-01, confirmés
  après une seconde vérification le 2026-09-01 — voir section 9) :
  - **Pic Perdiguère** (3222 m) — cheminée de 30 m cotée niveau II
    obligatoire (pas une variante évitable) juste après le col supérieur
    de Litérole, sur la voie directe.
  - **Pic du Balaïtous** (3144 m) — voie normale (Grande Diagonale) : PD,
    escalade finale II+, vire ascendante exposée avec 600 m de vide en
    contrebas, décrite comme nécessitant un "bon niveau montagne" même en
    conditions sèches.

  (Pic du Marboré, Pic de Batoua et Petit Vignemale, initialement retirés
  ici, ont été réintégrés après vérification — voir section 9 : le
  retrait reposait sur une confusion d'itinéraire ou de sommet.)

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

## 7. Audit critique du 2026-09-01

Suite à une demande explicite de vérification extrêmement critique, chaque
sommet de la liste a été réexaminé individuellement (recherche croisée
camptocamp.org quand accessible, sinon altituderando.com/visorando.com/
bivouak.net/skitour.fr/topopyrenees.com/outside.fr), en cherchant
spécifiquement des indices d'un terrain plus engagé que la cotation
affichée (corde/rappel, glacier obligatoire, escalade cotée II ou plus,
via ferrata).

**Résultat** : sur 43 sommets audités, **5 ont été retirés** (voie normale
en réalité alpinisme — détail section 4), **6 ont été recotés/reformulés**
suite à un terrain sous-estimé ou une saisonnalité mal reflétée :

- **Pointe de l'Observatoire** : T2 → T3 (dernier tronçon nécessite les
  mains).
- **Pic de la Farnéiréta** : T2 → T3 (cotation officielle "Moyen" — brefs
  passages aériens, hors-sentier par endroits, sens de l'orientation
  requis).
- **Mont Chaberton** : T2 → T3 (cotation officielle "Difficile" — hautes
  marches et prises de main nécessaires, notamment à la descente du col).
- **La Grande Fache** : T2 → T3 (passage niveau II sur les derniers
  350 m).
- **Pic de Néouvielle** : cotation T3 conservée mais note renforcée sur la
  fréquence réelle des névés/glace nécessitant crampons+piolet (pas
  seulement "en début de saison").
- **Grand Astazou** : cotation T4 conservée pour le sommet lui-même, mais
  note reformulée pour signaler que l'accès classique au refuge de
  Tuquerouye passe par un couloir raide (40-45°) souvent engagé —
  vérifier les conditions/une variante d'accès avant de partir.

Fait notable : 3 des 6 recotages concernent des sommets initialement en
**T2** ("facile") qui se sont révélés être en réalité des **T3** une fois
la cotation officielle vérifiée plutôt qu'un résumé de compte-rendu — un
schéma cohérent qui suggère que les T2 du reste de la liste méritent
d'être abordés avec un peu de prudence supplémentaire tant qu'ils n'ont
pas tous été vérifiés individuellement de cette façon.

Les **32 autres sommets ont été confirmés** sans changement. Deux cas
restent à surveiller (non modifiés, mais signalés par l'audit) :
- **Pointe d'Aval (Chauvet)** : une route cotée AD- existe dans le même
  secteur sous un nom proche — bien vérifier qu'on suit l'itinéraire de
  randonnée d'été classique et non cette variante.
- Les cotations qui reposent sur des comptes-rendus plutôt que sur une
  cotation CAS officielle camptocamp (la majorité — camptocamp.org est en
  grande partie inaccessible aux outils de recherche automatisés,
  contenu généré en JavaScript) restent, comme indiqué en section 3, des
  estimations à recouper avant une sortie réelle.

## 8. Balayage de complétude du 2026-09-01

Un second passage a cherché spécifiquement des sommets non-techniques
manquants dans des massifs jusque-là peu creusés (Beaufortain, Grandes
Rousses, Belledonne, Mercantour, Ossau, Couserans, Aure/Louron, Écrins
périphérie). **2 sommets supplémentaires vérifiés ajoutés** (40 au
total) :

- **La Mortice (sommet Nord)** (3186 m, Ubaye/Queyras) — traversée de
  crête depuis La Mortice (sommet Sud), déjà dans la liste.
- **Pic du Montcalm** (3077 m, Ariège) — souvent enchaîné avec la Pica
  d'Estats voisine, déjà dans la liste.

**Massifs vérifiés sans rien à ajouter** (point culminant sous 3000 m ou
sommets tous trop techniques) : Beaufortain (max 2995 m), Grandes Rousses
(Pic Bayle 3465 m mais glacier/crevasses sur toutes les voies), Belledonne
(max 2977 m), Ossau (max 2974 m), Couserans (max 2880 m). Au passage,
deux idées reçues corrigées : le Mont Mounier culmine en réalité à
**2817 m** (pas 3000 m+, contrairement à ce qu'affirment certains sites) ;
la Cime du Gélas (3143 m, Mercantour) est en réalité de l'alpinisme
(PD-, escalade III exposée) sur toutes les voies trouvées — les deux
n'ont jamais figuré dans cette liste, mais ne devraient pas y figurer par
erreur non plus.

**Candidat rejeté** : Pic du Maupas (3109 m, Luchonnais) — des résumés le
présentent comme facile, mais le topo détaillé le cote T6 avec escalade
I/II obligatoire hors-sentier. Exclu.

**Point de vigilance signalé ici, tranché en section 9** : la liste de
référence altituderando « sommets pyrénéens accessibles » incluait 3
sommets que l'audit critique (section 7) avait retirés (Pic du Marboré,
Pic de Batoua, Petit Vignemale). Un réexamen ciblé (section 9) a confirmé
que ce désaccord avait raison : les 3 ont été réintégrés après avoir
identifié la confusion d'itinéraire/de sommet à l'origine de leur retrait
initial.

## 9. Correction du 2026-09-01 : confusions d'itinéraire/de sommet

Suite à un signalement utilisateur pointant l'absence du Petit Vignemale,
les 5 sommets retirés en section 7 ont été réexaminés un par un avec des
sources supplémentaires (fetch direct de topos dédiés, pas seulement des
résumés). Résultat : **3 réintégrés, 2 confirmés retirés**.

**Réintégrés (l'exclusion reposait sur une confusion)** :

- **Petit Vignemale** (3032 m) : le retrait citait la voie "des Séracs"
  (glaciaire, PD+/III) — mais celle-ci mène en réalité au Grand Vignemale
  (Pique Longue, 3298 m), un sommet différent. Le Petit Vignemale a sa
  propre voie normale, via le refuge de Bayssellance et le col de la
  Hourquette d'Ossoue, confirmée non-technique (aucune difficulté par
  beau temps sec) par deux topos indépendants (altituderando.com,
  topopyrenees.com). Névés persistants possibles = prudence saisonnière,
  pas alpinisme.
- **Pic de Batoua** (3034 m, sommet occidental — celui de cette liste) :
  le retrait citait une cheminée de 5 m cotée II+ — mais celle-ci se
  trouve sur la crête *au-delà* du sommet occidental, en continuant vers
  le sommet oriental (un troisième sommet distinct du massif). Le sommet
  occidental (3034 m) s'atteint depuis le Pic de Cauarère en ~45 min sans
  jamais rencontrer cette cheminée (topopyrenees.com).
- **Pic du Marboré** (3248 m) : le retrait invoquait des névés/glace
  persistants — un problème saisonnier, pas un glacier permanent (le même
  argument avait pourtant justifié de *garder* le Pic de Néouvielle et le
  Grand Astazou avec une note plutôt que de les retirer — incohérence
  interne de l'audit initial). En conditions sèches d'été, la voie normale
  (refuge des Sarradets) ne nécessite ni corde ni piolet permanents ;
  deux courts passages d'escalade facile (II+, mains) restent dans la
  tolérance déjà admise ailleurs dans cette liste (T4, comparer à la
  Pointe de la Grande Sassière ou Ouille Noire).

**Confirmés retirés (l'exclusion tient après réexamen)** :

- **Pic Perdiguère** : une cheminée de 30 m cotée II reste décrite comme
  faisant partie de la voie directe après le col supérieur de Litérole,
  "pas une variante" (topopyrenees.com, citation explicite). Une mention
  annexe évoque un aller-retour "sans difficulté particulière" depuis le
  refuge d'Arlaud — non recoupée en détail, donc gardé comme retiré par
  prudence, mais c'est une piste à vérifier si tu veux challenger cette
  décision plus loin.
- **Pic du Balaïtous** : voie normale (Grande Diagonale) cotée PD avec
  escalade II+ finale et une vire exposée dominant 600 m de vide,
  qualifiée ailleurs de "nécessitant un bon niveau montagne" même par
  beau temps sec — plus engagé et plus sérieux que les cas réintégrés
  ci-dessus (exposition sostenue, pas juste un ou deux pas de II).

**Leçon retenue** : deux des trois erreurs initiales venaient de citer la
difficulté d'un *itinéraire ou sommet voisin* plutôt que celle du sommet
réellement listé (même schéma que l'ambiguïté déjà signalée pour la
Pointe d'Aval/Chauvet en section 7) — un piège à surveiller pour toute
future vérification, en particulier pour les massifs avec plusieurs
sommets homonymes ou très proches (Vignemale, Batoua, Marboré/Casque du
Marboré).

**43 sommets au total à ce stade.**

## 10. Lien source par sommet + ajout du Râteau d'Aussois (2026-09-02)

Chaque entrée de `mountains.json` porte désormais un champ `source_url`
pointant vers la page précise (topo/compte-rendu) qui a servi à établir sa
cotation — affiché en hyperlien cliquable dans le panneau "Détail de la
cotation" de la carte. Recherché sommet par sommet (recherches web ciblées,
sans délégation à des agents cette fois — cf. section 9 pour le contexte
de cet arbitrage), 44/44 entrées ont une URL vérifiée.

Au passage, un sommet supplémentaire a été trouvé et ajouté :

- **Râteau d'Aussois** (3131 m, Vanoise) : plateau sommital cairné,
  accessible par un bon chemin ; recherche de passage dans les rochers
  sur les derniers mètres après le col de la Masse, aucune difficulté
  d'escalade ni glacier. Source : randonnees-en-maurienne.fr.

**Candidat examiné mais non ajouté** : les pics de Clarabide (3020 m) et
de Gias (3011 m), vallée du Louron — cotés "Difficile" avec une cheminée
non cotée à escalader vers Gias, mains nécessaires sur pierrier instable,
mais sans glacier ni corde. Non ajoutés faute de coordonnées de sommet
fiables (recherche Nominatim infructueuse sous ces noms français — les
toponymes locaux/espagnols diffèrent). À revisiter si des coordonnées
précises sont trouvées.

**44 sommets au total désormais.**
