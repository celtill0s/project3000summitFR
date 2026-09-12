FROM python:3.13-slim
WORKDIR /app
COPY static/ ./static/
COPY server/ ./server/
ENV PORT=8000 \
    DATA_DIR=/data \
    STATIC_DIR=/app/static
# Tourne en utilisateur non-root (uid/gid 1000, aligné sur l'utilisateur hôte qui possède le
# bind-mount ./data) : un éventuel bug d'écriture/traversal reste confiné à cet utilisateur,
# pas root dans le conteneur.
RUN groupadd -g 1000 app && useradd -u 1000 -g 1000 -M -s /usr/sbin/nologin app
USER app
EXPOSE 8000
CMD ["python3", "server/app.py"]
