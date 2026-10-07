"""Download ou abertura dos relatórios gerados, planilha ou HTML (/relatorio)."""
from flask import abort, request, send_file

import comum
from painel.base import _dentro


def registrar(app, TOKEN, cabecalho, token_ok):
    @app.get("/relatorio")
    def ver_relatorio():
        caminho = comum.RELATORIOS_DIR / request.args.get("p", "")
        if not _dentro(comum.RELATORIOS_DIR, caminho) or not caminho.is_file():
            abort(404)
        return send_file(caminho, as_attachment=caminho.suffix == ".xlsx")
