#!/bin/bash
# Dois cliques para instalar no Mac. Ao terminar, o painel abre no navegador.
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR" && /bin/bash ./instalar.sh && exec "$DIR/Abrir painel.command"
echo; read -r -p "A instalação não terminou. Veja a mensagem acima e aperte Enter para fechar." _
