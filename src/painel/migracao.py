"""Migrar de modelo: converter um relatório que está num formato diferente para os modelos do
programa (rotas sob /migracao).

Passo a passo na tela:
  1. /migracao            a pessoa envia UM arquivo (planilha, tabela, Word, lista);
  2. /migracao/mapear     TELA DE MAPEAMENTO: para cada coluna do arquivo, o campo da ficha que ela vai
                          alimentar (sugestão automática, com a confiança; dá para trocar ou marcar
                          "não usar") e a coluna/bloco correspondente nos modelos novos; abaixo, a lista
                          do que NÃO tem destino. "Ver como ficou" reaplica o mapeamento e mostra uma
                          prévia dos primeiros processos; "Converter" cria o relatório e gera os arquivos;
  3. /entregas            os arquivos convertidos (texto A e/ou planilha B) e o relatório de qualidade.

Diferença para "Importar": importar adota o relatório como está, para acompanhar; migrar converte o
formato. Os dois usam o mesmo leitor (`leitores.ler`, que devolve em `RelatorioLido["mapeamento"]`
a proposta de mapeamento coluna -> campo, com confiança) e as mesmas rotinas de fichas e conferência
de painel/assistente.py. Aqui só mudam a tela de mapeamento e o escritor.

Formatos aceitos pelo mapeamento (ver `normalizar_mapeamento`): {coluna: campo}, {coluna: {"campo",
"confianca"}} ou lista de {"coluna", "campo", "confianca"}. Os nomes "numero" e "andamentos" são os
destinos especiais (número do processo e texto do histórico). Ao reler com o mapeamento corrigido
chama `leitores.ler(caminho, formato, mapeamento={coluna: campo})`. A conversão cria um relatório
novo (para ter pasta saida/ própria) e entrega pelos escritores via `painel.entregas.gerar`; as colunas
sem destino seguem em `parametros["campos_nao_migrados"]` do estado, para a aba "Campos não migrados".

O quadro "O que falta para a transição" (painel/lacunas_tela.py, calculado por lacunas.py) aparece na tela de mapeamento e na
prévia: por grupo de campos, quantos processos têm cada campo, de onde ele vem e o que fazer. Ao converter, o mesmo relatório de
lacunas segue em `parametros["faltas_da_migracao"]` e vira a aba "Faltas da migração" da planilha.

Sem o leitor ou os escritores (outros workstreams), a tela explica em português o que falta.
"""
import html
from pathlib import Path

from flask import abort, request

import ficha
from painel import assistente as ass
from painel import entregas as ent
from painel import lacunas_tela
from painel import perfil as per
from painel.base import _ir, _msg, ajuda
from painel.entregas import ESTILO_FLUXO, Indisponivel, modulo

EXTENSOES_MIGRACAO = (".xlsx", ".csv", ".docx", ".txt", ".md")
MODELOS_DE_DESTINO = {"docx_a": "Relatório em texto simplificado (modelo A, .docx)", "xlsx_b": "Planilha (modelo B, .xlsx)",
                      "dashboard": "Painel com gráficos (modelo C, .html; usa a planilha)"}
DESTINOS_ESPECIAIS = {"numero": "Número do processo", "andamentos": "Andamentos (histórico)"}
# onde cada campo aparece no relatório em texto (modelo A); o que não está aqui só existe na planilha
DESTINO_NO_TEXTO = {"numero": "Nº do processo", "andamentos": "Andamentos", "autores": "Autor(es)", "reus": "Réu(s)",
                    "assunto": "Assunto", "data_ajuizamento": "Ajuizamento", "valor_causa": "Valor da causa",
                    "data_citacao": "Data de citação", "vara": "Juízo", "area": "Área do direito",
                    "materia_principal": "Matéria principal", "momento_atual": "Momento atual do processo",
                    "ultimo_andamento": "Último andamento"}
_e = html.escape


def _com_comentario(item, origem):
    """Leva junto o `comentario` do leitor (por que o destino foi escolhido), quando houver."""
    if origem.get("comentario"):
        item["comentario"] = origem["comentario"]
    return item


def normalizar_mapeamento(bruto):
    """Qualquer formato de mapeamento -> [{"coluna", "campo", "confianca"}] na ordem recebida."""
    itens = []
    if isinstance(bruto, dict):
        for coluna, v in bruto.items():
            if isinstance(v, dict):
                itens.append(_com_comentario({"coluna": str(coluna), "campo": v.get("campo") or "", "confianca": v.get("confianca")}, v))
            else:
                itens.append({"coluna": str(coluna), "campo": v or "", "confianca": None})
    elif isinstance(bruto, (list, tuple)):
        for v in bruto:
            if isinstance(v, dict) and v.get("coluna") is not None:
                itens.append(_com_comentario({"coluna": str(v["coluna"]), "campo": v.get("campo") or "", "confianca": v.get("confianca")}, v))
    return itens


def opcoes_de_campo():
    return [("", "(não usar)"), *DESTINOS_ESPECIAIS.items(), *[(c, d[0]) for c, d in ficha.CAMPOS.items()]]


def destino_no_modelo(campo):
    """(coluna na planilha, bloco no texto) para um campo; vazio quando não aparece."""
    if not campo:
        return "não vai para os modelos (fica em Campos não migrados)", ""
    planilha = DESTINOS_ESPECIAIS.get(campo) or (ficha.CAMPOS[campo][0] if campo in ficha.CAMPOS else campo)
    return planilha, DESTINO_NO_TEXTO.get(campo, "só na planilha")


def colunas_da_leitura(rel):
    """Linhas da tela de mapeamento: colunas com proposta + colunas sem destino, com amostras."""
    amostras = {str(c.get("coluna")): c.get("amostra") or [] for c in rel.get("colunas_sem_destino", [])}
    linhas = normalizar_mapeamento(rel.get("mapeamento"))
    vistas = {l["coluna"] for l in linhas}
    for l in linhas:
        l["amostra"] = amostras.get(l["coluna"], [])
    for coluna, amostra in amostras.items():
        if coluna not in vistas:
            linhas.append({"coluna": coluna, "campo": "", "confianca": None, "amostra": amostra})
    return linhas


def _ler_com_mapeamento(dados, mapeamento=None):
    """Relê o arquivo guardado (com o mapeamento corrigido, se for tabela fora do modelo)."""
    leitores = modulo("leitores", "O leitor de relatórios")
    caminho = Path(dados["arquivo"]["caminho"])
    formato = dados["arquivo"]["formato"]
    if mapeamento is not None and formato == "tabela_livre":
        return leitores.ler(caminho, formato, mapeamento=mapeamento)
    return leitores.ler(caminho, formato)


def _selecao_do_formulario(form, linhas):
    """Escolhas da tela; coluna sem seletor (arquivo de formato conhecido) fica de fora e vale a proposta do leitor."""
    return {l["coluna"]: (form.get(f"map_{i}") or "") for i, l in enumerate(linhas) if f"map_{i}" in form}


def _sem_destino(dados, selecionado):
    """Colunas sem destino no mapeamento atual (uma vez cada, mesmo que a coluna apareça em duas abas)."""
    vistas, saida = set(), []
    for l in dados["colunas"]:
        if l["coluna"] in vistas or (selecionado.get(l["coluna"], l["campo"]) or ""):
            continue
        vistas.add(l["coluna"])
        saida.append({"coluna": l["coluna"], "amostra": l.get("amostra", [])})
    return saida


def quadro_de_lacunas(dados, selecionado, fichas=None):
    """HTML do quadro "O que falta para a transição" para o mapeamento atual. Sem `fichas`, relê o arquivo com o mapeamento
    escolhido. Nunca levanta exceção: a tela de mapeamento não pode cair por causa de um quadro informativo."""
    try:
        if fichas is None:
            escolhas = {c: (campo or None) for c, campo in selecionado.items()}      # "(não usar)" = None: a coluna fica de fora
            rel = _ler_com_mapeamento(dados, escolhas if (escolhas and dados["arquivo"]["formato"] == "tabela_livre") else None)
            fichas, _ = ass.fichas_do_relatorio(rel)
        mapa = [{"coluna": l["coluna"], "campo": selecionado.get(l["coluna"], l["campo"]) or ""} for l in dados["colunas"]]
        sem = _sem_destino(dados, selecionado)
        return lacunas_tela.quadro(fichas, mapeamento=mapa, colunas_sem_destino=sem, incluir_sem_destino=False)
    except Exception:  # noqa: BLE001
        return ""


def html_do_mapeamento(dados, selecionado, previa, oculto, lote, nome, quadro_html=""):
    h = []
    arq = dados["arquivo"]
    editavel = arq["formato"] == "tabela_livre"
    h.append(f"<div class='caixa'><b>{_e(arq['nome'])}</b> · {_e(ass.ROTULO_FORMATO.get(arq['formato'], arq['formato']))} · "
             f"{arq['processos']} processo(s)"
             + ("" if editavel else "<p class='dica'>Este arquivo já está num formato conhecido: as colunas são reconhecidas "
                                    "automaticamente. Confira abaixo e escolha o modelo de destino.</p>") + "</div>")
    h.append("<div class='caixa'><b>O que fazer agora</b><ol><li>Confira, coluna por coluna, para qual campo do programa ela vai "
             "(a sugestão automática costuma acertar, mas confira).</li><li>Escolha os modelos de destino e dê um nome ao novo "
             "relatório.</li><li>Clique em <b>Ver como ficou</b> para uma prévia e, estando bem, em <b>Converter</b>.</li></ol>"
             "<p class='dica'>O arquivo original não é alterado em nenhum momento.</p></div>")
    h.append(f"<form class='caixa' method='post' action='/migracao/converter'>{oculto}<input type='hidden' name='lote' value='{_e(lote)}'>")
    h.append("<h2>Mapeamento das colunas"
             + ajuda("Aqui você diz o que cada coluna do seu arquivo significa para o programa (por exemplo, \"Nº Processo\" é o número do "
                     "processo). É a parte que mais pede a sua conferência: um campo errado vira informação errada no relatório novo.")
             + "</h2><table class='t'><tr><th>Coluna do arquivo</th><th>Exemplos"
             + ajuda("Os primeiros valores de verdade que o programa leu nessa coluna, para você reconhecer o que ela contém.")
             + "</th><th>Vai para o campo"
             + ajuda("O campo do programa que essa coluna vai alimentar. \"(não usar)\" deixa a coluna de fora do relatório novo, mas ela "
                     "não se perde: vai para a aba \"Campos não migrados\" da planilha.")
             + "</th><th>Confiança"
             + ajuda("O quanto o programa tem certeza da sugestão automática. Quanto menor o número, mais vale conferir.")
             + "</th><th>Na planilha (B)</th><th>No texto (A)</th></tr>")
    opcoes = opcoes_de_campo()
    validos = {v for v, _ in opcoes}
    for i, l in enumerate(dados["colunas"]):
        atual = selecionado.get(l["coluna"], l["campo"]) or ""
        extra = [] if atual in validos else [(atual, atual)]       # nunca perder um destino que o leitor propôs
        planilha, texto = destino_no_modelo(atual)
        conf = f"{round(l['confianca'] * 100)}%" if isinstance(l.get("confianca"), (int, float)) else "-"
        if editavel:
            seletor = (f"<select name='map_{i}' aria-label='Campo para {_e(l['coluna'])}'>"
                       + "".join(f"<option value='{_e(v)}' {'selected' if v == atual else ''}>{_e(r)}</option>" for v, r in [*opcoes, *extra])
                       + "</select>")
        else:
            seletor = _e(dict(opcoes).get(atual, atual) or "(sem destino)")
        comentario = (f"<br><span class='dica'>{_e(l['comentario'])}</span>" if l.get("comentario") and atual == l["campo"] else "")
        h.append(f"<tr><td>{_e(l['coluna'])}</td><td class='dica'>{_e(' | '.join(map(str, l.get('amostra', [])[:3])))}</td>"
                 f"<td>{seletor}{comentario}</td><td>{conf}</td><td>{_e(planilha)}</td><td>{_e(texto)}</td></tr>")
    h.append("</table>")
    sem = _sem_destino(dados, selecionado)
    h.append(f"<h2>Sem destino ({len(sem)})"
             + ajuda("Colunas do seu arquivo que não foram ligadas a nenhum campo. Nada se perde: elas seguem para a aba \"Campos não "
                     "migrados\" da planilha nova.") + "</h2><p><b>Colunas do seu arquivo que ainda não têm destino.</b></p>")
    if sem:
        h.append("<p class='dica'>Nada se perde: estas colunas vão para a aba \"Campos não migrados\" da planilha.</p><ul>"
                 + "".join(f"<li>{_e(l['coluna'])}</li>" for l in sem) + "</ul>")
    else:
        h.append("<p class='dica'>Todas as colunas têm destino.</p>")
    if previa:
        h.append(f"<h2>Prévia: {previa['total']} processo(s)" + ajuda("Os primeiros processos como ficariam com o mapeamento "
                 "atual. Serve só para conferir: nada foi criado ainda.") + f"</h2><table class='t'><tr><th>Processo</th><th>Cliente</th><th>Momento atual</th><th>Valor da causa</th></tr>"
                 + "".join(f"<tr><td>{_e(f['numero'])}</td><td>{_e(str(ficha.obter(f, 'cliente') or ''))}</td>"
                           f"<td>{_e(str(ficha.obter(f, 'momento_atual') or ''))}</td><td>{_e(ficha.dinheiro_br(ficha.obter(f, 'valor_causa')))}</td></tr>"
                           for f in previa["amostra"]) + "</table>"
                 + (f"<p>{previa['avisos']} aviso(s) na leitura (aparecem na tela de conferência da migração se você importar o arquivo).</p>" if previa["avisos"] else ""))
    h.append(quadro_html)
    h.append("<h2>Para onde converter"
             + ajuda("Os formatos que o programa vai gerar a partir do seu arquivo. Pode marcar mais de um.") + "</h2>")
    dicas_modelo = {"docx_a": "Um arquivo Word com os andamentos em texto corrido por processo.",
                    "xlsx_b": "A planilha padrão do programa, com uma linha por processo.",
                    "dashboard": "Uma página com gráficos, montada a partir da planilha (a planilha é gerada junto)."}
    for k, v in MODELOS_DE_DESTINO.items():
        h.append(f"<label><input type='checkbox' name='modelos' value='{k}' checked> {_e(v)}</label>"
                 + ajuda(dicas_modelo.get(k, v)) + "<br>")
    h.append("<p><label>Estilo do texto <select name='estilo_texto'>"
             + "".join(f"<option value='{k}'>{_e(v)}</option>" for k, v in per.ESTILOS.items()) + "</select></label>"
             + ajuda("Só vale para o relatório em texto (Word): o estilo A é mais completo; o B é compacto.") + "</p>"
             f"<p><label>Nome do novo relatório<br><input type='text' name='nome' size='50' value='{_e(nome)}' required "
             "placeholder='ex.: Grupo Exemplo (convertido)'></label>"
             + ajuda("A conversão cria um relatório novo no painel (uma aba nova), com este nome. O relatório atual e o arquivo "
                     "original ficam como estão.") + "</p>"
             "<p class='dica'>O arquivo original não é alterado. O resultado entra num relatório novo, com relatório de qualidade da base "
             "para você conferir antes de adotar o formato.</p>"
             "<button name='acao' value='prever'>Ver como ficou</button>"
             + ajuda("Aplica o mapeamento escolhido e mostra uma prévia dos primeiros processos nesta mesma tela. Não cria nada e não "
                     "gera arquivo; pode repetir quantas vezes quiser até acertar.")
             + " <button class='principal' name='acao' value='converter'>Converter</button>"
             + ajuda("Cria o relatório novo com os processos lidos e gera os arquivos dos modelos marcados (você os vê em Entregas). "
                     "Nada sai do computador e o arquivo original não é alterado. Para desfazer, basta não usar o relatório novo.")
             + " <a href='/migracao'>Cancelar</a>"
             + ajuda("Abandona esta conversão e volta para a escolha do arquivo. Nada é criado.") + "</form>")
    return "".join(h)


def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"

    def pagina(titulo, *partes):
        return "".join([cabecalho("fluxo"), ESTILO_FLUXO, f"<h1>{titulo}</h1>", _msg(), *partes])

    @app.get("/migracao")
    def migracao_migracao():
        return pagina("Migrar de modelo",
                      f"<form class='caixa' method='post' action='/migracao/enviar' enctype='multipart/form-data'>{oculto}"
                      "<p><b>O que fazer agora</b>: escolha o arquivo do seu relatório antigo e clique em <b>Ler o arquivo</b>. "
                      "Na próxima tela você confere como as colunas viram campos do programa antes de converter.</p>"
                      "<p>Use quando o seu relatório está num formato diferente do programa (outra planilha, outro texto) e você quer "
                      "convertê-lo. Para só acompanhar um relatório que já está no formato do programa, use "
                      "<a href='/fluxo/importar'>Importar relatórios existentes</a>.</p>"
                      "<div class='zona'><input type='file' name='arquivo' accept='.xlsx,.csv,.docx,.txt,.md' required aria-label='Arquivo a converter'></div>"
                      + ajuda("O relatório que você quer converter: planilha (.xlsx ou .csv), Word (.docx) ou texto (.txt, .md). Só um "
                              "arquivo por vez. Ele é copiado para uma pasta de trabalho deste computador; nada é enviado pela internet.")
                      + "<p class='dica'>Em seguida você confere como as colunas do arquivo vão para os campos do programa.</p>"
                      "<button class='principal'>Ler o arquivo</button>"
                      + ajuda("Lê o arquivo e abre a tela de mapeamento das colunas. Ainda não converte nada nem cria relatório.")
                      + "</form>")

    @app.post("/migracao/enviar")
    def migracao_enviar():
        token_ok()
        lote, pasta = ass.novo_lote()
        aceitos, rejeitados = ass.salvar_envios(request.files.getlist("arquivo")[:1], pasta, EXTENSOES_MIGRACAO)
        if not aceitos and not rejeitados:
            return _ir("/migracao", "Escolha um arquivo.")
        try:
            lidos = ass.ler_arquivos(aceitos, rejeitados)
        except Indisponivel as erro:
            return _ir("/migracao", str(erro))
        if not lidos:
            return _ir("/migracao", "Não consegui usar o arquivo.\n" + "\n".join(f"{r['nome']}: {r['motivo']}" for r in rejeitados))
        lido = lidos[0]
        resumo = ass.resumo_da_leitura(lido)
        ass.gravar_lote(pasta, "lote.json", {"tipo": "migrar", "arquivo": resumo,
                                             "colunas": colunas_da_leitura(lido["rel"])})
        return _ir(f"/migracao/mapear?lote={lote}")

    def _carregar(lote):
        pasta = ass.pasta_do_lote(lote)
        dados = ass.ler_lote(pasta, "lote.json")
        if dados is None or dados.get("tipo") != "migrar":
            abort(404)
        return pasta, dados

    def _nome_sugerido(dados):
        base = dados["arquivo"].get("cliente") or Path(dados["arquivo"]["nome"]).stem
        return f"{base} (convertido)"

    @app.get("/migracao/mapear")
    def migracao_mapear():
        pasta, dados = _carregar(request.args.get("lote", ""))
        return pagina("Mapeamento das colunas", html_do_mapeamento(dados, {}, None, oculto, pasta.name, _nome_sugerido(dados),
                                                                   quadro_de_lacunas(dados, {})))

    # ---------------------------------------------------- mapeamento das colunas dentro de Importar e Atualizar

    def _lote_de_fluxo(lote):
        pasta = ass.pasta_do_lote(lote)
        dados = ass.ler_lote(pasta, "lote.json")
        if dados is None or dados.get("tipo") not in ("importar", "atualizar"):
            abort(404)
        return pasta, dados

    def _arquivo_livre(dados):
        return next((a for a in dados["arquivos"] if a.get("formato") == "tabela_livre"), None)

    def _volta(dados, pasta):
        return f"/fluxo/{'importar' if dados['tipo'] == 'importar' else 'atualizar'}/conferir?lote={pasta.name}"

    @app.get("/fluxo/mapear")
    def fluxo_mapear():
        pasta, dados = _lote_de_fluxo(request.args.get("lote", ""))
        arq = _arquivo_livre(dados)
        if arq is None:
            return _ir(_volta(dados, pasta), "Nenhum arquivo deste envio é planilha fora do modelo: não há colunas para mapear.")
        leitores = modulo("leitores", "O leitor de relatórios")
        escolhido = (dados.get("mapeamentos") or {}).get(arq["nome"]) or None
        rel = leitores.ler(Path(arq["caminho"]), "tabela_livre", mapeamento=escolhido)
        vistas, linhas = set(), []
        for l in colunas_da_leitura(rel):         # a mesma coluna em duas abas aparece uma vez só (vale para as duas)
            if l["coluna"] not in vistas:
                vistas.add(l["coluna"])
                linhas.append(l)
        selecionado = {l["coluna"]: l["campo"] for l in linhas}      # a proposta inteira vem marcada; a pessoa corrige
        opcoes = opcoes_de_campo()
        h = [f"<form class='caixa' method='post' action='/fluxo/mapear'>{oculto}<input type='hidden' name='lote' value='{_e(pasta.name)}'>",
             "<p><b>O que fazer agora</b>: para cada coluna, escolha o campo do programa que ela alimenta; é obrigatório indicar qual "
             "coluna traz o <b>número do processo</b>. Depois clique em <b>Aplicar e voltar à conferência</b>."
             + ajuda("O mapeamento diz ao programa o que cada coluna da sua planilha significa. Um campo errado vira informação errada "
                     "nas fichas, por isso confira. Nada é gravado ainda: só depois que você confirmar na conferência.") + "</p>",
             f"<p><b>{_e(arq['nome'])}</b>: {rel.get('processos') and len(rel['processos']) or 0} processo(s) com este mapeamento. "
             "Escolha, para cada coluna, o campo do programa que ela alimenta. O que ficar em \"(não usar)\" não entra no relatório "
             "novo, mas nada se perde: vai para a aba \"Campos não migrados\" quando você converter.</p>",
             "<table class='t'><tr><th>Coluna do arquivo</th><th>Exemplos</th><th>Vai para o campo"
             + ajuda("O campo do programa que a coluna vai alimentar. \"(não usar)\" deixa a coluna de fora; ela não se perde e "
                     "pode ir para a aba \"Campos não migrados\" quando você converter.")
             + "</th><th>Confiança"
             + ajuda("O quanto o programa tem certeza da sugestão automática. Quanto menor o número, mais vale conferir.")
             + "</th></tr>"]
        for i, l in enumerate(linhas):
            atual = selecionado.get(l["coluna"]) or ""
            extra = [] if atual in {v for v, _ in opcoes} else [(atual, atual)]
            conf = f"{round(l['confianca'] * 100)}%" if isinstance(l.get("confianca"), (int, float)) and l["confianca"] else "-"
            h.append(f"<tr><td>{_e(l['coluna'])}<input type='hidden' name='col_{i}' value='{_e(l['coluna'])}'></td>"
                     f"<td class='dica'>{_e(' | '.join(map(str, l.get('amostra', [])[:3])))}</td><td><select name='map_{i}'>"
                     + "".join(f"<option value='{_e(v)}' {'selected' if v == atual else ''}>{_e(r)}</option>" for v, r in [*opcoes, *extra])
                     + f"</select></td><td>{conf}</td></tr>")
        h.append("</table><button class='principal'>Aplicar e voltar à conferência</button>"
                 + ajuda("Guarda este mapeamento, relê o arquivo com ele e volta à tela de conferência. Ainda não grava nada nas fichas.")
                 + f" <a href='{_e(_volta(dados, pasta))}'>Cancelar</a>"
                 + ajuda("Volta à conferência sem mudar o mapeamento.") + "</form>")
        return pagina("Mapeamento das colunas", "".join(h))

    @app.post("/fluxo/mapear")
    def fluxo_mapear_aplicar():
        token_ok()
        pasta, dados = _lote_de_fluxo(request.form.get("lote", ""))
        arq = _arquivo_livre(dados)
        if arq is None:
            abort(404)
        mapeamento, i = {}, 0
        while f"col_{i}" in request.form:
            mapeamento[request.form[f"col_{i}"]] = request.form.get(f"map_{i}") or None
            i += 1
        if "numero" not in mapeamento.values():
            return _ir(f"/fluxo/mapear?lote={pasta.name}", "Escolha qual coluna traz o número do processo (campo \"Número do processo\").")
        leitores = modulo("leitores", "O leitor de relatórios")
        lidos = []
        for a in dados["arquivos"]:
            caminho = Path(a["caminho"])
            try:
                rel = leitores.ler(caminho, a["formato"], mapeamento=mapeamento) if a is arq else leitores.ler(caminho, a["formato"])
            except Exception as erro:  # noqa: BLE001
                return _ir(f"/fluxo/mapear?lote={pasta.name}", f"Não consegui aplicar o mapeamento ({erro}).")
            lidos.append({"nome": a["nome"], "caminho": a["caminho"], "formato": a["formato"], "rel": rel})
        if dados["tipo"] == "atualizar":
            fichas, avisos, novo = ass.montar_lote_de_atualizacao(lidos, dados.get("rejeitados", []))
        else:
            fichas, avisos, resumos = ass.tratar_leituras(lidos)
            novo = {"tipo": "importar", "arquivos": resumos, "rejeitados": dados.get("rejeitados", [])}
        novo["mapeamentos"] = {**(dados.get("mapeamentos") or {}), arq["nome"]: {c: v for c, v in mapeamento.items()}}
        ass.gravar_lote(pasta, "lote.json", novo)
        ass.gravar_lote(pasta, "fichas.json", fichas)
        ass.gravar_lote(pasta, "avisos.json", avisos)
        usados = sum(1 for v in mapeamento.values() if v)
        return _ir(_volta(novo, pasta), f"Mapeamento aplicado: {usados} coluna(s) em uso, {len(fichas)} processo(s).")

    @app.get("/fluxo/migrar")
    def fluxo_migrar():
        """Do envio de Importar/Atualizar para 'Migrar de modelo': converte o mesmo arquivo para texto, planilha e painel."""
        pasta, dados = _lote_de_fluxo(request.args.get("lote", ""))
        arq = _arquivo_livre(dados) or (dados["arquivos"][0] if dados["arquivos"] else None)
        if arq is None:
            return _ir(_volta(dados, pasta), "Não há arquivo para converter neste envio.")
        leitores = modulo("leitores", "O leitor de relatórios")
        escolhido = (dados.get("mapeamentos") or {}).get(arq["nome"]) or None
        rel = leitores.ler(Path(arq["caminho"]), arq["formato"], mapeamento=escolhido) if arq["formato"] == "tabela_livre" and escolhido \
            else leitores.ler(Path(arq["caminho"]), arq["formato"])
        novo_lote, nova_pasta = ass.novo_lote()
        resumo = ass.resumo_da_leitura({"nome": arq["nome"], "caminho": arq["caminho"], "formato": arq["formato"], "rel": rel})
        ass.gravar_lote(nova_pasta, "lote.json", {"tipo": "migrar", "arquivo": resumo, "colunas": colunas_da_leitura(rel)})
        return _ir(f"/migracao/mapear?lote={novo_lote}")

    @app.post("/migracao/converter")
    def migracao_converter():
        token_ok()
        pasta, dados = _carregar(request.form.get("lote", ""))
        selecionado = _selecao_do_formulario(request.form, dados["colunas"])
        try:
            rel = _ler_com_mapeamento(dados, {c: (campo or None) for c, campo in selecionado.items()}
                                      if dados["arquivo"]["formato"] == "tabela_livre" else None)
        except Indisponivel as erro:
            return _ir(f"/migracao/mapear?lote={pasta.name}", str(erro))
        except Exception as erro:  # noqa: BLE001
            return _ir(f"/migracao/mapear?lote={pasta.name}", f"Não consegui aplicar o mapeamento ({erro}).")
        lido = {"nome": dados["arquivo"]["nome"], "caminho": dados["arquivo"]["caminho"], "formato": dados["arquivo"]["formato"], "rel": rel}
        fichas, avisos, resumos = ass.tratar_leituras([lido])
        nome = request.form.get("nome", "").strip() or _nome_sugerido(dados)
        if request.form.get("acao") != "converter":
            previa = {"total": len(fichas), "amostra": fichas[:5], "avisos": len(avisos)}
            return pagina("Mapeamento das colunas", html_do_mapeamento(dados, selecionado, previa, oculto, pasta.name, nome,
                                                                       quadro_de_lacunas(dados, selecionado, fichas)))
        modelos = [m for m in request.form.getlist("modelos") if m in MODELOS_DE_DESTINO]
        if not modelos:
            return _ir(f"/migracao/mapear?lote={pasta.name}", "Escolha pelo menos um modelo de destino (texto, planilha ou painel).")
        if "dashboard" in modelos and "xlsx_b" not in modelos:
            modelos.append("xlsx_b")         # o painel lê a planilha: ela é gerada junto
        if not fichas:
            return _ir(f"/migracao/mapear?lote={pasta.name}", "Não encontrei nenhum processo com este mapeamento. Confira a coluna do número do processo.")
        slug = ass.criar_relatorio(nome, fichas, [resumos[0]], resumos)
        perfil = per.carregar()
        perfil["entregas"] = modelos
        estilo = request.form.get("estilo_texto")
        if estilo in per.ESTILOS:
            perfil["estilo_texto"] = estilo
        per.salvar(perfil)
        sem_destino = _sem_destino(dados, selecionado)
        extras = {"campos_nao_migrados": sem_destino}
        try:      # o que falta para a transição vai para a aba "Faltas da migração" da planilha (nunca impede a conversão)
            import lacunas
            mapa = [{"coluna": l["coluna"], "campo": selecionado.get(l["coluna"], l["campo"]) or ""} for l in dados["colunas"]]
            extras["faltas_da_migracao"] = lacunas.lacunas(fichas, mapeamento=mapa, colunas_sem_destino=sem_destino)
        except Exception:  # noqa: BLE001
            pass
        saida = ent.gerar(modelos, "migracao", parametros_extra=extras)
        msg = f"Relatório convertido: {nome}. {len(fichas)} processo(s).\n" + ent.resumo_do_resultado(saida)
        return ass._com_cookie(_ir("/entregas", msg), slug)
