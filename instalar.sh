#!/bin/bash
# Instalação no Mac (chamada pelo "Instalar (Mac).command"). Pergunta antes de
# cada download. Nada fica agendado nem rodando depois: a ferramenta só roda
# quando alguém manda.
set -e
cd "$(dirname "$0")"
pergunta() { read -r -p "$1 [s/N] " r; [[ "$r" =~ ^[sS] ]]; }

echo "======================================================"
echo " Relatório de Andamentos: instalação no Mac"
echo "======================================================"

echo; echo "== 1/5 Homebrew (instalador de programas do Mac)"
if ! command -v brew >/dev/null; then
  for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)"; done
fi
if ! command -v brew >/dev/null; then
  echo "O Homebrew não está instalado. O instalador oficial (https://brew.sh) vai pedir a senha do Mac."
  if pergunta "Instalar o Homebrew agora?"; then
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
    for b in /opt/homebrew/bin/brew /usr/local/bin/brew; do [ -x "$b" ] && eval "$("$b" shellenv)"; done
  fi
  command -v brew >/dev/null || { echo "Sem o Homebrew não dá para seguir. Instale por https://brew.sh e rode de novo."; exit 1; }
fi
echo "ok"

echo; echo "== 2/5 Python 3.11 ou mais novo"
PY=""
for c in python3.13 python3.12 python3.11 python3; do
  if command -v "$c" >/dev/null && "$c" -c "import sys; sys.exit(sys.version_info < (3, 11))" 2>/dev/null; then PY="$(command -v "$c")"; break; fi
done
if [ -z "$PY" ]; then
  if pergunta "Python 3.11+ não encontrado. Instalar pelo Homebrew?"; then
    brew install python@3.12
    PY="$(brew --prefix)/bin/python3.12"
  else
    echo "Sem Python 3.11+ não dá para seguir."; exit 1
  fi
fi
echo "ok ($("$PY" --version))"

echo; echo "== 3/5 Leitura de documentos digitalizados (OCR, opcional)"
FALTA=""
for c in pdftotext ocrmypdf tesseract; do command -v "$c" >/dev/null || FALTA="$FALTA $c"; done
if [ -n "$FALTA" ]; then
  echo "Sem estas ferramentas, PDFs com texto continuam sendo lidos; só os digitalizados (imagem) ficam sem texto."
  pergunta "Instalar poppler, ocrmypdf e tesseract (português) pelo Homebrew?" && brew install poppler ocrmypdf tesseract tesseract-lang || true
else
  echo "ok"
fi

echo; echo "== 4/5 Ambiente da ferramenta (pacotes Python e navegador de automação, ~300 MB)"
"$PY" -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python -m playwright install chromium
mkdir -p projetos
[ -f config.json ] || cp config.exemplo.json config.json
chmod +x rodar.sh conferir.sh "Abrir painel.command" "Instalar (Mac).command" revisar.command cadastro.command 2>/dev/null || true
echo "ok"

echo; echo "== 5/5 IA local (resume os documentos sem enviar nada para a internet)"
MODELO=$(cd src && ../.venv/bin/python -c "import resumir; print(resumir.modelo_escolhido())")
echo "Modelo indicado para a memória deste Mac: $MODELO"
if ! command -v ollama >/dev/null; then
  pergunta "Instalar o Ollama (motor da IA local, ~50 MB) pelo Homebrew?" && brew install ollama || true
fi
if command -v ollama >/dev/null; then
  if pergunta "Baixar o modelo $MODELO (2 a 3,5 GB)?"; then
    ollama serve >/dev/null 2>&1 &
    PID_OLLAMA=$!
    sleep 3
    ollama pull "$MODELO"
    kill "$PID_OLLAMA" 2>/dev/null || true   # nada fica rodando depois da instalação
  fi
else
  echo "Sem o Ollama, os andamentos são coletados normalmente, mas os documentos entram na revisão sem resumo."
fi

echo
echo "======================================================"
echo " Instalação concluída. O painel vai abrir no navegador."
echo " Primeiro passo: 'Acesso e escritório' (canto superior"
echo " direito): senha do certificado e segredo do autenticador."
echo "======================================================"
