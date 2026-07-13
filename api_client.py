#!/usr/bin/env python3
"""
Client HTTP minimale per chiamate POST autenticate con token JWT.

Imposta l'header Authorization: Bearer <token>, invia il corpo come JSON e
distingue tra risposte di successo (2xx) ed errore (4xx/5xx), sollevando
un'eccezione dedicata quando la richiesta non va a buon fine.
"""

import logging

import requests

logger = logging.getLogger(__name__)


class ApiError(Exception):
    """
    Errore restituito dall'API o dal livello di trasporto.

    Attributes:
        status_code: codice HTTP della risposta (None se la richiesta non è
            nemmeno partita, es. timeout o errore di rete).
        payload: corpo della risposta decodificato (dict) o testo grezzo.
    """

    def __init__(self, message: str, status_code: int = None, payload=None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload


def post_json(url: str, token: str, body: dict, timeout: float = 10.0) -> dict:
    """
    Esegue una POST JSON autenticata con token Bearer.

    Args:
        url: endpoint dell'API.
        token: token JWT da inserire nell'header Authorization.
        body: dizionario da serializzare come corpo JSON.
        timeout: timeout della richiesta in secondi.

    Returns:
        Il corpo della risposta decodificato come dizionario (in caso di 2xx).

    Raises:
        ApiError: se la risposta ha status di errore (>= 400) o se la
            richiesta fallisce a livello di rete.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        # `json=body` serializza il dizionario e imposta il Content-Type,
        # ma lo teniamo esplicito sopra per chiarezza.
        response = requests.post(url, json=body, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        # Errori di trasporto: DNS, connessione rifiutata, timeout, ecc.
        logger.error("Richiesta a %s fallita: %s", url, exc)
        raise ApiError(f"Errore di rete verso {url}: {exc}") from exc

    # Prova a decodificare il corpo come JSON; se non è JSON, tieni il testo.
    try:
        data = response.json()
    except ValueError:
        data = response.text

    if response.status_code == 200:
        logger.info("POST %s -> 200 OK", url)
        return data

    if response.status_code == 400:
        logger.warning("POST %s -> 400 Bad Request: %s", url, data)
        raise ApiError(
            "Richiesta rifiutata dall'API (400 Bad Request)",
            status_code=400,
            payload=data,
        )

    # Qualsiasi altro status di errore (401, 403, 409, 5xx, ...).
    if response.status_code >= 400:
        logger.error("POST %s -> %s: %s", url, response.status_code, data)
        raise ApiError(
            f"Risposta di errore dall'API ({response.status_code})",
            status_code=response.status_code,
            payload=data,
        )

    # Successi diversi da 200 (201 Created, 204 No Content, ...).
    logger.info("POST %s -> %s", url, response.status_code)
    return data if isinstance(data, dict) else {}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Esempio d'uso (endpoint fittizio che riflette il payload inviato).
    try:
        result = post_json(
            url="https://httpbin.org/post",
            token="eyJhbGciOi...jwt-di-esempio",
            body={"hello": "world"},
        )
        print("Successo:", result.get("json"))
    except ApiError as err:
        print(f"Errore ({err.status_code}): {err} | payload={err.payload}")
