"""Exceptions propres au plugin."""

from __future__ import annotations


class ApiRequestError(Exception):
    """Erreur générique lors d'un appel à l'API d'extraction."""

    def __init__(self, method: str, url: str, status_code: int, body: bytes = b""):
        self.method = method
        self.url = url
        self.status_code = status_code
        self.body = body
        try:
            detail = body.decode("utf-8", "ignore")
        except Exception:
            detail = ""
        super().__init__(f"{method} {url} -> HTTP {status_code} : {detail}")


class AuthenticationError(Exception):
    """La configuration d'authentification est absente, invalide ou refusée."""


class JobFailedError(Exception):
    """Le job d'extraction s'est terminé en échec (FAILED) ou a été supprimé."""


class AdminBoundaryNotFoundError(Exception):
    """Aucune entité administrative ne correspond à la recherche."""
