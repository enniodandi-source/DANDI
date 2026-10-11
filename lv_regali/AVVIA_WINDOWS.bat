@echo off
cd /d "%~dp0"
set PY=python
where python >nul 2>nul || set PY=py
echo Installo/aggiorno i componenti necessari (solo la prima volta ci mette qualche minuto)...
%PY% -m pip install -r requirements.txt
%PY% -m playwright install chromium
echo.
echo Avvio la ricerca su Louis Vuitton: NON chiudere la finestra del browser che si apre.
%PY% lv_regali.py %*
echo.
if exist lv_regali.pdf start "" lv_regali.pdf
pause
