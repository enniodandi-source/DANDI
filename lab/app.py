#!/usr/bin/env python3
"""
Server del lab di ricerca anti-bot.

Espone un form di registrazione fittizio protetto da:
  - reCAPTCHA v2 (test key ufficiali di Google, verifica server-side)
  - FingerprintJS + Botd lato client
  - un motore di scoring aggregato (detector.py)

Ogni richiesta a /register viene valutata e la risposta include il dettaglio
completo dei segnali e del punteggio di rischio: cosi' puoi osservare
esattamente PERCHE' una richiesta viene classificata bot o umano.

Nessun servizio di terzi viene registrato o abusato: e' tutto locale e
finto. Gli account non vengono creati da nessuna parte.
"""

import json
import logging

import requests
from flask import Flask, render_template, request, jsonify

import detector

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger("lab")

app = Flask(__name__)

# ---------------------------------------------------------------------------
# reCAPTCHA v2 - TEST KEY UFFICIALI DI GOOGLE
# Documentate qui: https://developers.google.com/recaptcha/docs/faq
# Restituiscono SEMPRE success=true e mostrano un banner "solo per test".
# Perfette per un lab: nessun captcha reale da risolvere.
# ---------------------------------------------------------------------------
RECAPTCHA_SITE_KEY = "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"
RECAPTCHA_SECRET_KEY = "6LeIxAcTAAAAAGG-vFI1TnRWxMZNFuojJ4WifJWe"
SITEVERIFY_URL = "https://www.google.com/recaptcha/api/siteverify"


def verify_recaptcha(token: str, remote_ip: str) -> dict:
    """Verifica il token lato server contro l'endpoint siteverify di Google."""
    if not token:
        return {}
    try:
        resp = requests.post(
            SITEVERIFY_URL,
            data={"secret": RECAPTCHA_SECRET_KEY, "response": token, "remoteip": remote_ip},
            timeout=10,
        )
        return resp.json()
    except requests.RequestException as exc:
        logger.warning("siteverify non raggiungibile (%s); uso esito simulato", exc)
        # In un lab offline simuliamo il comportamento delle test key.
        return {"success": True, "_simulated": True}


@app.route("/")
def index():
    return render_template("register.html", site_key=RECAPTCHA_SITE_KEY)


@app.route("/register", methods=["POST"])
def register():
    """
    Endpoint di registrazione fittizio.

    Accetta sia form-encoded (dal browser) sia JSON (dagli script di test),
    valuta tutti i segnali e restituisce il verdetto dettagliato.
    """
    # Supporta sia il form del browser sia il JSON degli script di automazione
    if request.is_json:
        form = request.get_json(silent=True) or {}
    else:
        form = request.form.to_dict()

    # Il fingerprint arriva come stringa JSON nel campo nascosto
    fingerprint = {}
    raw_fp = form.get("fingerprint")
    if raw_fp:
        try:
            fingerprint = json.loads(raw_fp) if isinstance(raw_fp, str) else raw_fp
        except (ValueError, TypeError):
            fingerprint = {}

    # Verifica captcha server-side
    captcha_result = verify_recaptcha(
        form.get("g-recaptcha-response") or form.get("captchaResponse", ""),
        request.remote_addr,
    )

    # Scoring aggregato
    verdict = detector.evaluate(
        headers=request.headers,
        form=form,
        fingerprint=fingerprint,
        captcha=captcha_result,
    )

    response = {
        "verdict": verdict.as_dict(),
        "captcha": {k: v for k, v in captcha_result.items() if k != "_simulated"},
        "email": form.get("email"),
    }

    if verdict.blocked:
        logger.info("BLOCCATO risk=%s email=%s", verdict.total_risk, form.get("email"))
        response["error"] = "Forbidden"
        response["message"] = "Richiesta classificata come automatica"
        return jsonify(response), 403

    logger.info("CONSENTITO risk=%s email=%s", verdict.total_risk, form.get("email"))
    response["success"] = True
    response["message"] = "Registrazione (fittizia) accettata"
    return jsonify(response), 200


if __name__ == "__main__":
    print("=" * 64)
    print(" LAB ANTI-BOT - server di ricerca (solo locale)")
    print(" Apri http://127.0.0.1:5000/ nel browser")
    print(" Soglia di blocco: risk >=", detector.BLOCK_THRESHOLD)
    print("=" * 64)
    app.run(host="127.0.0.1", port=5000, debug=True)
