# Appli Android

Appli Android autonome qui affiche la carte de ton instance dans une vue web intégrée. Elle ne
dépend d'**aucun navigateur** installé sur le téléphone (Chrome, Brave, DuckDuckGo… peu importe).

## Fonctionnement

- **Écran de connexion** au premier lancement : adresse du serveur (à saisir une fois, puis
  mémorisée ; le même APK fonctionne avec n'importe quelle instance) + identifiant et mot de
  passe du **compte du site** (voir « Comptes et rôles » dans le README principal). L'appli
  se connecte au serveur, puis ne garde que le **jeton de session** — jamais le mot de passe —,
  chiffré avec une clé du coffre Android (AndroidKeyStore) et exclu des sauvegardes. Les droits
  sont ceux du compte : un invité ne voit que le catalogue, un membre son propre espace.
- **Session** : le jeton est confié à la vue web (cookie), qui l'envoie seule avec chaque
  requête, y compris celles du service worker : le **hors-ligne** fonctionne (voir le README
  principal). Si la session prend fin (mot de passe changé, compte supprimé, déconnexion depuis
  un autre appareil), l'appli revient d'elle-même à l'écran de connexion, avec une explication.
- **Fonctions natives** : envoi de photos, vidéos et GPX (sélecteur Android), bouton « me
  localiser » (autorisation GPS demandée au premier appui), enregistrement des traces GPX dans
  « Téléchargements », vidéos en plein écran, liens externes (Google Maps, sources) ouverts dans
  les applis correspondantes, bouton retour qui ferme la visionneuse ou le panneau avant de
  quitter, icône « porte de sortie » en haut à droite de la carte pour se déconnecter
  (native : fonctionne quelle que soit la version du site ; cachée quand la visionneuse, la vue
  crampons ou la liste plein écran sont ouvertes, pour ne pas masquer leur bouton de fermeture).
- Le contenu (carte, fonctionnalités) vient du serveur : il se met à jour avec `update.sh`, sans
  réinstaller l'APK. Une nouvelle version de l'APK n'est utile que si l'appli elle-même change.
- Android 10 minimum. HTTPS obligatoire (le mot de passe accompagne chaque requête).

## Installer sur un téléphone

Page **Releases** du dépôt GitHub → télécharger `sommets3000-X.Y.Z.apk` → l'ouvrir sur le
téléphone. Android demande d'autoriser l'installation d'applis « de sources inconnues » pour le
navigateur ou le gestionnaire de fichiers utilisé. Une nouvelle version s'installe par-dessus
l'ancienne, sans perdre la connexion.

## Publier une release

Pousser un tag déclenche `.github/workflows/release.yml`, qui construit l'APK, le signe et
l'attache à une Release GitHub. Il faut d'abord, **une seule fois**, créer la clé de signature
et la confier à GitHub (étapes 1 et 2).

Circuit : on développe sur la branche **`devel`**, on publie une **bêta** depuis `devel` pour
tester sur le téléphone, puis on fusionne dans **`main`** — ce que le serveur déploie
(`update.sh`) — et on publie la **version finale** depuis `main`.

### 1. Créer la clé de signature (une fois pour toutes)

```bash
docker run --rm -it -v "$PWD":/out eclipse-temurin:17-jdk keytool -genkeypair \
  -keystore /out/sommets3000-release.jks -alias sommets3000 \
  -keyalg RSA -keysize 4096 -validity 10000 -dname "CN=Sommets 3000"
```

`keytool` demande un mot de passe : c'est à la fois celui du fichier et celui de la clé (le
format PKCS12 utilisé par défaut n'en gère qu'un seul).

> ⚠️ **Sauvegarde ce fichier `.jks` et son mot de passe en lieu sûr** (gestionnaire de mots de
> passe, clé USB…), et ne le commite jamais (il est dans `android/.gitignore`). Android
> n'accepte une mise à jour que si elle est signée par la **même** clé : s'il est perdu, il
> faudra désinstaller l'appli (et se reconnecter) avant d'installer une version signée avec une
> nouvelle clé.

### 2. Ajouter les secrets au dépôt GitHub

Settings → Secrets and variables → Actions → **New repository secret** :

| Secret | Valeur |
|---|---|
| `ANDROID_KEYSTORE_BASE64` | le fichier encodé : `base64 -w0 sommets3000-release.jks` |
| `ANDROID_KEYSTORE_PASSWORD` | le mot de passe choisi à l'étape 1 |
| `ANDROID_KEY_ALIAS` | `sommets3000` |
| `ANDROID_KEY_PASSWORD` | le même mot de passe |

Optionnel, onglet **Variables** : `DEFAULT_SERVER_URL` = adresse de ton instance, préremplie
sur l'écran de connexion. Sans elle, le champ est vide et l'adresse se saisit une fois. À savoir :
l'APK publié dans les Releases est public, et une adresse préremplie y est lisible par qui le
télécharge. Aucune adresse d'instance n'est écrite dans le code du dépôt.

### 3. Publier une bêta (depuis `devel`)

```bash
git switch devel
git tag v1.0.0-beta.1
git push origin v1.0.0-beta.1
```

Quelques minutes plus tard, une Release marquée **pré-version** apparaît avec l'APK. Bêtas
suivantes : `v1.0.0-beta.2`, `-beta.3`… (jusqu'à 98).

> L'APK n'est qu'une coquille : la carte vient du serveur, donc de `main`. Une bêta testée
> contre le serveur de production valide la partie native (connexion, hors-ligne, GPS,
> photos, déconnexion…), mais les ajouts côté site pour l'appli (`static/js/app-bridge.js` :
> bouton retour, enregistrement des GPX) n'y sont actifs qu'une fois fusionnés dans `main` et
> déployés.

### 4. Publier la version finale (depuis `main`)

```bash
git switch main
git merge devel
git push origin main          # puis ./update.sh sur le serveur
git tag v1.0.0
git push origin v1.0.0
```

Numéro de version Android, dérivé du tag, toujours croissant : `v1.0.0-beta.1` → 1000001,
`v1.0.0-beta.2` → 1000002, `v1.0.0` → 1000099, `v1.0.1-beta.1` → 1000101… La version finale
passe donc après ses bêtas, et chaque version s'installe par-dessus la précédente (bêtas et
finales sont signées avec la même clé). Un tag mal formé est refusé par le workflow.

## Construire en local

Avec Android Studio (ouvrir le dossier `android/`), ou en ligne de commande avec un JDK 17 et le
SDK Android : `./gradlew assembleDebug` → `app/build/outputs/apk/debug/app-debug.apk`.

Les builds de **debug** acceptent en plus `http://localhost:8080` comme adresse, pour tester
contre une instance locale depuis un émulateur (`adb reverse tcp:8080 tcp:8080`), et activent le
débogage de la vue web (`chrome://inspect`). Rien de tout ça dans l'APK de release.
