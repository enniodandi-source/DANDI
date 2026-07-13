#!/usr/bin/env python3
"""
CapSolver client - Risoluzione di reCAPTCHA v2 per i test automatici dell'API.

Questo modulo serve a superare il reCAPTCHA v2 durante i test end-to-end
dell'API di proprieta'. Invia un task a CapSolver e fa polling finche' il
token non e' pronto, poi restituisce il valore `g-recaptcha-response` da
inoltrare all'endpoint sotto test.

Non richiede dipendenze esterne: usa solo la standard library (urllib),
in linea con il resto del progetto.
"""

import json
import time
import logging
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

# ============================================================================
# COSTANTI
# ============================================================================
CREATE_TASK_URL = "https://api.capsolver.com/createTask"
GET_TASK_RESULT_URL = "https://api.capsolver.com/getTaskResult"

# Parametri di default per il polling
DEFAULT_TIMEOUT = 120        # secondi massimi di attesa complessiva
DEFAULT_POLL_INTERVAL = 3    # secondi tra un polling e il successivo
DEFAULT_HTTP_TIMEOUT = 30    # timeout della singola richiesta HTTP


# ============================================================================
# ECCEZIONI
# ============================================================================
class CapSolverError(Exception):
    """Errore generico restituito dal servizio CapSolver."""


class CapSolverTimeout(CapSolverError):
    """Il captcha non e' stato risolto entro il tempo massimo consentito."""


# ============================================================================
# FUNZIONI DI SUPPORTO
# ============================================================================
def _post_json(url: str, payload: dict, http_timeout: int) -> dict:
    """
    Esegue una POST JSON e restituisce la risposta decodificata.

    Args:
        url: endpoint da chiamare
        payload: dizionario da serializzare come corpo JSON
        http_timeout: timeout in secondi della richiesta

    Returns:
        La risposta JSON come dizionario

    Raises:
        CapSolverError: in caso di errore di rete o risposta non valida
    """
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=http_timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        # Il server ha risposto con uno status di errore (4xx/5xx)
        detail = e.read().decode("utf-8", errors="replace") if e.fp else ""
        raise CapSolverError(f"Errore HTTP {e.code} da {url}: {detail}") from e
    except urllib.error.URLError as e:
        # Problema di connessione / DNS / timeout
        raise CapSolverError(f"Errore di rete verso {url}: {e.reason}") from e

    try:
        return json.loads(body)
    except json.JSONDecodeError as e:
        raise CapSolverError(f"Risposta non JSON da {url}: {body[:200]}") from e


def _check_response(response: dict) -> None:
    """
    Verifica il campo `errorId` restituito da CapSolver e solleva
    un'eccezione se e' presente un errore.
    """
    if response.get("errorId", 0) != 0:
        code = response.get("errorCode", "ERRORE_SCONOSCIUTO")
        description = response.get("errorDescription", "nessuna descrizione")
        raise CapSolverError(f"CapSolver ha risposto con errore [{code}]: {description}")


# ============================================================================
# FUNZIONE PRINCIPALE
# ============================================================================
def solve_recaptcha_v2(
    site_key: str,
    page_url: str,
    api_key: str,
    timeout: int = DEFAULT_TIMEOUT,
    poll_interval: int = DEFAULT_POLL_INTERVAL,
    http_timeout: int = DEFAULT_HTTP_TIMEOUT,
) -> str:
    """
    Risolve un reCAPTCHA v2 tramite CapSolver e restituisce il token.

    Il flusso e' quello documentato da CapSolver:
      1. POST a /createTask per creare il task di risoluzione
      2. Polling su /getTaskResult finche' lo stato non e' "ready"
      3. Estrazione del token `gRecaptchaResponse` dalla soluzione

    Args:
        site_key: la site key del reCAPTCHA (attributo `data-sitekey`)
        page_url: URL della pagina che ospita il captcha
        api_key: la clientKey del proprio account CapSolver
        timeout: secondi massimi di attesa per la risoluzione (default 120)
        poll_interval: secondi di pausa tra i polling (default 3)
        http_timeout: timeout della singola richiesta HTTP (default 30)

    Returns:
        Il token `g-recaptcha-response` da inviare all'API sotto test.

    Raises:
        CapSolverTimeout: se il captcha non viene risolto entro `timeout`
        CapSolverError: per errori del servizio, di rete o di validazione
    """
    if not all([site_key, page_url, api_key]):
        raise ValueError("site_key, page_url e api_key sono obbligatori")

    # ------------------------------------------------------------------
    # 1. Creazione del task
    # ------------------------------------------------------------------
    create_payload = {
        "clientKey": api_key,
        "task": {
            # ProxyLess: CapSolver usa i propri proxy, non serve fornirne uno
            "type": "ReCaptchaV2TaskProxyLess",
            "websiteURL": page_url,
            "websiteKey": site_key,
        },
    }

    logger.info("Creazione task CapSolver per %s", page_url)
    create_response = _post_json(CREATE_TASK_URL, create_payload, http_timeout)
    _check_response(create_response)

    task_id = create_response.get("taskId")
    if not task_id:
        raise CapSolverError(f"createTask non ha restituito un taskId: {create_response}")

    logger.info("Task creato: %s", task_id)

    # ------------------------------------------------------------------
    # 2. Polling del risultato
    # ------------------------------------------------------------------
    result_payload = {"clientKey": api_key, "taskId": task_id}
    deadline = time.monotonic() + timeout

    while True:
        # Controllo del timeout complessivo prima di ogni tentativo
        if time.monotonic() >= deadline:
            raise CapSolverTimeout(
                f"Captcha non risolto entro {timeout}s (taskId={task_id})"
            )

        time.sleep(poll_interval)

        result_response = _post_json(GET_TASK_RESULT_URL, result_payload, http_timeout)
        _check_response(result_response)

        status = result_response.get("status")

        if status == "ready":
            solution = result_response.get("solution", {})
            token = solution.get("gRecaptchaResponse")
            if not token:
                raise CapSolverError(
                    f"Task pronto ma senza token: {result_response}"
                )
            logger.info("Captcha risolto (taskId=%s)", task_id)
            return token

        if status == "processing":
            logger.debug("Task %s ancora in elaborazione...", task_id)
            continue

        # Stato inatteso: interrompo invece di ciclare all'infinito
        raise CapSolverError(
            f"Stato inatteso '{status}' per il task {task_id}: {result_response}"
        )


# ============================================================================
# ESEMPIO D'USO
# ============================================================================
if __name__ == "__main__":
    import os
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )

    # I parametri si leggono da variabili d'ambiente per non scriverli nel codice
    demo_api_key = os.environ.get("CAPSOLVER_API_KEY")
    demo_site_key = os.environ.get("RECAPTCHA_SITE_KEY")
    demo_page_url = os.environ.get("RECAPTCHA_PAGE_URL")

    if not all([demo_api_key, demo_site_key, demo_page_url]):
        print(
            "Imposta le variabili d'ambiente CAPSOLVER_API_KEY, "
            "RECAPTCHA_SITE_KEY e RECAPTCHA_PAGE_URL per provare lo script."
        )
        sys.exit(1)

    try:
        result_token = solve_recaptcha_v2(
            site_key=demo_site_key,
            page_url=demo_page_url,
            api_key=demo_api_key,
        )
        print(f"Token ottenuto:\n{result_token}")
    except CapSolverTimeout as exc:
        print(f"Timeout: {exc}")
        sys.exit(1)
    except CapSolverError as exc:
        print(f"Errore CapSolver: {exc}")
        sys.exit(1)
