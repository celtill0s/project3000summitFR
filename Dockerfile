FROM python:3.13-slim
WORKDIR /app
# Pillow + pillow-heif (miniatures, HEIC -> JPEG) : roues précompilées dispo en amd64 et arm64
# (Raspberry Pi 64 bits), rien à compiler.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY static/ ./static/
COPY server/ ./server/
ENV PORT=8000 \
    DATA_DIR=/data \
    STATIC_DIR=/app/static \
    PYTHONUNBUFFERED=1
# Tourne en utilisateur non-root (uid/gid 1000, aligné sur l'utilisateur hôte qui possède le
# bind-mount ./data) : un éventuel bug d'écriture/traversal reste confiné à cet utilisateur,
# pas root dans le conteneur.
RUN groupadd -g 1000 app && useradd -u 1000 -g 1000 -M -s /usr/sbin/nologin app \
    && mkdir -p /data && chown app:app /data
# /data pré-créé et possédé par app : l'image démarre même sans volume (CI, test rapide).
# En production, le bind-mount ./data le remplace — ce dossier hôte doit appartenir à l'uid 1000.
USER app
EXPOSE 8000
CMD ["python3", "server/app.py"]
