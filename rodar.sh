#!/bin/bash
# Atualização pelo terminal (o mesmo que o botão Atualizar do painel).
# Uso: ./rodar.sh --projeto <pasta em projetos/> [--desde DD/MM/AAAA] [--processo N1,N2]
DIR="$(cd "$(dirname "$0")" && pwd)"
[ -x "$DIR/.venv/bin/python" ] || { echo "Ferramenta ainda não instalada. Dois cliques em 'Instalar (Mac).command'."; exit 1; }
cd "$DIR/src" && exec ../.venv/bin/python -u rodar.py "$@"
