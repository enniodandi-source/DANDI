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

## 6. Fingerprint TLS (JA3) — livello sotto l'HTTP

Prima ancora del livello applicativo, un sistema anti-bot può classificare il
client dal **ClientHello TLS**. La firma JA3 è costruita da versione, cipher
suite, estensioni, gruppi di curve e formati dei punti: dipende dalla **libreria
TLS** (OpenSSL vs BoringSSL) e dalla sua configurazione, e **non cambia
modificando gli header HTTP**. Lo script `tls_fingerprint.py` cattura il
ClientHello di ogni client su un server locale e ne calcola il JA3.

| Client | Libreria TLS | JA3 hash |
|---|---|---|
| Python `ssl` (~`requests`) | OpenSSL 3.0.13 | `8a9d5d0f12f7d43ee3af1c51d2998d99` |
| `curl` | OpenSSL 3.0.13 | `78f0dc5ac5b19daf131a133cfdee9691` |
| Chromium headless | BoringSSL | `ddb4b3952ec8c457cb65f2b41b81b418` |

**Osservazioni:**

- **Tre firme distinte su tre client.** A parità di header HTTP (o addirittura
  con lo stesso User-Agent falsificato), il JA3 li separa comunque.
- **Il browser è marcatamente diverso.** Chromium usa un set di cipher compatto
  in ordine BoringSSL (`4865-4866-4867-49195…`), estensioni **GREASE** (es.
  `43690`) e gruppi di curve tipici (`4588-29-23-24`). `requests` e `curl`,
  pur usando entrambi OpenSSL, differiscono tra loro per configurazione: la lista
  cipher di `curl` è più lunga e in ordine diverso.
- **Conseguenza per la detection:** un filtro TLS-fingerprint può respingere
  `requests`/`curl` **prima** di leggere un solo header o valutare il captcha.
  È il livello che spiega perché "sistemare gli header" non rende un client HTTP
  indistinguibile da un browser: la differenza è già nel ClientHello.

> Nota metodologica: JA3 (MD5) è ancora il riferimento diffuso; **JA4** è
> l'evoluzione più recente e robusta. Il principio — la firma dell'handshake
> tradisce la libreria TLS — è identico.

## 7. Limiti del lab e livelli non coperti

- **Reputazione del token captcha:** con le test key l'esito è sempre valido; in
  produzione reCAPTCHA lega il token a origin/sessione e ne pesa la reputazione
  (in v3/Enterprise con uno *score* 0–1).
- **Segnali server-side/di rete:** reputazione IP/ASN, rate limiting, coerenza
  di sessione e binding del JWT non sono modellati qui.

## 8. Conclusioni

La detection efficace non dipende da un header segreto, ma dalla **convergenza
di segnali su più livelli**: fingerprint TLS (JA3) già nel ClientHello, header
HTTP, esecuzione di JavaScript e fingerprint del browser, comportamento
(timing/honeypot), esito e reputazione del captcha, e — fuori dal perimetro di
questo lab — reputazione IP/ASN e binding di sessione. I dati mostrano che i
livelli sono **indipendenti**: rifinire gli header (sez. 5.1) non tocca il JA3
(sez. 6), e usare un browser vero per risolvere il fingerprint introduce altri
segnali (sez. 5.2). Un `403 Forbidden` è la manifestazione corretta di questa
difesa in profondità quando il punteggio aggregato supera la soglia.

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
python tls_fingerprint.py     # genera i JA3 della sezione 6 (nessun server da avviare)
```
