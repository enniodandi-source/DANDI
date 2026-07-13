#!/usr/bin/env python3
"""
API Retry Script - esegue N tentativi di chiamata a un'API di provisioning.

Pattern implementato:
  1. Esegue fino a N tentativi verso un endpoint API.
  2. In caso di errore "recuperabile" (es. email/username già in uso) rigenera
     le credenziali e riprova, senza interrompere l'esecuzione.
  3. Attende un delay casuale (default 30-90s) tra un tentativo e l'altro, per
     rispettare i rate limit del server ed evitare di sovraccaricarlo.
  4. Salva i risultati riusciti (email e password) in un file JSON, scrivendo
     in modo incrementale e atomico cosi' da non perdere dati in caso di crash.
  5. Gestisce le eccezioni e continua sempre con il tentativo successivo.

Nota: l'endpoint di default punta a un placeholder. Configura API_URL (o la
variabile d'ambiente API_URL) con l'API che sei autorizzato a usare.
"""

import argparse
import json
import logging
import os
import random
import secrets
import string
import time
import uuid
from pathlib import Path

try:
    import requests
except ImportError:  # requests e' opzionale: senza, si usa la modalita' dry-run
    requests = None


# ============================================================================
# CONFIGURAZIONE LOGGING
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("api_retry.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


# ============================================================================
# COSTANTI DI DEFAULT
# ============================================================================
DEFAULT_API_URL = os.environ.get("API_URL", "https://api.example.com/v1/register")
DEFAULT_EMAIL_DOMAIN = os.environ.get("EMAIL_DOMAIN", "example.com")
DEFAULT_RESULTS_FILE = "results.json"
DEFAULT_MIN_DELAY = 30  # secondi
DEFAULT_MAX_DELAY = 90  # secondi
DEFAULT_TIMEOUT = 30    # secondi per la singola richiesta HTTP


# ============================================================================
# GENERAZIONE CREDENZIALI
# ============================================================================
def generate_username() -> str:
    """Genera uno username univoco (prefisso leggibile + suffisso casuale)."""
    suffix = uuid.uuid4().hex[:8]
    return f"user_{suffix}"


def generate_email(username: str, domain: str = DEFAULT_EMAIL_DOMAIN) -> str:
    """Costruisce un'email a partire dallo username."""
    return f"{username}@{domain}"


def generate_password(length: int = 16) -> str:
    """Genera una password casuale robusta (usa secrets, non random)."""
    alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def new_credentials(domain: str = DEFAULT_EMAIL_DOMAIN) -> dict:
    """Crea un set completo di credenziali (username, email, password)."""
    username = generate_username()
    return {
        "username": username,
        "email": generate_email(username, domain),
        "password": generate_password(),
    }


# ============================================================================
# PERSISTENZA RISULTATI
# ============================================================================
def load_results(results_file: Path) -> list:
    """Carica i risultati esistenti dal file JSON (lista vuota se assente)."""
    if results_file.exists():
        try:
            with open(results_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Impossibile leggere {results_file} ({e}), riparto da zero")
    return []


def save_results(results_file: Path, results: list) -> None:
    """
    Salva i risultati su disco in modo atomico.

    Scrive prima su un file temporaneo e poi lo rinomina: cosi' anche se il
    processo viene interrotto durante la scrittura, il file originale resta
    integro.
    """
    tmp_file = results_file.with_suffix(results_file.suffix + ".tmp")
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    os.replace(tmp_file, results_file)
    logger.debug(f"Salvati {len(results)} risultati in {results_file}")


# ============================================================================
# CHIAMATA ALL'API
# ============================================================================
class RecoverableError(Exception):
    """Errore per cui ha senso rigenerare le credenziali e riprovare."""


class FatalError(Exception):
    """Errore non recuperabile: inutile riprovare con nuove credenziali."""


def call_api(api_url: str, credentials: dict, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """
    Esegue la chiamata all'API di registrazione.

    Args:
        api_url: endpoint dell'API.
        credentials: dict con username, email, password.
        timeout: timeout della richiesta in secondi.

    Returns:
        La risposta JSON dell'API in caso di successo.

    Raises:
        RecoverableError: se l'errore e' recuperabile (es. email gia' usata),
            quindi conviene rigenerare le credenziali e riprovare.
        FatalError: se l'errore non e' recuperabile (es. 401/403/500).
    """
    if requests is None:
        raise FatalError("La libreria 'requests' non e' installata (pip install requests)")

    payload = {
        "username": credentials["username"],
        "email": credentials["email"],
        "password": credentials["password"],
    }

    response = requests.post(api_url, json=payload, timeout=timeout)

    # 2xx -> successo
    if 200 <= response.status_code < 300:
        try:
            return response.json()
        except ValueError:
            return {"status_code": response.status_code, "raw": response.text}

    # 409 Conflict / 422 Unprocessable -> tipicamente "email/username gia' in uso"
    if response.status_code in (409, 422):
        raise RecoverableError(
            f"Conflitto (HTTP {response.status_code}): {response.text[:200]}"
        )

    # 429 Too Many Requests -> rate limit: recuperabile, ma non serve cambiare
    # credenziali. Lo trattiamo come recuperabile per non fermare il ciclo.
    if response.status_code == 429:
        raise RecoverableError(f"Rate limit (HTTP 429): {response.text[:200]}")

    # Tutto il resto (4xx/5xx) -> errore fatale per questo tentativo
    raise FatalError(f"HTTP {response.status_code}: {response.text[:200]}")


# ============================================================================
# CICLO PRINCIPALE
# ============================================================================
def run(
    n_attempts: int,
    api_url: str = DEFAULT_API_URL,
    results_file: str = DEFAULT_RESULTS_FILE,
    domain: str = DEFAULT_EMAIL_DOMAIN,
    min_delay: int = DEFAULT_MIN_DELAY,
    max_delay: int = DEFAULT_MAX_DELAY,
    max_regenerations: int = 5,
    dry_run: bool = False,
) -> list:
    """
    Esegue N tentativi di chiamata all'API.

    Args:
        n_attempts: numero di tentativi (successi desiderati) da eseguire.
        api_url: endpoint dell'API.
        results_file: file JSON dove salvare i risultati.
        domain: dominio da usare per generare le email.
        min_delay / max_delay: intervallo (secondi) del delay casuale tra tentativi.
        max_regenerations: quante volte rigenerare le credenziali sullo stesso
            tentativo prima di rinunciare.
        dry_run: se True, non chiama l'API ma simula un successo (per test).

    Returns:
        La lista completa dei risultati salvati.
    """
    results_path = Path(results_file)
    results = load_results(results_path)

    logger.info("=" * 70)
    logger.info(f"AVVIO: {n_attempts} tentativi verso {api_url}")
    logger.info(f"Delay casuale tra tentativi: {min_delay}-{max_delay}s")
    logger.info("=" * 70)

    successes = 0

    for attempt in range(1, n_attempts + 1):
        logger.info(f"\n--- Tentativo {attempt}/{n_attempts} ---")

        credentials = new_credentials(domain)
        result = None

        # Prova (e riprova rigenerando le credenziali) sul singolo tentativo.
        for regen in range(max_regenerations):
            try:
                if dry_run:
                    logger.info(f"[DRY-RUN] simulo la registrazione di {credentials['email']}")
                    response = {"simulated": True}
                else:
                    logger.info(f"Chiamo l'API con email {credentials['email']}")
                    response = call_api(api_url, credentials)

                # Successo: prepariamo il record da salvare.
                result = {
                    "email": credentials["email"],
                    "password": credentials["password"],
                    "username": credentials["username"],
                    "api_response": response,
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }
                logger.info(f"Successo: {credentials['email']}")
                break

            except RecoverableError as e:
                # Es. "email gia' usata": rigenero le credenziali e riprovo subito.
                logger.warning(
                    f"Errore recuperabile ({e}). Rigenero le credenziali "
                    f"(tentativo di rigenerazione {regen + 1}/{max_regenerations})"
                )
                credentials = new_credentials(domain)
                continue

            except FatalError as e:
                # Errore non recuperabile: interrompo la rigenerazione per questo tentativo.
                logger.error(f"Errore fatale, salto il tentativo: {e}")
                break

            except Exception as e:
                # Qualsiasi altra eccezione (rete, timeout, ...): logga e non
                # bloccare il ciclo. Riprovo con nuove credenziali.
                logger.error(f"Eccezione inattesa: {e}", exc_info=True)
                credentials = new_credentials(domain)
                continue

        # Se il tentativo ha avuto successo, salva subito (persistenza incrementale).
        if result is not None:
            results.append(result)
            successes += 1
            try:
                save_results(results_path, results)
            except OSError as e:
                logger.error(f"Impossibile salvare i risultati: {e}")
        else:
            logger.warning(f"Tentativo {attempt} fallito senza risultato utile")

        # Delay casuale prima del tentativo successivo (non dopo l'ultimo).
        if attempt < n_attempts:
            delay = random.uniform(min_delay, max_delay)
            logger.info(f"Attendo {delay:.1f}s prima del prossimo tentativo...")
            time.sleep(delay)

    logger.info("\n" + "=" * 70)
    logger.info(f"COMPLETATO: {successes}/{n_attempts} tentativi riusciti")
    logger.info(f"Risultati salvati in {results_path}")
    logger.info("=" * 70)

    return results


# ============================================================================
# ENTRY POINT / CLI
# ============================================================================
def parse_args():
    parser = argparse.ArgumentParser(
        description="Esegue N tentativi di chiamata a un'API con retry e persistenza JSON."
    )
    parser.add_argument("-n", "--attempts", type=int, default=5,
                        help="Numero di tentativi (default: 5)")
    parser.add_argument("--api-url", default=DEFAULT_API_URL,
                        help=f"Endpoint dell'API (default: {DEFAULT_API_URL})")
    parser.add_argument("--results-file", default=DEFAULT_RESULTS_FILE,
                        help=f"File JSON dei risultati (default: {DEFAULT_RESULTS_FILE})")
    parser.add_argument("--domain", default=DEFAULT_EMAIL_DOMAIN,
                        help=f"Dominio per le email generate (default: {DEFAULT_EMAIL_DOMAIN})")
    parser.add_argument("--min-delay", type=float, default=DEFAULT_MIN_DELAY,
                        help=f"Delay minimo tra tentativi in secondi (default: {DEFAULT_MIN_DELAY})")
    parser.add_argument("--max-delay", type=float, default=DEFAULT_MAX_DELAY,
                        help=f"Delay massimo tra tentativi in secondi (default: {DEFAULT_MAX_DELAY})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Non chiama l'API, simula i successi (utile per testare lo script)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    try:
        run(
            n_attempts=args.attempts,
            api_url=args.api_url,
            results_file=args.results_file,
            domain=args.domain,
            min_delay=args.min_delay,
            max_delay=args.max_delay,
            dry_run=args.dry_run,
        )
    except KeyboardInterrupt:
        logger.info("Interrotto dall'utente. I risultati gia' salvati sono su disco.")
    except Exception as e:
        logger.error(f"Errore critico: {e}", exc_info=True)
        exit(1)
