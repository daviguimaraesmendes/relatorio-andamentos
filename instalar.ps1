# Instalação no Windows (chamada pelo "Instalar (Windows).bat"). Pergunta antes
# de cada download. Nada fica agendado: a ferramenta só roda quando alguém manda.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
function Pergunta($texto) { $r = Read-Host "$texto [s/N]"; return ($r -match '^[sS]') }
function Atualiza-Path { $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" + [Environment]::GetEnvironmentVariable("Path","User") }
function Roda-Py($cmd, [string[]]$resto) {
  if ($cmd.Count -gt 1) { & $cmd[0] $cmd[1] @resto } else { & $cmd[0] @resto }
}
function Acha-Python {
  foreach ($c in @(@("py","-3.13"), @("py","-3.12"), @("py","-3.11"), @("python"))) {
    try {
      $ok = Roda-Py $c @("-c", "import sys; print(sys.version_info >= (3, 11))") 2>$null
      if ($ok -eq "True") { return ,$c }
    } catch {}
  }
  return $null
}

Write-Host "======================================================"
Write-Host " Relatório de Andamentos: instalação no Windows"
Write-Host "======================================================"

Write-Host "`n== 1/4 Python 3.11 ou mais novo"
$py = Acha-Python
if (-not $py) {
  if ((Get-Command winget -ErrorAction SilentlyContinue) -and (Pergunta "Python 3.11+ não encontrado. Instalar o Python 3.12 pelo winget?")) {
    winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
    Atualiza-Path
    $py = Acha-Python
  }
  if (-not $py) {
    Write-Host "Instale o Python 3.12 por https://www.python.org/downloads/ marcando 'Add python.exe to PATH' e rode de novo."
    Read-Host "Enter para fechar"; exit 1
  }
}
Write-Host "ok"

Write-Host "`n== 2/4 Ambiente da ferramenta (pacotes Python e navegador de automação, ~300 MB)"
Roda-Py $py @("-m", "venv", ".venv")
$vpy = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
& $vpy -m pip install -q --upgrade pip
& $vpy -m pip install -q -r requirements.txt
& $vpy -m playwright install chromium
New-Item -ItemType Directory -Force -Path projetos | Out-Null
if (-not (Test-Path config.json)) { Copy-Item config.exemplo.json config.json }
Write-Host "ok"

Write-Host "`n== 3/4 IA local (resume os documentos sem enviar nada para a internet)"
Push-Location src
$modelo = (& $vpy -c "import resumir; print(resumir.modelo_escolhido())").Trim()
Pop-Location
Write-Host "Modelo indicado para a memória deste computador: $modelo"
if (-not (Get-Command ollama -ErrorAction SilentlyContinue)) {
  if ((Get-Command winget -ErrorAction SilentlyContinue) -and (Pergunta "Instalar o Ollama (motor da IA local) pelo winget?")) {
    winget install -e --id Ollama.Ollama --accept-package-agreements --accept-source-agreements
    Atualiza-Path
  }
}
if (Get-Command ollama -ErrorAction SilentlyContinue) {
  if (Pergunta "Baixar o modelo $modelo (2 a 3,5 GB)?") {
    $servidor = $null
    try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://127.0.0.1:11434/api/tags | Out-Null }
    catch { $servidor = Start-Process ollama -ArgumentList "serve" -WindowStyle Hidden -PassThru; Start-Sleep 4 }
    ollama pull $modelo
    if ($servidor) { Stop-Process -Id $servidor.Id -ErrorAction SilentlyContinue }
  }
} else {
  Write-Host "Sem o Ollama, os andamentos são coletados normalmente, mas os documentos entram na revisão sem resumo."
}

Write-Host "`n== 4/4 Leitura de documentos digitalizados (OCR)"
Write-Host "No Windows, PDFs com texto são lidos normalmente; os digitalizados (imagem) entram na revisão com alerta."

Write-Host "`n======================================================"
Write-Host " Instalação concluída. O painel vai abrir no navegador."
Write-Host " Primeiro passo: 'Acesso e escritório' (canto superior"
Write-Host " direito): senha do certificado e segredo do autenticador."
Write-Host "======================================================"
