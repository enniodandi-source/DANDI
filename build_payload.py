#!/usr/bin/env python3
"""
Costruzione del payload JSON per la registrazione di utenti di test.

Genera dati anagrafici fittizi (nome, cognome, data di nascita) e assembla
il dizionario da inviare all'API di registrazione. I token (captcha e access
token) vengono forniti dall'esterno e inseriti così come sono.
"""

import random
import logging
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# Liste di nomi/cognomi per generare identità fittizie senza dipendenze esterne.
_FIRST_NAMES = [
    "Marco", "Giulia", "Luca", "Sara", "Andrea", "Chiara", "Matteo",
    "Francesca", "Alessandro", "Valentina", "Davide", "Elena",
]
_LAST_NAMES = [
    "Rossi", "Bianchi", "Ferrari", "Russo", "Romano", "Gallo",
    "Costa", "Fontana", "Conti", "Esposito", "Ricci", "Bruno",
]


def _random_birth_date(min_age: int = 18, max_age: int = 75) -> str:
    """
    Genera una data di nascita casuale coerente con un'età plausibile.

    Args:
        min_age: età minima (default 18).
        max_age: età massima (default 75).

    Returns:
        La data nel formato YYYY-MM-DD.
    """
    today = date.today()
    age = random.randint(min_age, max_age)
    # Sottrae gli anni approssimando con 365.25 giorni/anno, poi aggiunge
    # uno scarto casuale entro l'anno per variare mese e giorno.
    birth = today - timedelta(days=int(age * 365.25))
    birth -= timedelta(days=random.randint(0, 364))
    return birth.isoformat()


def build_payload(email: str, password: str, captcha_token: str, config: dict) -> dict:
    """
    Costruisce il payload di registrazione con dati anagrafici fittizi.

    Args:
        email: indirizzo email dell'utente di test.
        password: password dell'utente di test.
        captcha_token: token di risposta del captcha (fornito dal chiamante).
        config: dizionario di configurazione da cui leggere l'accessToken.

    Returns:
        Il dizionario pronto per essere serializzato e inviato all'API.

    Raises:
        KeyError: se `config` non contiene la chiave "accessToken".
    """
    payload = {
        "email": email,
        "password": password,
        "firstName": random.choice(_FIRST_NAMES),
        "lastName": random.choice(_LAST_NAMES),
        "birthDate": _random_birth_date(),
        "captchaResponse": captcha_token,
        "accessToken": config["accessToken"],
    }

    logger.info(
        "Payload costruito per %s (%s %s)",
        email, payload["firstName"], payload["lastName"],
    )
    return payload


if __name__ == "__main__":
    import json

    logging.basicConfig(level=logging.INFO)

    demo_config = {"accessToken": "abc123", "siteKey": "site-xyz"}
    payload = build_payload(
        email="test.user@example.com",
        password="Str0ngP4ss!",
        captcha_token="captcha-token-placeholder",
        config=demo_config,
    )
    print(json.dumps(payload, indent=2, ensure_ascii=False))
