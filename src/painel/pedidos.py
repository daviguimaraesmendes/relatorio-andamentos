"""Tela "Pedidos das iniciais" (/pedidos): kit para uma IA de maior capacidade ler as petições iniciais.

O programa lista os processos com e sem pedidos extraídos, monta o pacote (PDFs + prompt) para baixar,
recebe a resposta da IA num campo "colar resultado", CONFERE (formato, matérias, soma x valor da causa,
processo desconhecido ou duplicado) e mostra os achados ANTES de gravar. Só grava depois que a pessoa marca
que conferiu; a ficha de cada processo só é preenchida se ela pedir, e nunca por cima de valor existente
sem pedido explícito. A lógica está em pedidos.py; aqui só há tela.

Rotas: GET /pedidos; POST /pedidos/validar, /pedidos/gravar, /pedidos/pacote, /pedidos/planilha,
/pedidos/enviar (ponto de extensão do provedor externo: "indisponível" até haver provedor cadastrado e
consentido); GET /pedidos/prompt (baixa o prompt pronto).

Aviso de confidencialidade: anexar PDFs numa IA na internet envia o conteúdo para fora do computador.
"""
import html
import shutil
import tempfile
from pathlib import Path

from flask import Response, request, send_file

import ficha as fch
import pedidos
from painel.base import _ir, _msg, ajuda

ESTILO = """<style>
.pedidos table{border-collapse:collapse;width:100%;margin:8px 0}
.pedidos td,.pedidos th{border-bottom:1px solid var(--linha);padding:6px 4px;text-align:left;font-size:14px;vertical-align:top}
.pedidos td.num{white-space:nowrap}.pedidos td.valor{text-align:right;white-space:nowrap}
.pedidos .aviso-conf{background:var(--alerta-fundo);color:var(--alerta);border:1px solid var(--alerta);border-radius:6px;padding:10px;margin:12px 0}
.pedidos .erro{background:#fdecec;color:#7f1d1d;padding:6px 8px;border-radius:4px;margin:6px 0;font-size:14px}
.pedidos .info{color:var(--suave);font-size:13px;margin:4px 0}
.pedidos details{border:1px solid var(--linha);border-radius:6px;padding:8px 12px;margin:10px 0}
.pedidos summary{cursor:pointer;font-weight:600}
.pedidos .selo{display:inline-block;background:var(--alerta-fundo);color:var(--alerta);border-radius:4px;padding:2px 8px;font-size:13px}
.pedidos textarea.colar{min-height:200px;font-family:ui-monospace,Menlo,Consolas,monospace;font-size:13px}
</style>"""


def _e(x):
    return html.escape("" if x is None else str(x))


def _dinheiro(valor):
    return _e(fch.dinheiro_br(valor)) if valor not in (None, "") else "—"


def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"

    # ------------------------------------------------------------ peças da página

    def lista_de_processos():
        linhas = pedidos.situacao()
        if not linhas:
            return ("<div class='vazio'>Nenhum processo na carteira deste relatório. Cadastre em "
                    "<a href='/cadastro'>Clientes e processos</a>.</div>")
        corpo = []
        for s in linhas:
            if s["ja_extraido"]:
                estado = f"Pedidos extraídos em {_e(fch.data_br(s['extraido_em']))} ({s['n_pedidos']} pedido(s))"
            elif s["pdf_inicial"]:
                estado = "Inicial localizada; sem pedidos extraídos"
            else:
                estado = "Inicial não localizada"
            marcado = "checked" if s["pdf_inicial"] and not s["ja_extraido"] else ""
            desabilitado = "" if s["pdf_inicial"] else "disabled"
            corpo.append(f"<tr><td><input type='checkbox' name='numero' value='{_e(s['numero'])}' {marcado} {desabilitado}></td>"
                         f"<td class='num'>{_e(s['numero'])}</td><td>{_e(s['cliente'])}</td><td>{estado}</td></tr>")
        com = sum(1 for s in linhas if s["ja_extraido"])
        sem_inicial = sum(1 for s in linhas if not s["pdf_inicial"])
        return (f"<p class='meta'>{len(linhas)} processo(s): {com} com pedidos extraídos, "
                f"{len(linhas) - com} sem; {sem_inicial} sem inicial localizada.</p>"
                "<table><tr><th></th><th>Processo</th><th>Cliente</th><th>Situação</th></tr>" + "".join(corpo) + "</table>")

    def formulario_do_pacote():
        pasta = pedidos._locais()["data"] / "iniciais"
        disponivel, motivo = pedidos.provedor_disponivel()
        botao_provedor = (f"<button formaction='/pedidos/enviar' class='principal'>Enviar pelo provedor</button>"
                          if disponivel else
                          f"<button type='button' disabled title='{_e(motivo)}'>Enviar pelo provedor (indisponível)</button>")
        return (f"<form method='post' action='/pedidos/pacote'>{oculto}" + lista_de_processos() +
                "<p><label>Dividir em lotes de <input type='number' name='por_lote' value='5' min='0' max='50' style='width:60px'> "
                "PDFs (0 = um lote só)</label>"
                + ajuda("Quantas petições iniciais vão em cada lote do pacote. IAs na internet costumam aceitar poucos anexos por vez; "
                        "5 é um bom começo. Com 0, todas vão num lote só.") + "</p>"
                "<button class='principal'>Baixar pacote (.zip com PDFs e prompt)</button>"
                + ajuda("Cria no seu computador um arquivo .zip com as petições iniciais dos processos marcados (PDF) e o prompt, "
                        "o texto de instruções para a IA. O programa não envia nada: você leva o pacote a uma IA de sua escolha. "
                        "Atenção: anexar os PDFs numa IA na internet faz o conteúdo sair do seu computador.")
                + f" {botao_provedor}"
                + ajuda("Mandaria as petições direto a um provedor de IA externo cadastrado e autorizado, sem você baixar o pacote. "
                        "Está indisponível enquanto nenhum provedor estiver ligado a esta função; hoje, use o pacote e cole o "
                        "resultado na etapa 2.")
                + " <button formaction='/pedidos/planilha'>Baixar planilha dos pedidos já gravados</button>"
                + ajuda("Gera uma planilha (.xlsx) com todos os pedidos que você já conferiu e gravou neste relatório. "
                        "Só lê o que está gravado; não grava nada e não envia nada.")
                + f"<p class='dica'>{_e(pedidos.MENSAGEM_INDISPONIVEL) if not disponivel else ''}</p>"
                f"<p class='dica'>Inicial não localizada? Coloque o PDF na pasta <code>{_e(pasta)}</code> com o número do "
                "processo no nome do arquivo.</p></form>")

    def resumo_do_resultado(res):
        dados = res["dados"] or {"processos": []}
        cartoes = [("processos aceitos", len(dados["processos"])), ("recusados", len(res["recusados"])),
                   ("erros", len(res["erros"])), ("avisos", len([a for a in res["avisos"] if a["nivel"] == "atencao"]))]
        dicas = {"processos aceitos": "Processos que passaram na conferência e podem ser gravados.",
                 "recusados": "Processos que a conferência recusou por erro; não serão gravados.",
                 "erros": "Problemas que impedem a gravação do processo afetado. Veja a lista logo abaixo.",
                 "avisos": "Pontos de atenção que não impedem a gravação, mas pedem conferência sua."}
        return ("<div class='cartoes'>" + "".join(f"<div class='cartao'><b>{n}</b>{_e(r)}{ajuda(dicas[r])}</div>"
                                                   for r, n in cartoes) + "</div>")

    def lista_de_avisos(res):
        partes = []
        for a in res["erros"]:
            partes.append(f"<div class='erro'><b>Erro</b> ({_e(a['codigo'])}) · {_e(a['onde'])}: {_e(a['mensagem'])}</div>")
        for a in (x for x in res["avisos"] if x["nivel"] == "atencao"):
            partes.append(f"<div class='alerta'><b>Atenção</b> ({_e(a['codigo'])}) · {_e(a['onde'])}: {_e(a['mensagem'])}</div>")
        infos = [x for x in res["avisos"] if x["nivel"] == "info"]
        if infos:
            partes.append("<details><summary>Observações ({})</summary>".format(len(infos)) +
                          "".join(f"<div class='info'>{_e(a['onde'])}: {_e(a['mensagem'])}</div>" for a in infos) + "</details>")
        return "".join(partes)

    def cartao_do_processo(p):
        c, r = p["cadastro"], p["resumo"]
        cad = [("Reclamante", c.get("reclamante")), ("Função", c.get("funcao")), ("Categoria", c.get("categoria_funcao")),
               ("Empresa principal", c.get("empresa_principal")), ("Outras empresas", "; ".join(c.get("outras_empresas", []))),
               ("Terceiros", "; ".join(c.get("terceiros", []))), ("Vara", c.get("vara")),
               ("Município/UF", " / ".join(x for x in (c.get("municipio"), c.get("uf")) if x)),
               ("Ajuizamento", fch.data_br(c.get("data_ajuizamento"))), ("Valor da causa", fch.dinheiro_br(c.get("valor_causa"))),
               ("Critério do valor", c.get("criterio_valor_causa"))]
        linhas_cad = "".join(f"<tr><td>{_e(k)}</td><td>{_e(v) or '—'}</td></tr>" for k, v in cad)
        peds = "".join(
            f"<tr><td>{_e(x['materia'])}" + (f"<br><span class='dica'>lido como: {_e(x['materia_original'])}</span>"
                                             if x.get("materia_original") else "") + f"</td><td>{_e(x['pedido_como_formulado'])}</td>"
            f"<td class='valor'>{_dinheiro(x['valor_atribuido'])}</td><td>{_e(x['situacao_valor'])}</td>"
            f"<td>{_e(x['pagina_pdf'] or '—')}</td><td>{'Sim' if x['entra_nos_totais'] else 'Não'}</td></tr>"
            for x in p["pedidos"])
        achados = "".join(f"<li><b>{_e(a['tipo'])}</b>" + (f" ({_e(a['impacto'])})" if a.get("impacto") else "") +
                          f": {_e(a['descricao'])}</li>" for a in p["achados"])
        return (f"<details open><summary>{_e(p['numero'])} · {r['n_pedidos']} pedido(s) · soma {_dinheiro(r['soma_pedidos'])} "
                f"· valor da causa {_dinheiro(r['valor_causa'])}</summary>"
                f"<table>{linhas_cad}</table>"
                "<table><tr><th>Matéria</th><th>Pedido (como formulado)</th><th>Valor atribuído</th><th>Situação do valor</th>"
                f"<th>Pág.</th><th>Entra nos totais?</th></tr>{peds}</table>"
                f"<h3 style='font-size:15px'>Achados da IA (confira antes de gravar)</h3>"
                + (f"<ul>{achados}</ul>" if achados else "<p class='dica'>A IA não registrou achados para este processo.</p>")
                + "</details>")

    def previa_das_fichas(dados):
        linhas = [l for l in pedidos.conferir_cadastro(None, dados) if l["acao"] != "igual"]
        if not linhas:
            return "<p class='dica'>Cadastro da inicial coincide com o que já está nas fichas (ou não há o que preencher).</p>"
        rotulo = {"preencher": "será preenchido", "divergente": "diferente: só muda se marcar \"substituir\""}
        def legivel(campo, valor):
            tipo = fch.CAMPOS[campo][2]
            return (fch.dinheiro_br(valor) if tipo == "dinheiro" else fch.data_br(valor) if tipo == "data" else valor)
        corpo = "".join(f"<tr><td class='num'>{_e(l['numero'])}</td><td>{_e(l['rotulo'])}</td>"
                        f"<td>{_e(legivel(l['campo'], l['atual'])) or '—'}</td>"
                        f"<td>{_e(legivel(l['campo'], l['novo']))}</td><td>{rotulo[l['acao']]}</td></tr>" for l in linhas)
        return ("<table><tr><th>Processo</th><th>Campo da ficha</th><th>Hoje</th><th>Na inicial</th><th>O que acontece</th></tr>"
                + corpo + "</table>")

    def conferencia(texto, res):
        dados = res["dados"]
        blocos = [resumo_do_resultado(res), lista_de_avisos(res)]
        if dados and dados["processos"]:
            blocos += [cartao_do_processo(p) for p in dados["processos"]]
            blocos.append("<h2>Fichas dos processos</h2>" + previa_das_fichas(dados))
            blocos.append(
                f"<form class='caixa' method='post' action='/pedidos/gravar'>{oculto}"
                f"<textarea name='texto' style='display:none'>{_e(texto)}</textarea>"
                "<p><label><input type='checkbox' name='confirmo' value='1'> <b>Li os achados e avisos acima e confirmo a gravação.</b>"
                "</label>"
                + ajuda("Sem esta marca, o botão Gravar não grava nada. É a sua confirmação de que conferiu o que a IA devolveu.") + "</p>"
                "<p><label><input type='checkbox' name='atualizar_fichas' value='1'> Preencher também a ficha de cada processo "
                "com o cadastro da inicial (só campos vazios; fica marcado como confirmado por você).</label>"
                + ajuda("Além de guardar os pedidos, copia dados do cadastro da inicial (partes, vara, valor da causa etc.) para a ficha "
                        "do processo, mas só nos campos que estão vazios. A tabela \"Fichas dos processos\" acima mostra o que mudaria.")
                + "</p>"
                "<p><label><input type='checkbox' name='sobrescrever' value='1'> Substituir também os valores diferentes que "
                "já estão na ficha (use com cuidado).</label>"
                + ajuda("Só tem efeito junto com a opção anterior. Troca valores que já estão na ficha pelos da petição. O valor antigo "
                        "é perdido e não há botão para desfazer; deixe desmarcado se tiver dúvida.") + "</p>"
                + (f"<p class='dica'>{len(res['recusados'])} processo(s) com erro ficam de fora e não serão gravados.</p>"
                   if res["recusados"] else "")
                + f"<button class='principal'>Gravar {len(dados['processos'])} processo(s)</button>"
                + ajuda("Guarda os pedidos conferidos no arquivo de pedidos deste relatório, no seu computador. Se o processo já tinha "
                        "pedidos gravados, eles são substituídos pelos novos. Nada sai do computador.")
                + "</form>")
        else:
            blocos.append("<div class='erro'>Nada a gravar: corrija os erros acima (por exemplo, peça à IA para refazer) "
                          "e cole de novo.</div>")
        return "".join(blocos)

    def pagina(texto="", res=None, aviso_local=""):
        ok_prompt = pedidos.prompt_validado()
        selo = ("" if ok_prompt else
                " <span class='selo'>NÃO VALIDADO com petições reais (validação no piloto)</span>"
                 + ajuda("O prompt (as instruções dadas à IA) ainda não foi testado com petições reais do escritório. Por isso, "
                         "confira com cuidado tudo o que a IA devolver antes de gravar."))
        corpo = (cabecalho("pedidos") + f"<div class='pedidos'>{ESTILO}<h1>Pedidos das petições iniciais</h1>" + _msg() +
                 "<div class='aviso-conf'><b>Confidencialidade.</b> Ao anexar as petições numa IA na internet, o conteúdo "
                 "(nomes, números de processo, valores) sai do seu computador. Use somente uma IA autorizada pelo escritório e "
                 "pelo cliente. Este programa não envia nada sozinho.</div>"
                 f"<p class='meta'>Prompt versão {_e(pedidos.prompt_versao())}.{selo} "
                 "<a href='/pedidos/prompt'>Baixar o prompt</a>"
                 + ajuda("Baixa o arquivo de texto com as instruções que a IA deve seguir para ler as petições (já vai também dentro "
                         "do pacote). Serve se você preferir montar o envio à mão. Não envia nada.")
                 + " · o passo a passo está em <code>docs/pedidos-iniciais.md</code>.</p>"
                 "<div class='caixa'><b>O que fazer agora</b><ol>"
                 "<li>Marque os processos e <b>baixe o pacote</b> (petições iniciais em PDF mais o prompt).</li>"
                 "<li>Leve o pacote a uma IA que o escritório e o cliente autorizem e <b>cole aqui a resposta</b> dela.</li>"
                 "<li><b>Confira</b> o que o programa achou e só então grave. Nada é gravado antes da sua confirmação.</li></ol>"
                 "<p class='dica'>Os \"pedidos\" são as matérias pedidas em cada petição inicial, com os valores atribuídos, que "
                 "alimentam a ficha e a planilha dos processos.</p></div>"
                 "<h2>1. Escolha os processos e baixe o pacote"
                 + ajuda("Escolha quais petições iniciais irão no pacote. Vêm marcados os processos com inicial localizada e ainda "
                         "sem pedidos extraídos. As petições vêm da pasta de iniciais do relatório.") + "</h2>"
                 + formulario_do_pacote() +
                 "<h2>2. Cole o resultado da IA"
                 + ajuda("Depois que a IA ler as petições, ela devolve um texto em formato JSON. Cole aqui a resposta inteira; o programa "
                         "só confere o formato, as matérias e as somas, sem gravar nada ainda.") + "</h2>")
        if aviso_local:
            corpo += f"<div class='erro'>{_e(aviso_local)}</div>"
        corpo += (f"<form class='caixa' method='post' action='/pedidos/validar'>{oculto}"
                  "<p><label>Cole aqui a resposta inteira da IA (só o JSON)<br>"
                  f"<textarea class='colar' name='texto' placeholder='{{ \"processos\": [ ... ] }}'>{_e(texto)}</textarea></label></p>"
                  "<button class='principal'>Conferir</button>"
                  + ajuda("Analisa o texto colado e mostra, na etapa 3, o que foi entendido e os problemas encontrados (formato, matéria "
                          "desconhecida, soma diferente do valor da causa, processo desconhecido ou repetido). Não grava nada.")
                  + "</form>")
        if res is not None:
            corpo += ("<h2>3. Confira antes de gravar"
                      + ajuda("Leia os erros, os avisos e os achados da IA de cada processo. Só depois marque a confirmação e grave. "
                              "Processos com erro ficam de fora da gravação.") + "</h2>" + conferencia(texto, res))
        return corpo + "</div>"

    # ------------------------------------------------------------ rotas

    @app.get("/pedidos")
    def pedidos_inicio():
        return pagina()

    @app.get("/pedidos/prompt")
    def pedidos_prompt():
        return Response(pedidos.prompt_pronto(), mimetype="text/markdown",
                        headers={"Content-Disposition": "attachment; filename=prompt-pedidos.md"})

    @app.post("/pedidos/validar")
    def pedidos_validar():
        token_ok()
        texto = request.form.get("texto", "")
        return pagina(texto, pedidos.validar(texto))

    @app.post("/pedidos/gravar")
    def pedidos_gravar():
        token_ok()
        texto = request.form.get("texto", "")
        res = pedidos.validar(texto)
        if not request.form.get("confirmo"):
            return pagina(texto, res, "Marque que conferiu os achados e avisos antes de gravar.")
        if not res["dados"] or not res["dados"]["processos"]:
            return pagina(texto, res, "Não há nenhum processo sem erro para gravar.")
        saida = pedidos.gravar(None, res["dados"], atualizar_fichas=bool(request.form.get("atualizar_fichas")),
                               sobrescrever=bool(request.form.get("sobrescrever")))
        msg = f"{len(saida['gravados'])} processo(s) gravado(s) em pedidos.json"
        if saida["substituidos"]:
            msg += f" ({len(saida['substituidos'])} substituído(s))"
        if saida["fichas_atualizadas"]:
            msg += f"; {len(saida['fichas_atualizadas'])} campo(s) de ficha preenchido(s)"
        if saida["divergencias"]:
            msg += f"; {len(saida['divergencias'])} campo(s) diferente(s) na ficha foram mantidos"
        if res["recusados"]:
            msg += f". {len(res['recusados'])} processo(s) com erro ficaram de fora."
        return _ir("/pedidos", msg)

    @app.post("/pedidos/pacote")
    def pedidos_pacote():
        token_ok()
        escolhidos = request.form.getlist("numero") or None
        try:
            por_lote = max(0, min(50, int(request.form.get("por_lote") or 0)))
        except ValueError:
            por_lote = 0
        if not pedidos.pacote(None, incluir_extraidos=True):
            return _ir("/pedidos", "Nenhuma inicial localizada para montar o pacote.")
        arquivo = pedidos.pacote_zip(None, escolhidos, por_lote, incluir_extraidos=escolhidos is not None)
        return send_file(arquivo, mimetype="application/zip", as_attachment=True, download_name="pacote-pedidos.zip")

    @app.post("/pedidos/planilha")
    def pedidos_planilha():
        token_ok()
        if not pedidos.carregar()["processos"]:
            return _ir("/pedidos", "Ainda não há pedidos gravados para exportar.")
        tmp = Path(tempfile.mkdtemp(prefix="pedidos-"))
        try:
            destino = pedidos.exportar_xlsx(None, tmp / "pedidos.xlsx")
            conteudo = destino.read_bytes()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return Response(conteudo, mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        headers={"Content-Disposition": "attachment; filename=pedidos.xlsx"})

    @app.post("/pedidos/enviar")
    def pedidos_enviar():
        token_ok()
        numeros = request.form.getlist("numero") or [c["numero"] for c in pedidos.pacote(None)]
        try:
            texto = pedidos.enviar_pelo_provedor(None, numeros)
        except ValueError as e:
            return _ir("/pedidos", str(e))
        return pagina(texto, pedidos.validar(texto))
