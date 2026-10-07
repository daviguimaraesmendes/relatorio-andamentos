"""Arquivos dos eventos: documento original e print da tela (/documento, /print)."""
from flask import abort, request, send_file

import comum
from comum import eventos
from painel.base import _dentro


def registrar(app, TOKEN, cabecalho, token_ok):
    @app.get("/documento")
    def documento():
        ev = next((e for e in eventos() if e["id"] == request.args.get("id")), None)
        if not ev or not ev.get("arquivo") or not _dentro(comum.DOCS_DIR, ev["arquivo"]):
            abort(404)
        return send_file(ev["arquivo"])


    @app.get("/print")
    def ver_print():
        ev = next((e for e in eventos() if e["id"] == request.args.get("id")), None)
        if not ev or not ev.get("print") or not _dentro(comum.PRINTS_DIR, ev["print"]):
            abort(404)
        return send_file(ev["print"])
