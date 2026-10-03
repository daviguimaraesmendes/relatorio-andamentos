@echo off
rem Abre o painel do Relatorio de Andamentos (so neste computador, em 127.0.0.1).
rem Deixe esta janela aberta enquanto usa o painel; fecha-la encerra o painel.
cd /d "%~dp0src"
if not exist "..\.venv\Scripts\python.exe" (
  echo Ferramenta ainda nao instalada. Dois cliques em "Instalar (Windows).bat".
  pause
  exit /b 1
)
..\.venv\Scripts\python.exe revisao.py --abrir
pause
