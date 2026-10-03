#!/bin/bash
# Abre o painel do Relatório de Andamentos (só neste computador, em 127.0.0.1).
# Deixe esta janela aberta enquanto usa o painel; fechá-la encerra o painel.
DIR="$(cd "$(dirname "$0")" && pwd)"
[ -x "$DIR/.venv/bin/python" ] || { echo "Ferramenta ainda não instalada. Dois cliques em 'Instalar (Mac).command'."; read -r; exit 1; }
cd "$DIR/src"
PORTA=$(../.venv/bin/python -c "import comum; print(comum.config().get('porta_revisao', 5072))")
if curl -s -m 2 -o /dev/null "http://127.0.0.1:$PORTA/"; then
  open "http://127.0.0.1:$PORTA/${1:-}"   # já está aberto: só mostra
  exit 0
fi
exec ../.venv/bin/python revisao.py --abrir
