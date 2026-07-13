# Report di ricerca — Meccanismi di detection anti-bot su form di registrazione

**Ambiente:** lab locale (`lab/app.py`, `lab/detector.py`, `lab/automation_test.py`)
**Data esecuzione:** 2026-07-13
**Scope:** esclusivamente il server locale `127.0.0.1:5000` di questo repository.
Nessun servizio di terzi è stato contattato, testato o registrato.

---

## 1. Obiettivo

Capire e documentare **quali segnali** un sistema di protezione registrazioni
usa per distinguere un client automatizzato da un browser reale, e **quanto
pesa** ciascun segnale nella decisione finale. Il lab riproduce, in forma
didattica, il modello di *scoring aggregato* tipico dei sistemi reali
(reCAPTCHA Enterprise, Arkose, Botd): non un singolo controllo booleano, ma la
somma di molti segnali deboli confrontata con una soglia.

## 2. Metodologia

Il server assegna a ogni richiesta un **punteggio di rischio** (`detector.py`).
Superata la soglia `BLOCK_THRESHOLD = 50`, la richiesta riceve `403 Forbidden`.
Lo script `automation_test.py` invia sei profili di richiesta che isolano una
variabile alla volta, così da attribuire ogni incremento di rischio a una causa
precisa. reCAPTCHA usa le **test key ufficiali di Google** (sempre valide),
così l'analisi si concentra sui segnali diversi dal captcha.

## 3. Catalogo dei segnali e pesi

| Segnale | Rischio | Categoria | Perché è indicativo |
|---|---:|---|---|
| `ua_library` | 45 | Header | User-Agent di libreria HTTP (`python-requests`, `curl`…) |
| `ua_missing` | 40 | Header | User-Agent assente |
| `ch_ua_missing` | 20 | Header | UA dichiara Chromium ma mancano gli header `Sec-CH-UA` |
| `sec_fetch_missing` | 15 | Header | Header `Sec-Fetch-*` assenti |
| `accept_language_missing` | 10 | Header | `Accept-Language` assente |
| `accept_generic` | 8 | Header | `Accept: */*` (tipico dei client HTTP, non dei browser) |
| `fingerprint_missing` | 35 | Fingerprint | Nessun fingerprint → JavaScript non eseguito |
| `botd_positive` | 40 | Fingerprint | Botd rileva un bot lato browser |
| `webdriver_flag` | 30 | Fingerprint | `navigator.webdriver = true` (Selenium/Playwright) |
| `headless_flag` | 25 | Fingerprint | Browser headless |
| `fp_low_confidence` | 15 | Fingerprint | Confidence di FingerprintJS bassa |
| `honeypot_filled` | 50 | Comportamento | Campo nascosto compilato |
| `submit_too_fast` | 20 | Comportamento | Form inviato in < 1,5 s |
| `no_timing` | 10 | Comportamento | Nessun dato di timing |
| `captcha_missing` | 40 | Captcha | Token captcha assente |
| `captcha_failed` | 40 | Captcha | Verifica `siteverify` fallita |

## 4. Risultati sperimentali

Output di `automation_test.py` (soglia di blocco = 50):

| # | Profilo | Rischio | Esito | Segnali scattati |
|---|---|---:|---|---|
| 1 | `requests` grezzo | **113** | 🚫 403 | ua_library(45), fingerprint_missing(35), sec_fetch_missing(15), accept_language_missing(10), accept_generic(8) |
| 2 | Header da browser, ma senza JS | **35** | ✅ 200 | fingerprint_missing(35) |
| 3 | Header + fingerprint valido | **0–8** | ✅ 200 | (solo accept_generic se Accept=*/*) |
| 4 | Profilo umano + Botd/webdriver | **70** | 🚫 403 | botd_positive(40), webdriver_flag(30) |
| 5 | Profilo umano ma submit in 200 ms | **20** | ✅ 200 | submit_too_fast(20) |
| 6 | Honeypot compilato | **50** | 🚫 403 | honeypot_filled(50) |

## 5. Analisi

**5.1 — Il fattore dominante non è "l'header giusto che manca".**
Il confronto tra lo Scenario 1 e lo Scenario 2 è il risultato centrale. Passando
da un User-Agent di libreria a header da browser perfetti, il rischio cala da
113 a 35: si eliminano i segnali *header*, ma resta `fingerprint_missing`. Un
client HTTP puro (`requests`, `curl`) **non può** produrre il fingerprint perché
non esegue JavaScript. Questo è il motivo per cui rifinire gli header non basta
a farsi passare per umano: manca un'intera classe di segnale che nasce solo
dall'esecuzione di codice nel browser.

**5.2 — Un browser automatizzato viene rilevato comunque.**
Lo Scenario 4 mostra che eseguire un browser vero (Playwright/Selenium) risolve
`fingerprint_missing` ma ne introduce altri: `navigator.webdriver` e la
detection di Botd. L'automazione lascia tracce a un livello diverso.

**5.3 — Segnali comportamentali e trappole.**
Il timing (Scenario 5) da solo è un segnale debole (+20, non blocca), coerente
col fatto che un umano veloce non va punito troppo. L'honeypot (Scenario 6) è
invece dirimente: un campo invisibile all'utente ma compilato è quasi certamente
un bot che riempie tutti gli input, e da solo raggiunge la soglia.

**5.4 — Difesa in profondità.**
Nessun singolo segnale "è" il controllo: è la **somma** a decidere. Questo rende
la protezione robusta — neutralizzare un segnale non sblocca il flusso finché
gli altri restano attivi — ed è il motivo per cui un `403` su questi sistemi non
si spiega con "un header mancante".

## 6. Limiti del lab e livelli non coperti

- **TLS/HTTP fingerprint (JA3/JA4):** questo lab lavora a livello applicativo.
  A livello TLS un client come `requests` resta distinguibile da Chrome a
  prescindere dagli header. Estensione naturale: reverse proxy che ispeziona la
  firma TLS.
- **Reputazione del token captcha:** con le test key l'esito è sempre valido; in
  produzione reCAPTCHA lega il token a origin/sessione e ne pesa la reputazione
  (in v3/Enterprise con uno *score* 0–1).
- **Segnali server-side/di rete:** reputazione IP/ASN, rate limiting, coerenza
  di sessione e binding del JWT non sono modellati qui.

## 7. Conclusioni

La detection efficace non dipende da un header segreto, ma dalla **convergenza
di segnali su più livelli**: header HTTP, esecuzione di JavaScript e fingerprint,
comportamento (timing/honeypot), esito e reputazione del captcha, e — fuori dal
perimetro di questo lab — fingerprint TLS e reputazione di rete. Un `403 Forbidden`
è la manifestazione corretta di questa difesa in profondità quando il punteggio
aggregato supera la soglia.

---

## Appendice A — Risposta JSON grezza (Scenario 1, bloccato)

```json
{
  "captcha": {"success": true},
  "error": "Forbidden",
  "message": "Richiesta classificata come automatica",
  "verdict": {
    "blocked": true,
    "threshold": 50,
    "total_risk": 113,
    "signals": [
      {"name": "ua_library", "risk": 45, "detail": "User-Agent di libreria HTTP: 'python-requests/2.31.0'"},
      {"name": "sec_fetch_missing", "risk": 15, "detail": "Header Sec-Fetch-* assenti"},
      {"name": "accept_language_missing", "risk": 10, "detail": "Accept-Language assente"},
      {"name": "accept_generic", "risk": 8, "detail": "Header Accept generico '*/*'"},
      {"name": "fingerprint_missing", "risk": 35, "detail": "Nessun fingerprint: il client non ha eseguito JavaScript"}
    ]
  }
}
```

## Appendice B — Riproducibilità

```bash
cd lab
pip install -r requirements.txt
python app.py                 # terminale 1
python automation_test.py     # terminale 2  → genera i dati della sezione 4
```
