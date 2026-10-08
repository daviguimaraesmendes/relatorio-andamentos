"""Arquivos dos eventos: documento original e print da tela (/documento, /print)."""
from flask import request, send_file

import comum
from comum import eventos
from painel.base import _dentro


def registrar(app, TOKEN, cabecalho, token_ok):
    def nao_encontrado(o_que):
        """Página em português no lugar do "Not Found" seco: diz o que pode ter acontecido e para onde ir."""
        return (cabecalho("revisar") + f"<h1>{o_que} não encontrado</h1>"
                f"<p class='vazio'>{o_que} deste andamento não está mais na pasta do relatório (ou nunca foi baixado). "
                "Isso acontece quando o arquivo foi apagado ou movido, ou quando o documento não pôde ser baixado na coleta. "
                "Nada foi alterado.</p><p><a href='/'>Voltar para Revisar</a></p>"), 404

    @app.get("/documento")
    def documento():
        ev = next((e for e in eventos() if e["id"] == request.args.get("id")), None)
        if not ev or not ev.get("arquivo") or not _dentro(comum.DOCS_DIR, ev["arquivo"]):
            return nao_encontrado("Documento")
        return send_file(ev["arquivo"])


    @app.get("/print")
    def ver_print():
        ev = next((e for e in eventos() if e["id"] == request.args.get("id")), None)
        if not ev or not ev.get("print") or not _dentro(comum.PRINTS_DIR, ev["print"]):
            return nao_encontrado("Print")
        return send_file(ev["print"])
