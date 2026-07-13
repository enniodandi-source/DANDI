#!/usr/bin/env python3
"""
Script di ricerca: sonda il server del lab con profili di richiesta diversi
e mostra come il motore di scoring reagisce a ciascun segnale.

L'obiettivo NON e' superare il controllo, ma DOCUMENTARE quali segnali
spostano il punteggio di rischio e di quanto. Ogni "scenario" isola una
variabile (User-Agent, header dei browser, fingerprint, timing, honeypot)
cosi' da attribuire il rischio a cause precise.

Gira solo contro http://127.0.0.1:5000 (il tuo lab). Avvia prima app.py.
"""

import json
import requests

TARGET = "http://127.0.0.1:5000/register"

# Header "da browser reale" che useremo come baseline realistica
BROWSER_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
    "Sec-Ch-Ua": '"Chromium";v="120", "Not A(Brand";v="99"',
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-Mode": "cors",
}

# Un fingerprint "plausibile da browser reale" (come lo produrrebbe il JS)
GOOD_FP = {
    "webdriver": False,
    "visitorId": "abc123def456",
    "confidence": 0.97,
    "botd": {"bot": False, "botKind": None},
}


def probe(name: str, headers: dict, form: dict) -> dict:
    """Invia una richiesta e stampa il verdetto in modo leggibile."""
    try:
        r = requests.post(TARGET, headers=headers, data=form, timeout=10)
    except requests.RequestException as exc:
        print(f"\n[{name}] ERRORE DI RETE: {exc}")
        print("  -> Hai avviato il server?  python lab/app.py")
        return {}

    data = r.json()
    v = data.get("verdict", {})
    esito = "🚫 BLOCCATO" if v.get("blocked") else "✅ CONSENTITO"
    print(f"\n=== {name} ===")
    print(f"HTTP {r.status_code} | {esito} | risk={v.get('total_risk')}/{v.get('threshold')}")
    for s in v.get("signals", []):
        print(f"   +{s['risk']:>3}  {s['name']:<24} {s['detail']}")
    if not v.get("signals"):
        print("   (nessun segnale di rischio)")
    return data


def main():
    base_form = {
        "email": "ricercatore@example.test",
        "password": "Password123!",
        # con le test key un token qualsiasi risulta valido lato siteverify
        "g-recaptcha-response": "test-token",
        "elapsed_ms": "4200",  # tempo "umano" di compilazione
    }

    print("#" * 64)
    print("# RICERCA ANTI-BOT - profili di richiesta a confronto")
    print("#" * 64)

    # 1. Client HTTP grezzo: nessun header da browser, nessun fingerprint.
    #    E' il punto di partenza tipico di uno script (requests di default).
    probe("Scenario 1 - requests grezzo (nessun camuffamento)",
          {"User-Agent": "python-requests/2.31.0"},
          base_form)

    # 2. Aggiungo header 'da browser' ma ancora senza fingerprint (no JS).
    probe("Scenario 2 - header da browser, ma nessun JS/fingerprint",
          BROWSER_HEADERS,
          base_form)

    # 3. Header browser + fingerprint valido: profilo "umano" completo.
    form3 = dict(base_form, fingerprint=json.dumps(GOOD_FP))
    probe("Scenario 3 - header + fingerprint valido (profilo umano)",
          BROWSER_HEADERS,
          form3)

    # 4. Come il 3, ma il fingerprint dichiara webdriver/headless (Selenium/PW).
    fp_bot = dict(GOOD_FP, webdriver=True, botd={"bot": True, "botKind": "headless_chrome"})
    form4 = dict(base_form, fingerprint=json.dumps(fp_bot))
    probe("Scenario 4 - profilo umano ma Botd/webdriver positivi",
          BROWSER_HEADERS,
          form4)

    # 5. Profilo umano ma submit troppo veloce (timing comportamentale).
    form5 = dict(form3, elapsed_ms="200")
    probe("Scenario 5 - profilo umano ma submit in 200 ms",
          BROWSER_HEADERS,
          form5)

    # 6. Honeypot compilato (bot che riempie tutti i campi).
    form6 = dict(form3, website="http://spam.example")
    probe("Scenario 6 - honeypot compilato",
          BROWSER_HEADERS,
          form6)

    print("\n" + "#" * 64)
    print("# Nota: lo scoring e' cumulativo. Confronta i 'risk' tra scenari")
    print("# per attribuire ogni +N a un segnale specifico -> materiale da report.")
    print("#" * 64)


if __name__ == "__main__":
    main()
