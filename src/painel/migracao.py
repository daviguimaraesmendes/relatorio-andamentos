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

Sem o leitor ou os escritores (outros workstreams), a tela explica em português o que falta.
"""
import html
from pathlib import Path

from flask import abort, request

import ficha
from painel import assistente as ass
from painel import entregas as ent
from painel import perfil as per
from painel.base import _ir, _msg
from painel.entregas import ESTILO_FLUXO, Indisponivel, modulo

EXTENSOES_MIGRACAO = (".xlsx", ".csv", ".docx", ".txt", ".md")
MODELOS_DE_DESTINO = {"docx_a": "Relatório em texto (modelo A, .docx)", "xlsx_b": "Planilha (modelo B, .xlsx)"}
DESTINOS_ESPECIAIS = {"numero": "Número do processo", "andamentos": "Andamentos (histórico)"}
# onde cada campo aparece no relatório em texto (modelo A); o que não está aqui só existe na planilha
DESTINO_NO_TEXTO = {"numero": "Nº do processo", "andamentos": "Andamentos", "autores": "Autor(es)", "reus": "Réu(s)",
                    "assunto": "Assunto", "data_ajuizamento": "Ajuizamento", "valor_causa": "Valor da causa",
                    "data_citacao": "Data de citação", "vara": "Juízo", "area": "Área do direito",
                    "materia_principal": "Matéria principal", "momento_atual": "Momento atual do processo",
                    "ultimo_andamento": "Último andamento"}
_e = html.escape


def normalizar_mapeamento(bruto):
    """Qualquer formato de mapeamento -> [{"coluna", "campo", "confianca"}] na ordem recebida."""
    itens = []
    if isinstance(bruto, dict):
        for coluna, v in bruto.items():
            if isinstance(v, dict):
                itens.append({"coluna": str(coluna), "campo": v.get("campo") or "", "confianca": v.get("confianca")})
            else:
                itens.append({"coluna": str(coluna), "campo": v or "", "confianca": None})
    elif isinstance(bruto, (list, tuple)):
        for v in bruto:
            if isinstance(v, dict) and v.get("coluna") is not None:
                itens.append({"coluna": str(v["coluna"]), "campo": v.get("campo") or "", "confianca": v.get("confianca")})
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


def html_do_mapeamento(dados, selecionado, previa, oculto, lote, nome):
    h = []
    arq = dados["arquivo"]
    editavel = arq["formato"] == "tabela_livre"
    h.append(f"<div class='caixa'><b>{_e(arq['nome'])}</b> · {_e(ass.ROTULO_FORMATO.get(arq['formato'], arq['formato']))} · "
             f"{arq['processos']} processo(s)"
             + ("" if editavel else "<p class='dica'>Este arquivo já está num formato conhecido: as colunas são reconhecidas "
                                    "automaticamente. Confira abaixo e escolha o modelo de destino.</p>") + "</div>")
    h.append(f"<form class='caixa' method='post' action='/migracao/converter'>{oculto}<input type='hidden' name='lote' value='{_e(lote)}'>")
    h.append("<h2>Mapeamento das colunas</h2><table class='t'><tr><th>Coluna do arquivo</th><th>Exemplos</th><th>Vai para o campo</th>"
             "<th>Confiança</th><th>Na planilha (B)</th><th>No texto (A)</th></tr>")
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
        h.append(f"<tr><td>{_e(l['coluna'])}</td><td class='dica'>{_e(' | '.join(map(str, l.get('amostra', [])[:3])))}</td>"
                 f"<td>{seletor}</td><td>{conf}</td><td>{_e(planilha)}</td><td>{_e(texto)}</td></tr>")
    h.append("</table>")
    sem = [l for l in dados["colunas"] if not (selecionado.get(l["coluna"], l["campo"]) or "")]
    h.append(f"<h2>Sem destino ({len(sem)})</h2>")
    if sem:
        h.append("<p class='dica'>Nada se perde: estas colunas vão para a aba \"Campos não migrados\" da planilha.</p><ul>"
                 + "".join(f"<li>{_e(l['coluna'])}</li>" for l in sem) + "</ul>")
    else:
        h.append("<p class='dica'>Todas as colunas têm destino.</p>")
    if previa:
        h.append(f"<h2>Prévia: {previa['total']} processo(s)</h2><table class='t'><tr><th>Processo</th><th>Cliente</th><th>Momento atual</th><th>Valor da causa</th></tr>"
                 + "".join(f"<tr><td>{_e(f['numero'])}</td><td>{_e(str(ficha.obter(f, 'cliente') or ''))}</td>"
                           f"<td>{_e(str(ficha.obter(f, 'momento_atual') or ''))}</td><td>{_e(ficha.dinheiro_br(ficha.obter(f, 'valor_causa')))}</td></tr>"
                           for f in previa["amostra"]) + "</table>"
                 + (f"<p>{previa['avisos']} aviso(s) na leitura (aparecem na tela de conferência da migração se você importar o arquivo).</p>" if previa["avisos"] else ""))
    h.append("<h2>Para onde converter</h2>")
    for k, v in MODELOS_DE_DESTINO.items():
        h.append(f"<label><input type='checkbox' name='modelos' value='{k}' checked> {_e(v)}</label><br>")
    h.append("<p><label>Estilo do texto <select name='estilo_texto'>"
             + "".join(f"<option value='{k}'>{_e(v)}</option>" for k, v in per.ESTILOS.items()) + "</select></label></p>"
             f"<p><label>Nome do novo relatório<br><input type='text' name='nome' size='50' value='{_e(nome)}' required></label></p>"
             "<p class='dica'>O arquivo original não é alterado. O resultado entra num relatório novo, com relatório de qualidade da base "
             "para você conferir antes de adotar o formato.</p>"
             "<button name='acao' value='prever'>Ver como ficou</button> "
             "<button class='principal' name='acao' value='converter'>Converter</button> <a href='/migracao'>Cancelar</a></form>")
    return "".join(h)


def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"

    def pagina(titulo, *partes):
        return "".join([cabecalho("fluxo"), ESTILO_FLUXO, f"<h1>{titulo}</h1>", _msg(), *partes])

    @app.get("/migracao")
    def migracao_migracao():
        return pagina("Migrar de modelo",
                      f"<form class='caixa' method='post' action='/migracao/enviar' enctype='multipart/form-data'>{oculto}"
                      "<p>Use quando o seu relatório está num formato diferente do programa (outra planilha, outro texto) e você quer "
                      "convertê-lo. Para só acompanhar um relatório que já está no formato do programa, use "
                      "<a href='/fluxo/importar'>Importar relatórios existentes</a>.</p>"
                      "<div class='zona'><input type='file' name='arquivo' accept='.xlsx,.csv,.docx,.txt,.md' required aria-label='Arquivo a converter'></div>"
                      "<p class='dica'>Em seguida você confere como as colunas do arquivo vão para os campos do programa.</p>"
                      "<button class='principal'>Ler o arquivo</button></form>")

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
        return pagina("Mapeamento das colunas", html_do_mapeamento(dados, {}, None, oculto, pasta.name, _nome_sugerido(dados)))

    @app.post("/migracao/converter")
    def migracao_converter():
        token_ok()
        pasta, dados = _carregar(request.form.get("lote", ""))
        selecionado = _selecao_do_formulario(request.form, dados["colunas"])
        try:
            rel = _ler_com_mapeamento(dados, {c: campo for c, campo in selecionado.items() if campo} if dados["arquivo"]["formato"] == "tabela_livre" else None)
        except Indisponivel as erro:
            return _ir(f"/migracao/mapear?lote={pasta.name}", str(erro))
        except Exception as erro:  # noqa: BLE001
            return _ir(f"/migracao/mapear?lote={pasta.name}", f"Não consegui aplicar o mapeamento ({erro}).")
        lido = {"nome": dados["arquivo"]["nome"], "caminho": dados["arquivo"]["caminho"], "formato": dados["arquivo"]["formato"], "rel": rel}
        fichas, avisos, resumos = ass.tratar_leituras([lido])
        nome = request.form.get("nome", "").strip() or _nome_sugerido(dados)
        if request.form.get("acao") != "converter":
            previa = {"total": len(fichas), "amostra": fichas[:5], "avisos": len(avisos)}
            return pagina("Mapeamento das colunas", html_do_mapeamento(dados, selecionado, previa, oculto, pasta.name, nome))
        modelos = [m for m in request.form.getlist("modelos") if m in MODELOS_DE_DESTINO]
        if not modelos:
            return _ir(f"/migracao/mapear?lote={pasta.name}", "Escolha pelo menos um modelo de destino (texto ou planilha).")
        if not fichas:
            return _ir(f"/migracao/mapear?lote={pasta.name}", "Não encontrei nenhum processo com este mapeamento. Confira a coluna do número do processo.")
        slug = ass.criar_relatorio(nome, fichas, [resumos[0]], resumos)
        perfil = per.carregar()
        perfil["entregas"] = modelos
        estilo = request.form.get("estilo_texto")
        if estilo in per.ESTILOS:
            perfil["estilo_texto"] = estilo
        per.salvar(perfil)
        sem_destino = [{"coluna": l["coluna"], "amostra": l.get("amostra", [])} for l in dados["colunas"] if not selecionado.get(l["coluna"], l["campo"])]
        saida = ent.gerar(modelos, "migracao", parametros_extra={"campos_nao_migrados": sem_destino})
        msg = f"Relatório convertido: {nome}. {len(fichas)} processo(s).\n" + ent.resumo_do_resultado(saida)
        return ass._com_cookie(_ir("/entregas", msg), slug)
