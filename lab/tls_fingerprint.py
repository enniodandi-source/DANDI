#!/usr/bin/env python3
"""
Analisi del fingerprint TLS (JA3) — estensione del lab anti-bot.

Molti sistemi anti-bot classificano il client GIA' PRIMA del livello HTTP,
guardando il ClientHello TLS: l'ordine e l'insieme di cipher suite, estensioni,
gruppi di curve, ecc. Questa "firma" (JA3) dipende dalla libreria TLS usata e
NON e' modificabile cambiando gli header HTTP. Un client come `requests`
(OpenSSL) produce un JA3 diverso da Chrome (BoringSSL), a prescindere dallo
User-Agent che dichiara.

Questo script apre un mini-server TLS locale che, invece di completare
l'handshake, CATTURA il ClientHello grezzo e ne calcola il JA3. Poi lancia
diversi client contro di se' e confronta le firme.

Tutto su 127.0.0.1: nessun servizio di terzi coinvolto. Serve a documentare
un segnale di detection, non ad aggirarne uno.
"""

import socket
import struct
import hashlib
import threading
import subprocess
import ssl
import sys

HOST = "127.0.0.1"

# Valori GREASE (RFC 8701): vanno esclusi dal calcolo JA3 perche' casuali.
GREASE = {
    0x0a0a, 0x1a1a, 0x2a2a, 0x3a3a, 0x4a4a, 0x5a5a, 0x6a6a, 0x7a7a,
    0x8a8a, 0x9a9a, 0xacac, 0xbaba, 0xcaca, 0xdada, 0xeaea, 0xfafa,
}


# ---------------------------------------------------------------------------
# Parsing del ClientHello e calcolo JA3
# ---------------------------------------------------------------------------
def parse_client_hello(data: bytes):
    """
    Parsa un record TLS contenente un ClientHello e restituisce la stringa
    JA3 e il suo hash MD5. Ritorna None se i byte non sono un ClientHello.

    JA3 = SSLVersion,Ciphers,Extensions,EllipticCurves,ECPointFormats
    """
    try:
        # Record layer: type(1)=22 handshake, version(2), length(2)
        if data[0] != 0x16:
            return None
        pos = 5  # salta record header

        # Handshake header: msg_type(1)=1 ClientHello, length(3)
        if data[pos] != 0x01:
            return None
        pos += 4

        # client_version (2 byte) -> campo 1 del JA3
        client_version = struct.unpack(">H", data[pos:pos + 2])[0]
        pos += 2

        pos += 32  # random (32 byte)

        # session_id
        sid_len = data[pos]
        pos += 1 + sid_len

        # cipher suites -> campo 2
        cs_len = struct.unpack(">H", data[pos:pos + 2])[0]
        pos += 2
        ciphers = []
        for i in range(0, cs_len, 2):
            c = struct.unpack(">H", data[pos + i:pos + i + 2])[0]
            if c not in GREASE:
                ciphers.append(c)
        pos += cs_len

        # compression methods
        comp_len = data[pos]
        pos += 1 + comp_len

        # extensions
        extensions, curves, point_formats = [], [], []
        if pos < len(data):
            ext_total = struct.unpack(">H", data[pos:pos + 2])[0]
            pos += 2
            end = pos + ext_total
            while pos < end:
                etype = struct.unpack(">H", data[pos:pos + 2])[0]
                elen = struct.unpack(">H", data[pos + 2:pos + 4])[0]
                edata = data[pos + 4:pos + 4 + elen]
                if etype not in GREASE:
                    extensions.append(etype)
                # supported_groups / elliptic_curves (ext 10) -> campo 4
                if etype == 0x000a and len(edata) >= 2:
                    glen = struct.unpack(">H", edata[0:2])[0]
                    for i in range(0, glen, 2):
                        g = struct.unpack(">H", edata[2 + i:4 + i])[0]
                        if g not in GREASE:
                            curves.append(g)
                # ec_point_formats (ext 11) -> campo 5
                if etype == 0x000b and len(edata) >= 1:
                    plen = edata[0]
                    for i in range(plen):
                        point_formats.append(edata[1 + i])
                pos += 4 + elen

        ja3 = "{},{},{},{},{}".format(
            client_version,
            "-".join(map(str, ciphers)),
            "-".join(map(str, extensions)),
            "-".join(map(str, curves)),
            "-".join(map(str, point_formats)),
        )
        return ja3, hashlib.md5(ja3.encode()).hexdigest()
    except (IndexError, struct.error):
        return None


# ---------------------------------------------------------------------------
# Server che cattura UN ClientHello e chiude
# ---------------------------------------------------------------------------
def capture_one(result: dict, port_holder: list, ready: threading.Event):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((HOST, 0))
    port_holder.append(srv.getsockname()[1])
    srv.listen(1)
    srv.settimeout(15)
    ready.set()
    try:
        conn, _ = srv.accept()
        conn.settimeout(5)
        chunks = b""
        while len(chunks) < 8192:
            b = conn.recv(4096)
            if not b:
                break
            chunks += b
            # Il ClientHello sta nel primo record: appena lo abbiamo, basta.
            if len(chunks) >= 5:
                rec_len = struct.unpack(">H", chunks[3:5])[0] + 5
                if len(chunks) >= rec_len:
                    break
        result["hello"] = chunks
        conn.close()
    except socket.timeout:
        result["hello"] = result.get("hello", b"")
    finally:
        srv.close()


def run_client_and_capture(client_fn) -> tuple:
    """Avvia il server di cattura, lancia il client, restituisce il JA3."""
    result, port_holder, ready = {}, [], threading.Event()
    t = threading.Thread(target=capture_one, args=(result, port_holder, ready))
    t.start()
    ready.wait(5)
    port = port_holder[0]
    try:
        client_fn(port)
    except Exception:
        pass  # l'handshake fallira': a noi basta il ClientHello
    t.join(20)
    hello = result.get("hello", b"")
    return parse_client_hello(hello)


# ---------------------------------------------------------------------------
# Client di test
# ---------------------------------------------------------------------------
def client_python_ssl(port: int):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    s = socket.create_connection((HOST, port), timeout=5)
    ss = ctx.wrap_socket(s, server_hostname=HOST)
    ss.close()


def client_curl(port: int):
    subprocess.run(
        ["curl", "-sk", "--max-time", "5", f"https://{HOST}:{port}/"],
        capture_output=True,
    )


CHROME = "/opt/pw-browsers/chromium_headless_shell-1194/chrome-linux/headless_shell"


def client_chromium(port: int):
    subprocess.run(
        [CHROME, "--headless", "--no-sandbox", "--disable-gpu",
         "--ignore-certificate-errors", f"https://{HOST}:{port}/"],
        capture_output=True, timeout=15,
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("#" * 66)
    print("# FINGERPRINT TLS (JA3) — confronto tra client")
    print("# Ogni client si connette a un server locale che cattura il")
    print("# ClientHello. La firma dipende dalla libreria TLS, non dagli header.")
    print("#" * 66)

    clients = [
        ("Python ssl (OpenSSL) ~ requests", client_python_ssl),
        ("curl (OpenSSL)", client_curl),
    ]
    import os
    if os.path.exists(CHROME):
        clients.append(("Chromium headless (BoringSSL)", client_chromium))
    else:
        print("\n[!] Chromium non trovato: salto il confronto con il browser reale.")

    results = []
    for name, fn in clients:
        parsed = run_client_and_capture(fn)
        if parsed:
            ja3, digest = parsed
            results.append((name, ja3, digest))
            print(f"\n=== {name} ===")
            print(f"JA3 hash : {digest}")
            print(f"JA3 str  : {ja3}")
        else:
            print(f"\n=== {name} ===\n[!] ClientHello non catturato/parsato")

    # Confronto finale
    print("\n" + "#" * 66)
    print("# CONFRONTO")
    print("#" * 66)
    digests = {name: d for name, _, d in results}
    for name, d in digests.items():
        print(f"  {d}  {name}")
    unique = set(digests.values())
    print(f"\n  -> {len(unique)} firme distinte su {len(digests)} client.")
    if len(unique) > 1:
        print("  -> Client diversi = JA3 diversi, a parita' di header HTTP.")
        print("     Un anti-bot puo' distinguere `requests`/`curl` da un browser")
        print("     al livello TLS, PRIMA ancora di guardare header o captcha.")


if __name__ == "__main__":
    sys.exit(main())
