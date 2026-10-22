@echo off
cd /d "%~dp0"
rem Runs the app plus the git auto-deploy watcher. Use a venv python here if you have one.
python watch.py
