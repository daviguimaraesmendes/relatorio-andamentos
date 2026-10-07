"""Configuração do relatório ativo: nome, planilha de referência e data do último
relatório (/config)."""
import html
from pathlib import Path

from flask import request

import comum
from painel.base import _ir, _msg


def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"

    @app.route("/config", methods=["GET", "POST"])
    def configuracao():
        proj = comum.projeto()
        if request.method == "POST":
            token_ok()
            proj["nome"] = request.form.get("nome", "").strip() or proj.get("nome", comum.PROJETO)
            caminho = request.form.get("planilha_modelo", "").strip()
            if caminho and not Path(caminho).expanduser().exists():
                return _ir("/config", f"Planilha não encontrada: {caminho}")
            proj["planilha_modelo"] = str(Path(caminho).expanduser()) if caminho else ""
            proj["ultimo_relatorio"] = request.form.get("ultimo_relatorio", "")
            comum.salvar_projeto(proj)
            return _ir("/config", "Configuração salva.")
        return (cabecalho("config") + "<h1>Configuração do relatório</h1>" + _msg() +
                f"<form class='caixa' method='post'>{oculto}"
                f"<p><label>Nome do relatório<br><input type='text' name='nome' size='50' value='{html.escape(proj.get('nome', ''))}'></label></p>"
                f"<p><label>Planilha de referência (caminho completo do .xlsx do último relatório)<br>"
                f"<input type='text' name='planilha_modelo' size='90' value='{html.escape(proj.get('planilha_modelo', ''))}'></label><br>"
                "<span class='dica'>Dica: no Finder, clique no arquivo com a tecla Option e escolha \"Copiar como nome de caminho\".</span></p>"
                f"<p><label>Data do último relatório enviado<br><input type='date' name='ultimo_relatorio' "
                f"value='{html.escape(proj.get('ultimo_relatorio', ''))}'></label></p>"
                "<button class='principal'>Salvar</button></form>"
                f"<p class='dica'>Pasta deste relatório: {html.escape(str(comum.PROJETO_DIR))}</p>")
