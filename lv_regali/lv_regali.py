#!/usr/bin/env python3
"""
Idee regalo Louis Vuitton sotto una certa soglia di prezzo, in PDF.

Apre it.louisvuitton.com in un browser vero (Playwright), cerca i prodotti per
parole chiave raggruppate in categorie (gioielli e bijoux, borse, accessori),
tiene solo quelli con prezzo <= soglia e genera un PDF A4 con foto, nome,
prezzo e link, ordinati per categoria e prezzo.

Il sito LV blocca le richieste da server/cloud e spesso i browser "headless":
lancialo dal tuo computer, con la finestra del browser visibile (default).

Installazione (una volta sola):
    pip install playwright
    playwright install chromium

Uso:
    python3 lv_regali.py                         # soglia 1250 €, PDF lv_regali.pdf
    python3 lv_regali.py --max-price 800 --out regali.pdf
    python3 lv_regali.py --categories gioielli accessori
    python3 lv_regali.py --channel chrome        # usa Google Chrome installato
"""

import argparse
import base64
import html
import os
import re
import sys
import time
import urllib.parse
from datetime import date

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
except ImportError:
    sys.exit("Manca Playwright: esegui  pip install playwright && playwright install chromium")

BASE = "https://it.louisvuitton.com"
LOCALE = "ita-it"

# Parole chiave cercate sul sito per ogni categoria
CATEGORIES = {
    "gioielli": ("Gioielli e bijoux", [
        "bracciale", "collana", "orecchini", "anello", "ciondolo",
    ]),
    "borse": ("Borse", [
        "pochette", "mini borsa", "borsa a tracolla", "nano",
    ]),
    "accessori": ("Accessori", [
        "portafoglio", "portacarte", "portachiavi", "charm borsa",
        "foulard", "bandeau", "cintura donna", "occhiali da sole donna",
    ]),
}

# Esclude articoli chiaramente non adatti (uomo, casa, viaggio ingombrante)
EXCLUDE = re.compile(r"\buomo\b|\bmen\b|valigia|baule|horizon|keepall|cane|gatto", re.I)

PRICE_RE = re.compile(r"(?:€\s*)?(\d{1,3}(?:[.   ]\d{3})*(?:,\d{2})?)\s*(?:€|EUR)|€\s*(\d{1,3}(?:[.   ]\d{3})*(?:,\d{2})?)")

# JS eseguito nella pagina: raccoglie le "card" prodotto partendo dai link /products/
EXTRACT_JS = r"""
() => {
  const out = [];
  const seen = new Set();
  for (const a of document.querySelectorAll('a[href*="/products/"]')) {
    const href = a.href.split('?')[0].split('#')[0];
    if (seen.has(href)) continue;
    // risale fino al contenitore che contiene anche il prezzo
    let card = a, hops = 0;
    while (card && hops < 6 && !/€/.test(card.innerText || '')) { card = card.parentElement; hops++; }
    if (!card) continue;
    const text = (card.innerText || '').trim();
    if (!/€/.test(text)) continue;
    const img = card.querySelector('img');
    let src = '';
    if (img) {
      src = img.currentSrc || img.src || '';
      if (!src || src.startsWith('data:')) {
        const ss = img.getAttribute('srcset') || img.getAttribute('data-srcset') || '';
        src = ss.split(',').pop().trim().split(' ')[0] || img.getAttribute('data-src') || src;
      }
    }
    const nameEl = card.querySelector('h2, h3, [class*="name" i], [class*="title" i]');
    seen.add(href);
    out.push({ url: href, text, name: nameEl ? nameEl.innerText.trim() : '', image: src });
  }
  return out;
}
"""


def fmt_eur(value):
    """1250.0 -> '1.250' (formato italiano, senza decimali)."""
    return f"{value:,.0f}".replace(",", ".")


def parse_price(text):
    m = PRICE_RE.search(text or "")
    if not m:
        return None
    raw = (m.group(1) or m.group(2))
    raw = re.sub(r"[.   ]", "", raw).replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def clean_name(item):
    name = item.get("name") or ""
    if not name or "€" in name:
        # prima riga di testo che non sia prezzo/etichetta
        for line in item["text"].splitlines():
            line = line.strip()
            if line and "€" not in line and len(line) > 3 and not re.match(
                    r"^(nuovo|novità|new|esclusiv|aggiungi|preferiti)", line, re.I):
                name = line
                break
    return name or item["url"].rsplit("/", 1)[-1]


def accept_cookies(page):
    for label in ("Accetta tutti", "Accetta tutto", "Accetta", "Accept All", "Accept"):
        try:
            btn = page.get_by_role("button", name=re.compile(label, re.I)).first
            if btn.is_visible(timeout=1500):
                btn.click()
                page.wait_for_timeout(800)
                return
        except Exception:
            pass


def load_all(page, max_rounds=25):
    """Scorre la pagina e clicca 'carica altri' finché il numero di prodotti cresce."""
    last = -1
    for _ in range(max_rounds):
        page.mouse.wheel(0, 20000)
        page.wait_for_timeout(1200)
        for label in ("Carica altri", "Mostra altri", "Visualizza altri", "Load more", "Altri prodotti"):
            try:
                btn = page.get_by_role("button", name=re.compile(label, re.I)).first
                if btn.is_visible(timeout=300):
                    btn.click()
                    page.wait_for_timeout(1500)
            except Exception:
                pass
        count = page.locator('a[href*="/products/"]').count()
        if count == last:
            break
        last = count


def blocked(page):
    title = (page.title() or "").strip().upper()
    body = page.locator("body").inner_text(timeout=5000)[:2000].lower()
    return ("access denied" in body or "accesso negato" in body
            or ("LOUIS VUITTON" == title and page.locator('a[href*="/products/"]').count() == 0
                and "reference #" in body))


def search(page, term, debug_dir=None):
    url = f"{BASE}/{LOCALE}/search/{urllib.parse.quote(term)}"
    try:
        resp = page.goto(url, wait_until="domcontentloaded", timeout=60000)
    except PWTimeout:
        print(f"  ! timeout su '{term}'", file=sys.stderr)
        return []
    if resp and resp.status == 403 or blocked(page):
        raise RuntimeError("Il sito LV ha bloccato il browser (403). Riprova con la finestra "
                           "visibile, con --channel chrome, o più tardi.")
    accept_cookies(page)
    try:
        page.wait_for_selector('a[href*="/products/"]', timeout=15000)
    except PWTimeout:
        if debug_dir:
            slug = re.sub(r"\W+", "_", term)
            page.screenshot(path=f"{debug_dir}/debug_{slug}.png", full_page=True)
        print(f"  ! nessun prodotto trovato per '{term}'", file=sys.stderr)
        return []
    load_all(page)
    return page.evaluate(EXTRACT_JS)


def image_data_uri(context, url):
    if not url:
        return ""
    if url.startswith("//"):
        url = "https:" + url
    try:
        r = context.request.get(url, timeout=20000)
        if r.ok:
            ctype = r.headers.get("content-type", "image/jpeg").split(";")[0]
            return f"data:{ctype};base64," + base64.b64encode(r.body()).decode()
    except Exception:
        pass
    return url


def build_html(products, max_price, categories):
    sections = []
    for key in categories:
        title = CATEGORIES[key][0]
        items = sorted((p for p in products if p["category"] == key), key=lambda p: p["price"])
        if not items:
            continue
        cards = "".join(f"""
        <a class="card" href="{html.escape(p['url'])}">
          <div class="img"><img src="{p['image_data']}" alt=""></div>
          <div class="name">{html.escape(p['name'])}</div>
          <div class="price">&euro; {fmt_eur(p['price'])}</div>
        </a>""" for p in items)
        sections.append(f'<h2>{html.escape(title)} <span>({len(items)})</span></h2>'
                        f'<div class="grid">{cards}</div>')
    body = "".join(sections) or "<p>Nessun prodotto trovato sotto la soglia.</p>"
    return f"""<!doctype html><html lang="it"><head><meta charset="utf-8">
<title>Regali Louis Vuitton</title>
<style>
  @page {{ size:A4; margin:12mm; }}
  body {{ font-family:Georgia,"Times New Roman",serif; color:#19110b; margin:0; }}
  header {{ border-bottom:1px solid #19110b; padding-bottom:8px; margin-bottom:12px; }}
  h1 {{ font-size:22px; letter-spacing:3px; margin:0; text-transform:uppercase; }}
  header p {{ margin:4px 0 0; font-size:12px; color:#555; font-family:Helvetica,Arial,sans-serif; }}
  h2 {{ font-size:15px; letter-spacing:2px; text-transform:uppercase; margin:18px 0 8px;
       break-after:avoid; }}
  h2 span {{ color:#888; font-weight:normal; }}
  .grid {{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; }}
  .card {{ text-decoration:none; color:inherit; break-inside:avoid; border:1px solid #eee;
          padding:6px; font-family:Helvetica,Arial,sans-serif; }}
  .img {{ aspect-ratio:1; background:#f6f5f3; display:flex; align-items:center; justify-content:center; }}
  .img img {{ max-width:100%; max-height:100%; object-fit:contain; }}
  .name {{ font-size:10px; margin-top:6px; min-height:2.6em; }}
  .price {{ font-size:12px; font-weight:bold; margin-top:2px; }}
</style></head><body>
<header><h1>Louis Vuitton &middot; Idee regalo</h1>
<p>Prodotti fino a &euro; {fmt_eur(max_price)} &middot; {len(products)} articoli &middot;
prezzi rilevati su it.louisvuitton.com il {date.today():%d/%m/%Y}</p></header>
{body}
</body></html>"""


def main():
    global BASE
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-price", type=float, default=1250, help="prezzo massimo in euro (default 1250)")
    ap.add_argument("--categories", nargs="+", choices=list(CATEGORIES), default=list(CATEGORIES))
    ap.add_argument("--out", default="lv_regali.pdf", help="file PDF di output")
    ap.add_argument("--headless", action="store_true", help="browser invisibile (più facile da bloccare)")
    ap.add_argument("--channel", help="es. 'chrome' per usare Google Chrome installato")
    ap.add_argument("--debug", action="store_true", help="salva screenshot quando non trova prodotti")
    ap.add_argument("--base", default=BASE, help=argparse.SUPPRESS)  # solo per test
    args = ap.parse_args()
    BASE = args.base.rstrip("/")

    found = {}
    with sync_playwright() as pw:
        exe = os.environ.get("LV_CHROMIUM_PATH")  # opzionale: percorso di un Chromium specifico
        browser = pw.chromium.launch(headless=args.headless, channel=args.channel, executable_path=exe,
                                     args=["--disable-blink-features=AutomationControlled"])
        context = browser.new_context(locale="it-IT", viewport={"width": 1366, "height": 900})
        page = context.new_page()

        for key in args.categories:
            title, terms = CATEGORIES[key]
            for term in terms:
                print(f"[{title}] cerco '{term}'...", file=sys.stderr)
                try:
                    items = search(page, term, "." if args.debug else None)
                except RuntimeError as e:
                    browser.close()
                    sys.exit(str(e))
                kept = 0
                for it in items:
                    price = parse_price(it["text"])
                    name = clean_name(it)
                    if price is None or price > args.max_price or EXCLUDE.search(name + " " + it["url"]):
                        continue
                    if it["url"] not in found:
                        found[it["url"]] = {"url": it["url"], "name": name, "price": price,
                                            "image": it["image"], "category": key}
                        kept += 1
                print(f"   {len(items)} risultati, {kept} nuovi sotto soglia", file=sys.stderr)
                time.sleep(1.5)  # non martellare il sito

        products = list(found.values())
        print(f"Scarico {len(products)} immagini...", file=sys.stderr)
        for p in products:
            p["image_data"] = image_data_uri(context, p["image"])
        browser.close()

        # Il PDF richiede Chromium headless: secondo browser solo per la stampa
        printer = pw.chromium.launch(headless=True, executable_path=exe)
        pg = printer.new_page()
        pg.set_content(build_html(products, args.max_price, args.categories), wait_until="load")
        pg.pdf(path=args.out, format="A4", print_background=True,
               margin={"top": "12mm", "bottom": "12mm", "left": "12mm", "right": "12mm"})
        printer.close()

    print(f"\n{len(products)} prodotti sotto € {fmt_eur(args.max_price)} -> {args.out}")
    for p in sorted(products, key=lambda p: (p["category"], p["price"])):
        print(f"  {CATEGORIES[p['category']][0]:<18} € {p['price']:>8.0f}  {p['name']}")


if __name__ == "__main__":
    main()
