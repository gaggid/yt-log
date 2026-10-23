@echo off
cd /d "%~dp0"
rem Runs the app plus the git auto-deploy watcher, using the project's own virtual environment (.venv).
if not exist ".venv\Scripts\python.exe" (
  echo Creating .venv ...
  python -m venv .venv
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
)
".venv\Scripts\python.exe" watch.py
