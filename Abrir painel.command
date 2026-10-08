#!/bin/bash
# Abre o painel do Relatório de Andamentos (só neste computador, em 127.0.0.1).
# Deixe esta janela aberta enquanto usa o painel; fechá-la encerra o painel.
DIR="$(cd "$(dirname "$0")" && pwd)"
[ -x "$DIR/.venv/bin/python" ] || { echo "Ferramenta ainda não instalada. Dois cliques em 'Instalar (Mac).command'."; read -r; exit 1; }
cd "$DIR/src"
exec ../.venv/bin/python abrir_painel.py "$@"
