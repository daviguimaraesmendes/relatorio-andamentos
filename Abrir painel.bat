@echo off
rem Abre o painel do Relatorio de Andamentos (so neste computador, em 127.0.0.1).
rem Deixe esta janela aberta enquanto usa o painel; fecha-la encerra o painel.
rem Se um painel de versao antiga ainda estiver aberto, ele e reiniciado (salvo coleta em andamento).
cd /d "%~dp0src"
if not exist "..\.venv\Scripts\python.exe" (
  echo Ferramenta ainda nao instalada. Dois cliques em "Instalar (Windows).bat".
  pause
  exit /b 1
)
..\.venv\Scripts\python.exe abrir_painel.py %*
pause
