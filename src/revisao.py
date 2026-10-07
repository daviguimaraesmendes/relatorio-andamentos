"""Painel local do Relatório de Andamentos: uma aba por relatório (projeto
autônomo, com clientes, processos, andamentos e planilha próprios) e, dentro
de cada uma: Atualizar, Revisar, Planilha, Clientes e processos, Configuração.

Roda só em 127.0.0.1, sem modo debug, um pedido por vez (o relatório ativo é
estado global). Cada formulário leva um token gerado na inicialização, para
que outra página aberta no navegador não consiga agir por conta própria.

Este arquivo só monta o painel: cria o app, gera o token e chama o registrar() de
cada tela (pacote painel/, mais cadastro.py) e sobe o servidor."""
import secrets
import sys

from flask import Flask

import cadastro
from comum import config
from painel import (acesso_tela, atualizar, base, configuracao, documentos, pedidos, planilha_mes, projetos,
                    relatorio_html, revisao_eventos)

app = Flask(__name__)
TOKEN = secrets.token_urlsafe(24)
token_ok = base.criar_token_ok(TOKEN)
cabecalho = base.cabecalho

for tela in (base, projetos, revisao_eventos, atualizar, planilha_mes, relatorio_html, configuracao,
             documentos, acesso_tela, cadastro, pedidos):
    tela.registrar(app, TOKEN, cabecalho, token_ok)


if __name__ == "__main__":
    porta = config().get("porta_revisao", 5072)
    print(f"Painel em http://127.0.0.1:{porta}  (feche esta janela para encerrar)")
    if "--abrir" in sys.argv:
        import threading
        import webbrowser
        threading.Timer(1.5, lambda: webbrowser.open(f"http://127.0.0.1:{porta}/")).start()
    app.run(host="127.0.0.1", port=porta, debug=False, threaded=False)
