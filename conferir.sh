#!/bin/bash
# Conferência pelo terminal (o mesmo que o botão Conferir do painel). Sem IA.
# Uso: ./conferir.sh --projeto <pasta em projetos/> [--dias 7]
DIR="$(cd "$(dirname "$0")" && pwd)"
[ -x "$DIR/.venv/bin/python" ] || { echo "Ferramenta ainda não instalada. Dois cliques em 'Instalar (Mac).command'."; exit 1; }
cd "$DIR/src" && exec ../.venv/bin/python -u conferencia.py "$@"
