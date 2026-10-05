@echo off
title IMAP Viewer
cd /d "%~dp0"
where py >nul 2>nul && (py -3 imap_viewer.py & goto :eof)
where python >nul 2>nul && (python imap_viewer.py & goto :eof)
echo Python non trovato. Installalo da https://www.python.org/downloads/
echo (durante l'installazione spunta "Add Python to PATH")
pause
