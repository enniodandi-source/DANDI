#!/usr/bin/env python3
"""
Stock della collezione IKEA KONSTRUNDA in un negozio specifico.

Cerca tutti i prodotti della collezione sul sito IKEA Italia, poi interroga
l'API di disponibilità e stampa, per il negozio scelto, quantità a magazzino,
probabilità di trovarlo oggi, eventuale rifornimento previsto e ubicazione
(corsia/scaffale) quando disponibile.

Uso:
    python3 konstrunda_stock.py                       # KONSTRUNDA @ Roma Anagnina
    python3 konstrunda_stock.py --store "Porta di Roma"
    python3 konstrunda_stock.py --query "konstrunda" --json
    python3 konstrunda_stock.py --html konstrunda_anagnina.html
"""

import argparse
import base64
import html
import json
import sys
import urllib.parse
import urllib.request

COUNTRY = "it"
LANG = "it"
SEARCH_URL = f"https://sik.search.blue.cdtapps.com/{COUNTRY}/{LANG}/search-result-page"
STORES_URL = f"https://www.ikea.com/{COUNTRY}/{LANG}/meta-data/informera/stores-detailed.json"
AVAIL_URL = f"https://api.ingka.ikea.com/cia/availabilities/ru/{COUNTRY}"
# Client id pubblico usato dal sito ikea.com per l'API di disponibilità
CLIENT_ID = "b6c117e5-ae61-4ef5-b4cc-e0b1e37f0631"

MESSAGES = {
    "HIGH_IN_STOCK": "Disponibile",
    "LOW_IN_STOCK": "Pochi pezzi",
    "OUT_OF_STOCK": "Esaurito",
}


def get_json(url, headers=None):
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        **(headers or {}),
    })
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def find_store(name):
    stores = get_json(STORES_URL)
    needle = name.lower()
    matches = [s for s in stores
               if needle in s["name"].lower() or needle in (s.get("displayName") or "").lower()]
    if not matches:
        names = ", ".join(sorted(s["name"] for s in stores))
        sys.exit(f"Negozio '{name}' non trovato. Negozi disponibili: {names}")
    if len(matches) > 1:
        sys.exit("Nome negozio ambiguo: " + ", ".join(s["name"] for s in matches))
    return matches[0]


def search_products(query):
    params = urllib.parse.urlencode({"q": query, "size": 200, "types": "PRODUCT"})
    data = get_json(f"{SEARCH_URL}?{params}")
    items = data["searchResultPage"]["products"]["main"]["items"]
    products = []
    for it in items:
        p = it["product"]
        # Tiene solo i prodotti della collezione (il nome è il nome della serie)
        if p["name"].lower() != query.lower():
            continue
        desc = ", ".join(x for x in (p.get("typeName"), p.get("validDesignText"),
                                     p.get("itemMeasureReferenceText")) if x)
        products.append({
            "itemNo": p["itemNo"],
            "name": p["name"],
            "description": desc,
            "price": p.get("salesPrice", {}).get("numeral"),
            "url": p.get("pipUrl"),
            "image": p.get("mainImageUrl"),
        })
    return products


def get_availability(item_nos, store_id):
    result = {}
    # L'API accetta più articoli per chiamata; lotti da 50 per sicurezza
    for i in range(0, len(item_nos), 50):
        chunk = ",".join(item_nos[i:i + 50])
        params = urllib.parse.urlencode({
            "itemNos": chunk,
            "expand": "StoresList,Restocks,SalesLocations",
        })
        data = get_json(f"{AVAIL_URL}?{params}", {"X-Client-Id": CLIENT_ID})
        for a in data.get("availabilities", []):
            cu = a.get("classUnitKey", {})
            if cu.get("classUnitType") != "STO" or cu.get("classUnitCode") != str(store_id):
                continue
            cc = a.get("buyingOption", {}).get("cashCarry", {})
            av = cc.get("availability", {})
            msg = av.get("probability", {}).get("thisDay", {}).get("messageType")
            restocks = av.get("restocks") or []
            locations = []
            for loc in cc.get("salesLocations") or []:
                parts = [loc.get("type")]
                aisle = loc.get("aisleAndBin") or {}
                if aisle:
                    parts.append(f"corsia {aisle.get('aisle')} scaffale {aisle.get('bin')}")
                locations.append(" ".join(p for p in parts if p))
            result[a["itemKey"]["itemNo"]] = {
                "inRange": cc.get("range", {}).get("inRange"),
                "quantity": av.get("quantity"),
                "status": msg,
                "updated": av.get("updateDateTime"),
                "restock": (f"{restocks[0].get('earliestDate')} → {restocks[0].get('latestDate')}"
                            f" ({restocks[0].get('quantity')} pz)") if restocks else None,
                "locations": locations,
            }
    return result


def fetch_image_data_uri(url):
    """Scarica l'immagine e la restituisce come data URI (pagina leggibile offline)."""
    if not url:
        return ""
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            ctype = resp.headers.get_content_type() or "image/jpeg"
            return f"data:{ctype};base64," + base64.b64encode(resp.read()).decode()
    except OSError:
        return url


def write_html(path, query, store, products):
    available = [p for p in products if p.get("quantity")]
    cards = []
    for p in available:
        cards.append(f"""
      <a class="card" href="{html.escape(p.get('url') or '#')}" target="_blank" rel="noopener">
        <img src="{fetch_image_data_uri(p.get('image'))}" alt="{html.escape(p['description'])}">
        <div class="info">
          <div class="name">{html.escape(p['name'])}</div>
          <div class="desc">{html.escape(p['description'])}</div>
          <div class="row"><span class="price">€{p['price']:.2f}</span>
            <span class="qty">{p['quantity']} pz</span></div>
          <div class="sku">Art. {p['itemNo'][:3]}.{p['itemNo'][3:6]}.{p['itemNo'][6:]}</div>
        </div>
      </a>""".replace("€", "&euro;"))
    page = f"""<!doctype html>
<html lang="it"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(query.upper())} disponibili</title>
<style>
  :root {{ --bg:#f6f6f4; --card:#fff; --fg:#111; --muted:#666; --accent:#0058a3; --ok:#0a8a00; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --bg:#141414; --card:#1f1f1f; --fg:#eee; --muted:#aaa; --accent:#5aa9ff; --ok:#4cc94c; }}
  }}
  body {{ margin:0; padding:24px 16px; background:var(--bg); color:var(--fg);
         font-family:system-ui,-apple-system,"Segoe UI",sans-serif; }}
  h1 {{ margin:0 0 4px; font-size:1.5rem; }}
  p.sub {{ margin:0 0 20px; color:var(--muted); }}
  .grid {{ display:grid; gap:16px; grid-template-columns:repeat(auto-fill,minmax(200px,1fr)); }}
  .card {{ background:var(--card); border-radius:10px; overflow:hidden; text-decoration:none;
          color:inherit; box-shadow:0 1px 3px rgba(0,0,0,.08); display:flex; flex-direction:column; }}
  .card img {{ width:100%; aspect-ratio:1; object-fit:contain; background:#fff; }}
  .info {{ padding:12px; display:flex; flex-direction:column; gap:4px; }}
  .name {{ font-weight:700; }}
  .desc {{ color:var(--muted); font-size:.9rem; min-height:2.4em; }}
  .row {{ display:flex; justify-content:space-between; align-items:baseline; margin-top:4px; }}
  .price {{ font-size:1.3rem; font-weight:700; }}
  .qty {{ color:var(--ok); font-weight:600; font-size:.9rem; }}
  .sku {{ color:var(--muted); font-size:.8rem; }}
</style></head><body>
  <h1>{html.escape(query.upper())} &mdash; {html.escape(store['name'])}</h1>
  <p class="sub">{len(available)} articoli disponibili su {len(products)} della collezione</p>
  <div class="grid">{''.join(cards)}
  </div>
</body></html>
"""
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(page)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--query", default="konstrunda", help="nome della collezione")
    ap.add_argument("--store", default="Anagnina", help="nome (anche parziale) del negozio")
    ap.add_argument("--json", action="store_true", help="output in JSON")
    ap.add_argument("--html", metavar="FILE", help="salva una pagina con foto e prezzi dei disponibili")
    args = ap.parse_args()

    store = find_store(args.store)
    products = search_products(args.query)
    if not products:
        sys.exit(f"Nessun prodotto trovato per '{args.query}'.")
    avail = get_availability([p["itemNo"] for p in products], store["id"])

    for p in products:
        p.update(avail.get(p["itemNo"], {"inRange": None, "quantity": None, "status": None}))
    products.sort(key=lambda p: -(p.get("quantity") or 0))

    if args.html:
        write_html(args.html, args.query, store, products)
        print(f"Pagina salvata in {args.html}", file=sys.stderr)

    if args.json:
        print(json.dumps({"store": store["name"], "products": products}, ensure_ascii=False, indent=2))
        return

    print(f"{args.query.upper()} — {store['name']} (id {store['id']}) — {len(products)} articoli\n")
    print(f"{'Articolo':<10} {'Prezzo':>8} {'Qtà':>5}  {'Stato':<12} Descrizione")
    print("-" * 90)
    in_stock = 0
    for p in products:
        if p.get("inRange") is False:
            status = "Non venduto"
        else:
            status = MESSAGES.get(p.get("status"), p.get("status") or "n/d")
        qty = "-" if p.get("quantity") is None else p["quantity"]
        if p.get("quantity"):
            in_stock += 1
        price = f"€{p['price']}" if p.get("price") is not None else "-"
        print(f"{p['itemNo']:<10} {price:>8} {qty:>5}  {status:<12} {p['description']}")
        extra = []
        if p.get("locations"):
            extra.append("Ubicazione: " + "; ".join(p["locations"]))
        if p.get("restock"):
            extra.append("Rifornimento: " + p["restock"])
        if extra:
            print(" " * 30 + " | ".join(extra))
    print("-" * 90)
    print(f"Disponibili a magazzino: {in_stock}/{len(products)}")


if __name__ == "__main__":
    main()
