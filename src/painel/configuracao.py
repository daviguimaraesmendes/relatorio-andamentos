"""Configuração do relatório ativo: nome, planilha de referência e data do último
relatório (/config)."""
import html
from pathlib import Path

from flask import request

import comum
from painel.base import _ir, _msg, ajuda


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
                return _ir("/config", f"Planilha não encontrada: {caminho}\nConfira se o arquivo ainda está nesse lugar e se o "
                                      "caminho foi copiado inteiro, ou deixe o campo em branco.")
            proj["planilha_modelo"] = str(Path(caminho).expanduser()) if caminho else ""
            proj["ultimo_relatorio"] = request.form.get("ultimo_relatorio", "")
            comum.salvar_projeto(proj)
            return _ir("/config", "Configuração salva.")
        return (cabecalho("config") + "<h1>Configuração do relatório</h1>" + _msg() +
                "<div class='caixa'><b>O que fazer agora</b>"
                + ajuda("Estas informações são só deste relatório (cada relatório tem as suas). Nada aqui é enviado a ninguém: "
                        "ficam num arquivo na pasta do relatório, neste computador.") +
                "<p>Confira o nome, indique a planilha do último relatório que você enviou ao cliente e a data dele. Depois clique em "
                "<b>Salvar</b>. Se ainda não tem a planilha, deixe em branco: dá para enviar uma na tela <a href='/planilha'>Planilha</a>.</p></div>"
                f"<form class='caixa' method='post'>{oculto}"
                "<p><label>Nome do relatório"
                + ajuda("É o nome que aparece na aba no alto da tela e nos arquivos gerados. Mudar o nome não apaga nem move nada. "
                        "Em branco, mantém o nome atual.") +
                f"<br><input type='text' name='nome' size='50' value='{html.escape(proj.get('nome', ''))}' placeholder='Ex.: Grupo Exemplo'></label></p>"
                "<p><label>Planilha de referência (caminho completo do .xlsx do último relatório)"
                + ajuda("A planilha do mês passado, que serve de base: a planilha nova é uma cópia dela com os andamentos aprovados "
                        "acrescentados. O programa só lê esse arquivo; ele não é alterado. Se o caminho não existir, nada é salvo.") +
                f"<br><input type='text' name='planilha_modelo' size='90' value='{html.escape(proj.get('planilha_modelo', ''))}' "
                "placeholder='Ex.: /Users/voce/Documents/Relatorio Exemplo - agosto.xlsx'></label><br>"
                "<span class='dica'>Dica: no Mac, clique no arquivo com a tecla Option e escolha \"Copiar como nome de caminho\". "
                "No Windows, segure Shift, clique com o botão direito e escolha \"Copiar como caminho\".</span></p>"
                "<p><label>Data do último relatório enviado"
                + ajuda("Na primeira atualização, o programa só traz o que veio depois desta data. Depois que você gera a planilha do mês, "
                        "ela é atualizada sozinha. Se errar, corrija aqui e salve.") +
                f"<br><input type='date' name='ultimo_relatorio' "
                f"value='{html.escape(proj.get('ultimo_relatorio', ''))}'></label></p>"
                "<button class='principal'>Salvar</button>"
                + ajuda("Grava as três informações acima. Pode ser refeito quantas vezes quiser; só uma planilha que não existe é recusada.")
                + "</form>"
                f"<p class='dica'>Pasta deste relatório: {html.escape(str(comum.PROJETO_DIR))}"
                + ajuda("Aqui ficam as fichas, os andamentos, os prints e os documentos deste relatório. Faça cópia de segurança desta pasta, "
                        "mas nunca a envie a outra pessoa: ela tem dados dos seus clientes.") + "</p>")
