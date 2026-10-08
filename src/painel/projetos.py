"""Abas de relatórios: trocar de relatório (/p/<slug>) e criar um novo (/novo)."""
from flask import abort, make_response, redirect, request

import comum
from painel.base import _ir, _msg, ajuda, coleta_em_andamento_em


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
                return _ir("/novo", "Dê um nome ao relatório. Pode ser o nome do cliente ou do grupo.")
            if coleta_em_andamento_em():
                return _ir("/novo", "Há uma coleta em andamento. Crie o novo relatório quando ela terminar, ou pause a coleta "
                                    "em Assistente > Andamento da coleta.")
            slug = comum.criar_projeto(nome)
            comum.usar_projeto(slug)
            r = make_response(_ir("/cadastro", f"Relatório criado: {nome}. Cadastre os clientes e os processos."))
            r.set_cookie("projeto", slug, samesite="Strict", max_age=3600 * 24 * 365)
            return r
        return (cabecalho("novo") + "<h1>Novo relatório</h1>" + _msg() +
                "<div class='caixa'><b>O que fazer agora</b>"
                + ajuda("Um relatório é uma pasta própria no seu computador, com clientes, processos, andamentos e planilha só dele. "
                        "Criar não envia nada a lugar nenhum e não mexe nos outros relatórios.") +
                "<p>Dê um nome e clique em <b>Criar</b>. Em seguida você cadastra os clientes e os processos. "
                "Já tem relatórios prontos (Word, Excel ou uma lista de números)? Então comece por "
                "<a href='/fluxo/importar'>Importar relatórios existentes</a>"
                + ajuda("Lê os seus arquivos, mostra o que entendeu e só então cria o relatório. É o caminho mais rápido para quem já tem "
                        "relatórios no formato do escritório.") + ".</p></div>"
                f"<form class='caixa' method='post'>{oculto}<p class='dica'>Cada relatório é independente: clientes, processos, "
                "andamentos e planilha próprios (ex.: um por grupo econômico ou por cliente).</p>"
                "<label>Nome"
                + ajuda("Escolha um nome que você reconheça de longe: ele vira a aba no alto da tela. Dá para mudar depois em Configuração.") +
                " <input type='text' name='nome' placeholder='Ex.: Grupo Exemplo' required></label> "
                "<button class='principal'>Criar</button>"
                + ajuda("Cria o relatório vazio e abre a tela de cadastro de clientes e processos. Não há botão para apagar relatórios; "
                        "se criar um por engano, é só não usá-lo.") + "</form>")
