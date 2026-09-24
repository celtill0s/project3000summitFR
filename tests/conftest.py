import sys
from pathlib import Path

# Permet `from server import app` quel que soit le répertoire depuis lequel pytest est lancé.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server import auth  # noqa: E402

# Tests : scrypt allégé (la vérification relit les paramètres stockés dans l'empreinte, donc les
# mots de passe hachés ainsi restent vérifiables normalement).
auth.SCRYPT_N = 2 ** 10
