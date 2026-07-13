# Lab di ricerca sui meccanismi anti-bot

Ambiente **locale e autonomo** per studiare come i sistemi anti-bot distinguono
un browser reale da un client automatizzato, e come si inserisce la verifica
reCAPTCHA nel punteggio complessivo.

Tutto gira su `127.0.0.1`: non viene contattato, registrato o testato nessun
servizio di terzi. Gli "account" sono fittizi e non vengono creati da nessuna
parte. Serve a produrre dati riproducibili per un report, non a superare la
protezione di un sistema di produzione.

## Componenti

| File | Ruolo |
|------|-------|
| `app.py` | Server Flask: form di registrazione + endpoint `/register` che valuta i segnali |
| `detector.py` | Motore di **scoring aggregato**: assegna un rischio a ogni segnale |
| `templates/register.html` | Form con reCAPTCHA v2 (test key) + FingerprintJS + Botd |
| `automation_test.py` | Sonda il server con profili diversi e mostra come cambia il rischio |

## reCAPTCHA: test key ufficiali

Il lab usa le **test key pubbliche di Google**
(`6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI` / secret `6Le...WifJWe`),
documentate nella [FAQ di reCAPTCHA](https://developers.google.com/recaptcha/docs/faq).
Restituiscono sempre `success: true` e mostrano un banner "for testing only":
così non c'è alcun captcha reale da risolvere e ci si concentra sugli *altri*
segnali.

## Come si avvia

```bash
cd lab
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 1) avvia il server
python app.py            # -> http://127.0.0.1:5000/

# 2) in un altro terminale, lancia le sonde di ricerca
python automation_test.py
```

Aprendo il form nel browser vedrai il verdetto "umano"; lanciando
`automation_test.py` vedrai i profili automatici accumulare rischio.

## Modello di scoring (didattico)

I sistemi reali non usano un singolo controllo booleano: sommano molti
**segnali deboli**. `detector.py` riproduce questa logica con una soglia
(`BLOCK_THRESHOLD = 50`). Le famiglie di segnali:

1. **Header HTTP** — User-Agent di libreria, assenza di `Sec-CH-UA` /
   `Sec-Fetch-*`, `Accept` generico, `Accept-Language` mancante.
2. **Fingerprint (JS)** — assenza totale (nessun JS eseguito), esito di
   **Botd**, `navigator.webdriver`, confidence di FingerprintJS.
3. **Comportamento** — honeypot compilato, timing di submit troppo rapido.
4. **Captcha** — esito di `siteverify` (in v3/Enterprise anche lo *score*).

## Spunti di ricerca da documentare

- **Il fattore dominante non è un header mancante.** Confronta lo Scenario 2
  (header da browser perfetti, ma nessun JS) con lo Scenario 3: la differenza
  la fa l'esecuzione di JavaScript e il fingerprint, non l'header giusto.
- **TLS/HTTP fingerprint (JA3/JA4).** Questo lab lavora a livello applicativo.
  Per estendere la ricerca al livello TLS — dove `requests` è distinguibile da
  Chrome a prescindere dagli header — si può mettere davanti un reverse proxy
  (nginx/Cloudflare) o analizzare i pacchetti; è il naturale passo successivo.
- **Reputazione del token captcha.** Con le test key l'esito è sempre valido;
  in produzione reCAPTCHA lega il token a origin/sessione e ne pesa la
  reputazione. È il punto in cui, in `_score_captcha`, si inserirebbe uno score.

## Estensioni suggerite

- Aggiungere un profilo con **Playwright/Selenium reali** (browser headless) e
  osservare cosa rileva Botd rispetto a `requests`.
- Sostituire lo scoring statico con un piccolo modello che pesa i segnali su
  un dataset di richieste etichettate.
- Aggiungere un layer TLS-fingerprint per completare l'analisi multi-livello.
