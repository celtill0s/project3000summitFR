"""Erreur renvoyée au client : statut HTTP + message (jamais de détail interne)."""


class ApiError(Exception):
    def __init__(self, status, message, headers=None, extra=None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.headers = headers or {}
        self.extra = extra or {}
