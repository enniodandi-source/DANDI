#!/usr/bin/env python3
"""
Motore di scoring anti-bot per il lab di ricerca.

Riproduce, in forma didattica e semplificata, il tipo di ragionamento che
usano i sistemi anti-bot reali (es. reCAPTCHA Enterprise, Arkose, Botd):
NON un singolo controllo booleano, ma un PUNTEGGIO AGGREGATO costruito da
molti segnali deboli. Ogni segnale aggiunge "rischio"; oltre una soglia la
richiesta viene rifiutata.

Serve a documentare *quali* segnali distinguono un client automatico da un
browser reale. Tutto gira sul server locale del lab: nessun servizio di
terzi viene toccato.
"""

from dataclasses import dataclass, field


# Soglia oltre la quale consideriamo la richiesta "bot" (403).
BLOCK_THRESHOLD = 50


@dataclass
class Signal:
    """Un singolo segnale valutato, con il peso di rischio che aggiunge."""
    name: str
    risk: int
    detail: str


@dataclass
class Verdict:
    total_risk: int = 0
    signals: list = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.total_risk >= BLOCK_THRESHOLD

    def add(self, name: str, risk: int, detail: str):
        if risk:
            self.signals.append(Signal(name, risk, detail))
            self.total_risk += risk

    def as_dict(self) -> dict:
        return {
            "blocked": self.blocked,
            "total_risk": self.total_risk,
            "threshold": BLOCK_THRESHOLD,
            "signals": [
                {"name": s.name, "risk": s.risk, "detail": s.detail}
                for s in self.signals
            ],
        }


# ---------------------------------------------------------------------------
# Segnali basati sugli HEADER HTTP
# ---------------------------------------------------------------------------
def _score_headers(headers: dict, verdict: Verdict):
    """
    I browser moderni inviano un set di header molto riconoscibile.
    La loro assenza o incoerenza e' un forte indicatore di client scriptato.
    `headers` e' un dict case-insensitive (werkzeug lo e' gia').
    """
    ua = headers.get("User-Agent", "")

    if not ua:
        verdict.add("ua_missing", 40, "User-Agent assente")
    else:
        low = ua.lower()
        # Librerie che si presentano onestamente
        for token in ("python-requests", "curl", "httpx", "go-http", "okhttp", "wget"):
            if token in low:
                verdict.add("ua_library", 45, f"User-Agent di libreria HTTP: '{ua}'")
                break

    # Client Hints: Chrome/Edge inviano sec-ch-ua*. Un UA che dichiara Chrome
    # ma non manda i client hints e' incoerente.
    claims_chromium = any(b in ua for b in ("Chrome", "Edg", "Chromium"))
    has_ch_ua = "Sec-Ch-Ua" in headers or "sec-ch-ua" in headers
    if claims_chromium and not has_ch_ua:
        verdict.add("ch_ua_missing", 20,
                    "UA dichiara Chromium ma mancano gli header Sec-CH-UA")

    # Fetch metadata headers: i browser reali li inviano su navigazioni/fetch.
    if not any(h in headers for h in ("Sec-Fetch-Site", "Sec-Fetch-Mode")):
        verdict.add("sec_fetch_missing", 15, "Header Sec-Fetch-* assenti")

    # Accept-Language: quasi sempre presente in un browser reale.
    if not headers.get("Accept-Language"):
        verdict.add("accept_language_missing", 10, "Accept-Language assente")

    # Accept generico "*/*" e' tipico dei client HTTP, non dei browser.
    accept = headers.get("Accept", "")
    if accept == "*/*":
        verdict.add("accept_generic", 8, "Header Accept generico '*/*'")


# ---------------------------------------------------------------------------
# Segnali basati sul FINGERPRINT del client (FingerprintJS / Botd)
# ---------------------------------------------------------------------------
def _score_fingerprint(fp: dict, verdict: Verdict):
    """
    Il payload di fingerprint viene generato da JavaScript nel browser.
    Un client che non esegue JS non puo' produrlo: la sua assenza e' di per
    se' un segnale fortissimo.
    `fp` e' quello che il form invia nel campo nascosto 'fingerprint'.
    """
    if not fp:
        verdict.add("fingerprint_missing", 35,
                    "Nessun fingerprint: il client non ha eseguito JavaScript")
        return

    # Botd: risultato di bot detection lato browser.
    bot = fp.get("botd", {})
    if bot.get("bot") is True:
        kind = bot.get("botKind", "sconosciuto")
        verdict.add("botd_positive", 40, f"Botd ha rilevato un bot: {kind}")

    # FingerprintJS restituisce una confidence sull'identificazione.
    confidence = fp.get("confidence")
    if isinstance(confidence, (int, float)) and confidence < 0.5:
        verdict.add("fp_low_confidence", 15,
                    f"Confidence del fingerprint bassa: {confidence}")

    # Segnali di ambiente headless/automatizzato riportati dal client.
    if fp.get("webdriver") is True:
        verdict.add("webdriver_flag", 30, "navigator.webdriver = true (automazione)")
    if fp.get("headless") is True:
        verdict.add("headless_flag", 25, "Browser headless rilevato")


# ---------------------------------------------------------------------------
# Segnali COMPORTAMENTALI (timing, honeypot)
# ---------------------------------------------------------------------------
def _score_behavior(form: dict, verdict: Verdict):
    # Honeypot: campo invisibile all'utente. Se e' compilato, e' un bot che
    # riempie tutti gli input che trova.
    if form.get("website"):  # 'website' e' il nostro honeypot
        verdict.add("honeypot_filled", 50, "Campo honeypot compilato")

    # Tempo tra caricamento pagina e submit. Un umano impiega secondi;
    # un bot invia quasi istantaneamente.
    try:
        elapsed_ms = int(form.get("elapsed_ms", 0))
    except (TypeError, ValueError):
        elapsed_ms = 0
    if 0 < elapsed_ms < 1500:
        verdict.add("submit_too_fast", 20,
                    f"Form inviato troppo in fretta ({elapsed_ms} ms)")
    elif elapsed_ms == 0:
        verdict.add("no_timing", 10, "Nessun dato di timing dal client")


# ---------------------------------------------------------------------------
# Segnale CAPTCHA (esito verifica server-side gia' calcolato)
# ---------------------------------------------------------------------------
def _score_captcha(captcha: dict, verdict: Verdict):
    """
    `captcha` e' l'esito di siteverify di Google (o simulato con le test key).
    Con le test key l'esito e' sempre success=true, quindi in laboratorio
    questo segnale non blocca: serve a mostrare *dove* si inserirebbe nello
    scoring un token debole/assente in produzione.
    """
    if not captcha:
        verdict.add("captcha_missing", 40, "Nessun token captcha inviato")
        return
    if not captcha.get("success"):
        errors = captcha.get("error-codes", [])
        verdict.add("captcha_failed", 40, f"Verifica captcha fallita: {errors}")
    # In reCAPTCHA v3/Enterprise ci sarebbe anche uno 'score' 0..1 da pesare qui.


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def evaluate(headers: dict, form: dict, fingerprint: dict, captcha: dict) -> Verdict:
    """
    Combina tutti i segnali e restituisce un Verdict con il rischio totale,
    la lista dei segnali scattati e la decisione finale (blocca / consenti).
    """
    verdict = Verdict()
    _score_headers(headers, verdict)
    _score_fingerprint(fingerprint, verdict)
    _score_behavior(form, verdict)
    _score_captcha(captcha, verdict)
    return verdict
