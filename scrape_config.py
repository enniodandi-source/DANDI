#!/usr/bin/env python3
"""
Estrazione di JSON di configurazione inline da una pagina web.

Molte pagine incorporano la configurazione del front-end in un tag <script>
(es. `window.__CONFIG__ = { ... }`). Questo modulo individua quel blocco,
ne estrae il JSON con BeautifulSoup + regex e lo restituisce come dizionario.
"""

import json
import re
import logging
from typing import Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


def extract_inline_config(
    html: str,
    required_keys: tuple = ("accessToken", "siteKey"),
) -> Optional[dict]:
    """
    Estrae il JSON di configurazione inline da una pagina HTML.

    La strategia è a due livelli:
      1. Scorre tutti i tag <script> senza attributo `src` (quelli inline).
      2. Per ognuno, tenta prima un parsing diretto del contenuto come JSON;
         se fallisce, cerca con regex il primo oggetto JSON che contiene
         tutte le chiavi richieste e prova a decodificarlo.

    Args:
        html: il markup HTML grezzo della pagina.
        required_keys: chiavi che devono essere presenti nel JSON perché
            venga considerato il blocco di configurazione corretto.
            Default: ("accessToken", "siteKey").

    Returns:
        Il dizionario di configurazione se trovato, altrimenti None.
    """
    soup = BeautifulSoup(html, "html.parser")

    for script in soup.find_all("script"):
        # Salta gli script esterni: non contengono JSON inline.
        if script.get("src"):
            continue

        content = script.string or script.get_text()
        if not content or not all(key in content for key in required_keys):
            continue

        config = _parse_config_from_text(content, required_keys)
        if config is not None:
            logger.info("Configurazione inline estratta con successo")
            return config

    logger.warning(
        "Nessun blocco di configurazione con le chiavi %s trovato",
        required_keys,
    )
    return None


def _parse_config_from_text(text: str, required_keys: tuple) -> Optional[dict]:
    """
    Estrae un dizionario JSON da una stringa di codice JavaScript.

    Args:
        text: contenuto testuale del tag <script>.
        required_keys: chiavi che il JSON deve contenere.

    Returns:
        Il dizionario decodificato, oppure None se non estraibile.
    """
    # Caso 1: l'intero contenuto è già JSON valido
    # (es. <script type="application/json">).
    stripped = text.strip()
    try:
        data = json.loads(stripped)
        if isinstance(data, dict) and all(k in data for k in required_keys):
            return data
    except json.JSONDecodeError:
        pass

    # Caso 2: il JSON è assegnato a una variabile, es.
    #   window.__CONFIG__ = { ... };
    # Cerchiamo ogni oggetto delimitato da graffe e lo validiamo, partendo
    # da quello che contiene la prima chiave richiesta.
    for match in _iter_json_objects(text):
        try:
            data = json.loads(match)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and all(k in data for k in required_keys):
            return data

    return None


def _iter_json_objects(text: str):
    """
    Genera le sottostringhe candidate a essere oggetti JSON.

    Trova la posizione di ogni `{` che apre un oggetto contenente una chiave
    plausibile e restituisce la porzione bilanciata di graffe che ne consegue.
    Questo evita di dipendere da una singola regex fragile per tutto l'oggetto.
    """
    for start in (m.start() for m in re.finditer(r"\{", text)):
        candidate = _balanced_braces(text, start)
        if candidate:
            yield candidate


def _balanced_braces(text: str, start: int) -> Optional[str]:
    """
    A partire da una `{` in posizione `start`, restituisce la sottostringa
    fino alla graffa di chiusura corrispondente, rispettando le stringhe
    con virgolette e gli escape. None se non c'è bilanciamento.
    """
    depth = 0
    in_string = False
    escaped = False
    quote_char = ""

    for i in range(start, len(text)):
        ch = text[i]

        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == quote_char:
                in_string = False
            continue

        if ch in ('"', "'"):
            in_string = True
            quote_char = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]

    return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    # Esempio d'uso con del markup di prova.
    sample_html = """
    <html>
      <head>
        <script src="https://cdn.example.com/app.js"></script>
        <script>
          window.__APP_CONFIG__ = {
            "accessToken": "abc123",
            "siteKey": "site-xyz",
            "features": { "beta": true }
          };
        </script>
      </head>
      <body>Ciao</body>
    </html>
    """

    config = extract_inline_config(sample_html)
    print(json.dumps(config, indent=2, ensure_ascii=False))
