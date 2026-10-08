"""Abas de relatórios: trocar de relatório (/p/<slug>) e criar um novo (/novo)."""
from flask import abort, make_response, redirect, request

import comum
from painel.base import _ir, _msg, coleta_em_andamento_em


def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"

    @app.get("/p/<slug>")
    def trocar(slug):
        if slug not in [s for s, _ in comum.projetos()]:
            abort(404)
        rodando = coleta_em_andamento_em()
        if rodando and rodando != slug:
            nome = dict(comum.projetos()).get(rodando, {}).get("nome", rodando)
            return _ir("/fluxo/progresso", f"Há uma coleta em andamento no relatório \"{nome}\". Só dá para trocar de "
                                           "relatório quando ela terminar (ou for pausada).")
        comum.usar_projeto(slug)
        r = make_response(redirect("/"))
        r.set_cookie("projeto", slug, samesite="Strict", max_age=3600 * 24 * 365)
        return r

    @app.route("/novo", methods=["GET", "POST"])
    def novo():
        if request.method == "POST":
            token_ok()
            nome = request.form.get("nome", "").strip()
            if not nome:
                return _ir("/novo", "Dê um nome ao relatório.")
            if coleta_em_andamento_em():
                return _ir("/novo", "Há uma coleta em andamento. Crie o novo relatório quando ela terminar.")
            slug = comum.criar_projeto(nome)
            comum.usar_projeto(slug)
            r = make_response(_ir("/cadastro", f"Relatório criado: {nome}. Cadastre os clientes e os processos."))
            r.set_cookie("projeto", slug, samesite="Strict", max_age=3600 * 24 * 365)
            return r
        return (cabecalho("novo") + "<h1>Novo relatório</h1>" + _msg() +
                f"<form class='caixa' method='post'>{oculto}<p class='dica'>Cada relatório é independente: clientes, processos, "
                "andamentos e planilha próprios (ex.: um por grupo econômico ou por cliente).</p>"
                "<label>Nome <input type='text' name='nome' placeholder='Ex.: Grupo Exemplo' required></label> "
                "<button class='principal'>Criar</button></form>")
