@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=
where py >nul 2>nul && set PY=py
if not defined PY where python >nul 2>nul && set PY=python
if not defined PY (
  echo Python nije instaliran. Otvaram stranicu za preuzimanje...
  echo Pri instalaciji obavezno stikliraj "Add python.exe to PATH", pa ponovo pokreni ovaj fajl.
  start https://www.python.org/downloads/
  pause
  exit /b 1
)
if not exist ".instalirano" (
  echo Prvo pokretanje: instaliram potrebne pakete, sacekaj...
  %PY% -m pip install --upgrade -r requirements.txt
  if errorlevel 1 (
    pause
    exit /b 1
  )
  %PY% -m pip install libpff-python >nul 2>nul
  if errorlevel 1 echo Napomena: PST podrska nije instalirana - ostali formati rade.
  echo ok> .instalirano
)
start "" %PY%w mailconv_gui.pyw
