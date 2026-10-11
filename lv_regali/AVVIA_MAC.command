#!/bin/bash
cd "$(dirname "$0")"
echo "Installo/aggiorno i componenti necessari (solo la prima volta ci mette qualche minuto)..."
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
echo
echo "Avvio la ricerca su Louis Vuitton: NON chiudere la finestra del browser che si apre."
python3 lv_regali.py "$@"
[ -f lv_regali.pdf ] && open lv_regali.pdf
read -p "Premi Invio per chiudere..."
