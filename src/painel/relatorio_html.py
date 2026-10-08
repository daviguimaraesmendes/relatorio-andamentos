"""Download ou abertura dos relatórios gerados, planilha ou HTML (/relatorio)."""
from flask import request, send_file

import comum
from painel.base import _dentro


def registrar(app, TOKEN, cabecalho, token_ok):
    @app.get("/relatorio")
    def ver_relatorio():
        caminho = comum.RELATORIOS_DIR / request.args.get("p", "")
        if not _dentro(comum.RELATORIOS_DIR, caminho) or not caminho.is_file():
            return (cabecalho("planilha") + "<h1>Relatório não encontrado</h1>"
                    "<p class='vazio'>Esse arquivo não está mais na pasta de relatórios (foi apagado ou movido). "
                    "Nada foi alterado. Gere a planilha de novo, se precisar.</p>"
                    "<p><a href='/planilha'>Voltar para Planilha</a></p>"), 404
        return send_file(caminho, as_attachment=caminho.suffix == ".xlsx")
