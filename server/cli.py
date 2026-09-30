"""Commandes d'administration en ligne de commande, et migration des données d'avant les
comptes (un seul espace, à la racine de data/)."""
import getpass
import os
from pathlib import Path

from . import auth, storage

LEGACY_ITEMS = ("progress.json", "photos", "gpx", "thumbs")


def _non_empty(path: Path) -> bool:
    return path.is_file() or (path.is_dir() and any(path.iterdir()))


def legacy_data_present() -> bool:
    return any(_non_empty(storage.DATA_DIR / name) for name in LEGACY_ITEMS)


def migrate_legacy_to(username: str) -> list:
    """Déplace data/progress.json, photos/, gpx/, thumbs/ dans data/users/<username>/.
    Renvoie la liste des éléments déplacés ; ne remplace jamais un élément existant."""
    dest = storage.user_dir(username)
    dest.mkdir(parents=True, exist_ok=True)
    moved = []
    for name in LEGACY_ITEMS:
        src = storage.DATA_DIR / name
        if not _non_empty(src):
            continue
        if _non_empty(dest / name):
            raise RuntimeError(f"{dest / name} existe déjà : migration interrompue, rien n'est écrasé")
        if (dest / name).is_dir():
            (dest / name).rmdir()
        os.replace(src, dest / name)
        moved.append(name)
    if (dest / "progress.json").exists():
        # progress.json d'avant les ids (indexé par nom de sommet) : converti au passage.
        storage.save_progress(username, storage.load_progress(username))
    return moved


def _prompt_password(label="Mot de passe") -> str:
    while True:
        pw = getpass.getpass(f"{label} ({auth.MIN_PASSWORD_LENGTH} caractères minimum) : ")
        try:
            auth.validate_password(pw)
        except ValueError as e:
            print(f"  {e}")
            continue
        if getpass.getpass("Confirmation : ") == pw:
            return pw
        print("  les deux saisies diffèrent, recommence")


def cli(argv) -> int:
    """Commandes d'administration, à lancer sur le serveur :
      python3 server/app.py create-admin <identifiant>   crée un compte admin (et y rattache les
                                                         données d'avant les comptes, s'il y en a)
      python3 server/app.py set-password <identifiant>   réinitialise un mot de passe (secours)
      python3 server/app.py list-users
    (avec Docker : docker compose exec app python3 server/app.py …)"""
    if not argv or argv[0] not in ("create-admin", "set-password", "list-users"):
        print(cli.__doc__)
        return 2
    store = storage.users_store()
    try:
        if argv[0] == "list-users":
            for u, d in sorted(store.all().items()):
                print(f"{u:32s} {d['role']}")
            return 0
        if len(argv) != 2:
            print(cli.__doc__)
            return 2
        username = auth.validate_username(argv[1].strip().lower())
        if argv[0] == "create-admin":
            store.create(username, _prompt_password(), "admin")
            print(f"✓ compte administrateur « {username} » créé")
            if legacy_data_present():
                moved = migrate_legacy_to(username)
                print(f"✓ données existantes rattachées à « {username} » : {', '.join(moved)}")
        else:
            if not store.get(username):
                print(f"utilisateur « {username} » inconnu")
                return 1
            store.set_password(username, _prompt_password("Nouveau mot de passe"))
            storage.sessions_store().revoke_user(username)
            print(f"✓ mot de passe de « {username} » changé (ses sessions ouvertes sont fermées)")
        return 0
    except (ValueError, RuntimeError) as e:
        print(f"erreur : {e}")
        return 1
