#!/usr/bin/env python3
"""
IMAP Viewer - terminale per leggere una casella email via IMAP.

Legge il profilo da config/imap_config.txt, si collega al server IMAP
e mostra a schermo, passo per passo, cosa succede: connessione, login,
email trovate (mittente, oggetto, anteprima del testo, link).
In modalità "watch" resta in ascolto e mostra le nuove email in arrivo.

Usa solo la libreria standard di Python (3.8+).
"""

import configparser
import email
import html
import imaplib
import os
import re
import shutil
import socket
import sys
import time
from datetime import datetime, timedelta
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime

BASE_DIR = os.path.dirname(os.path.abspath(sys.argv[0]))
CONFIG_DIR = os.path.join(BASE_DIR, "config")
CONFIG_FILE = os.path.join(CONFIG_DIR, "imap_config.txt")
EXAMPLE_FILE = os.path.join(CONFIG_DIR, "imap_config.example.txt")

# --- Colori ANSI (su Windows 10+ si attivano con os.system("")) ---
if os.name == "nt":
    os.system("")
CYAN, GREEN, RED, YELLOW, MAGENTA, WHITE, GREY, RESET = (
    "\033[96m", "\033[92m", "\033[91m", "\033[93m", "\033[95m",
    "\033[97m", "\033[90m", "\033[0m",
)


def log(tag, msg, color=CYAN):
    ts = datetime.now().strftime("%H:%M:%S:%f")[:-3]
    print(f"{CYAN}[{ts}]{RESET} {color}[{tag}] {msg}{RESET}", flush=True)


def press_any_key_to_exit(code=0):
    print(f"\n{WHITE}Press any key to exit...{RESET}", end="", flush=True)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.getch()
        else:
            input()
    except (EOFError, KeyboardInterrupt):
        pass
    sys.exit(code)


def decode(value):
    if not value:
        return ""
    try:
        return str(make_header(decode_header(value)))
    except Exception:
        return value


# ---------------------------------------------------------------- config

def load_config():
    log("Configuration", f"Loading config from {CONFIG_FILE}")
    if not os.path.exists(CONFIG_FILE):
        if os.path.exists(EXAMPLE_FILE):
            shutil.copy(EXAMPLE_FILE, CONFIG_FILE)
            log("Configuration", "imap_config.txt non trovato: creato dal modello.", YELLOW)
            log("Configuration", "Compila il file con i tuoi dati e riavvia il programma.", YELLOW)
        else:
            log("Configuration", "File di configurazione mancante.", RED)
        press_any_key_to_exit(1)

    cp = configparser.ConfigParser(inline_comment_prefixes=None)
    cp.read(CONFIG_FILE, encoding="utf-8")

    def get(section, key, default=""):
        return cp.get(section, key, fallback=default).strip()

    cfg = {
        "host": get("imap", "host"),
        "port": int(get("imap", "port", "993") or 993),
        "ssl": get("imap", "ssl", "yes").lower() in ("yes", "si", "sì", "true", "1"),
        "user": get("imap", "user"),
        "password": get("imap", "password"),
        "folder": get("imap", "folder", "INBOX") or "INBOX",
        "from_contains": get("filtri", "from_contains").lower(),
        "subject_contains": get("filtri", "subject_contains").lower(),
        "days_back": int(get("filtri", "days_back", "3") or 3),
        "max_messages": int(get("filtri", "max_messages", "10") or 10),
        "preview_chars": int(get("visualizzazione", "preview_chars", "800") or 800),
        "show_links": get("visualizzazione", "show_links", "yes").lower() in ("yes", "si", "sì", "true", "1"),
        "watch": get("monitoraggio", "watch", "yes").lower() in ("yes", "si", "sì", "true", "1"),
        "interval": max(10, int(get("monitoraggio", "interval_seconds", "30") or 30)),
    }

    missing = [k for k in ("host", "user", "password") if not cfg[k]]
    if missing or "tuo.indirizzo" in cfg["user"] or cfg["password"] == "la-tua-app-password":
        log("Configuration", "Profilo incompleto: compila host, user e password in imap_config.txt", RED)
        press_any_key_to_exit(1)

    log("Configuration", "Successfully loaded configuration", GREEN)
    log("Profile", f"{cfg['user']} @ {cfg['host']}:{cfg['port']} "
                   f"({'SSL' if cfg['ssl'] else 'no SSL'}) - cartella {cfg['folder']}", WHITE)
    filters = []
    if cfg["from_contains"]:
        filters.append(f"mittente contiene '{cfg['from_contains']}'")
    if cfg["subject_contains"]:
        filters.append(f"oggetto contiene '{cfg['subject_contains']}'")
    filters.append(f"ultimi {cfg['days_back']} giorni")
    log("Filters", ", ".join(filters), WHITE)
    return cfg


# ------------------------------------------------------------------ imap

def connect(cfg):
    log("IMAP", f"Connessione a {cfg['host']}:{cfg['port']}...")
    try:
        if cfg["ssl"]:
            conn = imaplib.IMAP4_SSL(cfg["host"], cfg["port"], timeout=30)
        else:
            conn = imaplib.IMAP4(cfg["host"], cfg["port"], timeout=30)
    except (socket.timeout, TimeoutError):
        raise RuntimeError("Timeout: server non raggiungibile (controlla host, porta o firewall)")
    except socket.gaierror:
        raise RuntimeError(f"Host '{cfg['host']}' non trovato")
    except OSError as e:
        raise RuntimeError(f"Connessione fallita: {e}")
    log("IMAP", "Connesso", GREEN)

    log("Login", f"Autenticazione come {cfg['user']}...")
    try:
        conn.login(cfg["user"], cfg["password"])
    except imaplib.IMAP4.error as e:
        raise RuntimeError(f"Login rifiutato: {e}. Per Gmail usa una Password per le app "
                           "e verifica che IMAP sia attivo.")
    log("Login", "Login effettuato", GREEN)

    status, data = conn.select(cfg["folder"], readonly=True)
    if status != "OK":
        raise RuntimeError(f"Cartella '{cfg['folder']}' non trovata")
    log("Mailbox", f"Cartella {cfg['folder']} aperta ({data[0].decode()} messaggi totali, sola lettura)", GREEN)
    return conn


def search_ids(conn, cfg):
    since = (datetime.now() - timedelta(days=cfg["days_back"])).strftime("%d-%b-%Y")
    status, data = conn.uid("SEARCH", None, "SINCE", since)
    if status != "OK":
        return []
    return data[0].split()


def get_body(msg):
    """Restituisce (testo, html) del messaggio."""
    text, html_body = "", ""
    parts = msg.walk() if msg.is_multipart() else [msg]
    for part in parts:
        if part.get_content_maintype() == "multipart":
            continue
        if "attachment" in str(part.get("Content-Disposition", "")).lower():
            continue
        payload = part.get_payload(decode=True)
        if payload is None:
            continue
        charset = part.get_content_charset() or "utf-8"
        try:
            content = payload.decode(charset, errors="replace")
        except LookupError:
            content = payload.decode("utf-8", errors="replace")
        if part.get_content_type() == "text/plain" and not text:
            text = content
        elif part.get_content_type() == "text/html" and not html_body:
            html_body = content
    return text, html_body


def html_to_text(src):
    src = re.sub(r"(?is)<(script|style).*?</\1>", "", src)
    src = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</tr>", "\n", src)
    src = re.sub(r"<[^>]+>", "", src)
    src = html.unescape(src)
    return re.sub(r"\n\s*\n+", "\n\n", src).strip()


def extract_links(text, html_body):
    links = re.findall(r'href=["\'](https?://[^"\']+)["\']', html_body, re.I)
    links += re.findall(r"https?://[^\s<>\"')\]]+", text)
    seen, out = set(), []
    for link in links:
        link = html.unescape(link)
        if link not in seen:
            seen.add(link)
            out.append(link)
    return out


def show_message(conn, uid, cfg):
    status, data = conn.uid("FETCH", uid, "(BODY.PEEK[])")  # PEEK: non segna come letta
    if status != "OK" or not data or data[0] is None:
        return False
    msg = email.message_from_bytes(data[0][1])
    sender = decode(msg.get("From"))
    subject = decode(msg.get("Subject"))

    if cfg["from_contains"] and cfg["from_contains"] not in sender.lower():
        return False
    if cfg["subject_contains"] and cfg["subject_contains"] not in subject.lower():
        return False

    try:
        date = parsedate_to_datetime(msg.get("Date")).strftime("%d/%m/%Y %H:%M")
    except Exception:
        date = msg.get("Date", "?")

    text, html_body = get_body(msg)
    body = text.strip() or html_to_text(html_body)

    print(f"{GREY}{'-' * 70}{RESET}")
    print(f"{MAGENTA}  Data    :{RESET} {date}")
    print(f"{MAGENTA}  Da      :{RESET} {sender}")
    print(f"{MAGENTA}  Oggetto :{RESET} {WHITE}{subject}{RESET}")
    preview = body[: cfg["preview_chars"]]
    if preview:
        print(f"{MAGENTA}  Testo   :{RESET}")
        for line in preview.splitlines():
            if line.strip():
                print(f"    {line.strip()}")
        if len(body) > cfg["preview_chars"]:
            print(f"    {GREY}[...]{RESET}")
    if cfg["show_links"]:
        links = extract_links(text, html_body)
        if links:
            print(f"{MAGENTA}  Link    :{RESET}")
            for link in links[:15]:
                print(f"    {YELLOW}{link}{RESET}")
    return True


# ------------------------------------------------------------------ main

def run():
    print(f"{WHITE}=== IMAP Viewer ==={RESET}\n")
    cfg = load_config()
    conn = connect(cfg)

    uids = search_ids(conn, cfg)
    log("Search", f"{len(uids)} email negli ultimi {cfg['days_back']} giorni, applico i filtri...")
    shown = 0
    for uid in reversed(uids):  # dalla più recente
        if shown >= cfg["max_messages"]:
            break
        if show_message(conn, uid, cfg):
            shown += 1
    if shown:
        print(f"{GREY}{'-' * 70}{RESET}")
    log("Search", f"{shown} email corrispondenti ai filtri", GREEN if shown else YELLOW)

    if not cfg["watch"]:
        conn.logout()
        log("IMAP", "Disconnesso")
        return

    seen = set(uids)
    log("Watch", f"In ascolto di nuove email ogni {cfg['interval']}s (Ctrl+C per fermare)...", WHITE)
    while True:
        time.sleep(cfg["interval"])
        try:
            conn.noop()
            conn.select(cfg["folder"], readonly=True)
            current = search_ids(conn, cfg)
        except (imaplib.IMAP4.abort, OSError):
            log("Watch", "Connessione persa, riconnessione...", YELLOW)
            conn = connect(cfg)
            current = search_ids(conn, cfg)
        new = [u for u in current if u not in seen]
        seen.update(current)
        found = 0
        for uid in new:
            if show_message(conn, uid, cfg):
                found += 1
        if found:
            print(f"{GREY}{'-' * 70}{RESET}")
            log("Watch", f"{found} nuova/e email", GREEN)
        else:
            log("Watch", "Nessuna nuova email", GREY)


if __name__ == "__main__":
    try:
        run()
        press_any_key_to_exit(0)
    except KeyboardInterrupt:
        print()
        log("Exit", "Interrotto dall'utente", YELLOW)
        press_any_key_to_exit(0)
    except RuntimeError as e:
        log("Error", str(e), RED)
        press_any_key_to_exit(1)
    except Exception as e:
        log("Error", f"Errore imprevisto: {type(e).__name__}: {e}", RED)
        press_any_key_to_exit(1)
