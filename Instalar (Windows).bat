@echo off
rem Dois cliques para instalar no Windows. Ao terminar, o painel abre no navegador.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"
if errorlevel 1 (
  echo.
  echo A instalacao nao terminou. Veja a mensagem acima.
  pause
  exit /b 1
)
call "%~dp0Abrir painel.bat"
