# Monta a pasta que o Inno Setup empacota: Python embutido + pacotes + codigo.
# Roda no Windows (localmente ou no GitHub Actions):  .\instalador\montar.ps1
# Resultado: build\app\  (python\, src\, assets\, ...). Nao inclui dados de clientes.
param(
  [string]$PythonVersion = "3.12.10",
  [string]$Saida = "build\app"
)
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"   # Invoke-WebRequest muito mais rapido
$raiz = Split-Path -Parent $PSScriptRoot
Set-Location $raiz

function Confere($etapa) { if ($LASTEXITCODE -ne 0) { throw "Falhou: $etapa (codigo $LASTEXITCODE)" } }

if (Test-Path $Saida) { Remove-Item -Recurse -Force $Saida }
New-Item -ItemType Directory -Force -Path $Saida | Out-Null
$saida = (Resolve-Path $Saida).Path
$py = Join-Path $saida "python"
$cache = Join-Path $raiz "build\cache"
New-Item -ItemType Directory -Force -Path $cache | Out-Null

Write-Host "== 1/4 Python $PythonVersion embutido"
$zip = Join-Path $cache "python-$PythonVersion-embed-amd64.zip"
if (-not (Test-Path $zip)) {
  Invoke-WebRequest "https://www.python.org/ftp/python/$PythonVersion/python-$PythonVersion-embed-amd64.zip" -OutFile $zip
}
Expand-Archive $zip -DestinationPath $py
$partes = $PythonVersion.Split(".")
$pth = Join-Path $py ("python{0}{1}._pth" -f $partes[0], $partes[1])
if (-not (Test-Path $pth)) { throw "Arquivo $pth nao encontrado no Python embutido." }
# liga o site-packages (pip e pacotes) e deixa o codigo do programa no caminho de importacao
$linhas = (Get-Content $pth) -replace '^#\s*import site', 'import site'
$linhas += "..\src"
Set-Content -Path $pth -Value $linhas -Encoding ascii

Write-Host "== 2/4 pip e pacotes"
$getpip = Join-Path $cache "get-pip.py"
if (-not (Test-Path $getpip)) { Invoke-WebRequest "https://bootstrap.pypa.io/get-pip.py" -OutFile $getpip }
& "$py\python.exe" $getpip --no-warn-script-location -q; Confere "get-pip"
& "$py\python.exe" -m pip install --no-warn-script-location -q -r requirements.txt; Confere "pip install"

Write-Host "== 3/4 Codigo do programa"
Copy-Item -Recurse src (Join-Path $saida "src")
Copy-Item -Recurse assets (Join-Path $saida "assets")
Remove-Item (Join-Path $saida "assets\gerar_icone.py") -ErrorAction SilentlyContinue
foreach ($f in "movimentos.json", "config.exemplo.json", "requirements.txt", "README.md") { Copy-Item $f $saida }
New-Item -ItemType Directory -Force -Path (Join-Path $saida "projetos") | Out-Null
Get-ChildItem $saida -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

Write-Host "== 4/4 Conferencia: nada de cliente no pacote"
$cfg = Get-Content (Join-Path $saida "config.exemplo.json") -Raw | ConvertFrom-Json
if ($cfg.identificadores_escritorio.Count -gt 0 -or $cfg.revisor) {
  throw "config.exemplo.json tem dados do escritorio. Limpe antes de gerar o instalador."
}
$cnj = '\b[0-9]{7}-[0-9]{2}\.[0-9]{4}\.[0-9]\.[0-9]{2}\.[0-9]{4}\b'
$permitidos = '0000000-00\.0000\.0\.00\.0000|9999999-99\.9999\.9\.99\.9999|123456[7-9]-|1234570-'
$achados = Get-ChildItem $saida -Recurse -File -Include *.py, *.json, *.md, *.txt -Exclude "*.dist-info" |
  Where-Object { $_.FullName -notlike "*\python\*" } |
  Select-String -Pattern $cnj | Where-Object { $_.Line -notmatch $permitidos }
if ($achados) {
  $achados | ForEach-Object { Write-Host ("  " + $_.Path + ":" + $_.LineNumber) }
  throw "O pacote contem numero de processo. Revise antes de publicar."
}
Write-Host "Pronto: $saida"
