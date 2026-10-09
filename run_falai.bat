@echo off
setlocal

rem === Inicializador do FALAI (Windows) ===
rem Se existir .venv, usa o Python dela. Caso contrário, usa o Python do sistema.

set "APP_DIR=%~dp0"
cd /d "%APP_DIR%"

if exist ".venv\Scripts\python.exe" (
  set "PYTHON=.venv\Scripts\python.exe"
) else (
  set "PYTHON=python"
)

%PYTHON% main.py
