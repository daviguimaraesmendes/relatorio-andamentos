"""Perfil do relatório: leitura e gravação do `perfil.json` (CONTRATOS §7) e a tela /perfil.

O perfil diz o que o relatório entrega (texto A, planilha B, painel C), com que profundidade
coletar, em que modo (contínuo, com janela de horário, ou imediato), quais colunas a planilha
usa e os parâmetros do cliente (nº de funcionários, empresas do grupo). Vive em
`projetos/<slug>/perfil.json`.

Uso nas outras telas e nos fluxos:

    from painel import perfil
    p = perfil.carregar()            # sempre completo: o que faltar no arquivo vem do padrão
    perfil.salvar(p)                 # grava preservando chaves que esta tela não conhece

Regras:
  - arquivo ausente, ilegível ou malformado nunca derruba a tela: vale o padrão;
  - chaves desconhecidas do arquivo (por exemplo, o bloco "ia" do WS-18) são preservadas
    na gravação; esta tela não edita IA nem consentimento (ponto de extensão abaixo);
  - além das chaves do contrato, o perfil guarda duas chaves aditivas, opcionais:
    "janela_coleta" ({"inicio": "20:00", "fim": "06:00"}, usada no modo contínuo) e
    "pasta_de_trabalho" (onde ficam entrada/ e saida/; vazio = a pasta do relatório;
    serve para apontar para uma pasta do Drive para Desktop).

Ponto de extensão para a tela de IA (WS-18): acrescente em `PONTOS_DE_EXTENSAO` uma função
`f(perfil) -> html` e o bloco aparece no fim da tela, dentro do formulário de visualização.
"""
import copy
import html
import re
from pathlib import Path

from flask import request

import comum
from painel.base import _ir, _msg

ENTREGAS = {"docx_a": "Relatório em texto (modelo A, arquivo .docx)",
            "xlsx_b": "Planilha (modelo B, arquivo .xlsx)",
            "dashboard": "Painel com gráficos (modelo C, arquivo .html)"}
PROFUNDIDADES = {"rapido": "Rápido: capa do processo e movimentações (não abre os documentos)",
                 "padrao": "Padrão: o anterior e os documentos principais (inicial, sentenças, acórdãos, decisões)",
                 "completo": "Completo: todos os documentos"}
MODOS = {"continuo": "Contínuo: a coleta roda sozinha nas horas escolhidas (por exemplo, à noite)",
         "imediato": "Imediato: roda agora, com aviso de quanto tempo deve levar"}
MOLDES = {"padrao": "Modelo padrão do programa", "cliente": "Planilha enviada pelo cliente (atualiza o arquivo dele)"}
ESTILOS = {"a": "Estilo A (completo)", "b": "Estilo B (compacto)"}
JANELA_PADRAO = {"inicio": "20:00", "fim": "06:00"}

# As 29 colunas da aba de processos do modelo B (nomes de campo da ficha; "numero", "tribunal",
# "andamentos" e "ativo" não são campos de ficha.CAMPOS, mas são colunas do modelo).
COLUNAS_MODELO_B = ["numero", "autores", "reus", "vara", "municipio", "tribunal", "data_ajuizamento", "area",
                    "materia_principal", "objeto", "valor_causa", "andamentos", "situacao", "ativo",
                    "valor_arbitrado", "probabilidade", "valor_estimado", "valor_execucao", "custas",
                    "depositos_recursais", "garantias", "resultado", "valor_economizado", "data_transito",
                    "taxa_resolucao_dias", "houve_recurso", "percentual_exito", "terceirizado", "outras_partes"]
_ROTULOS_EXTRA = {"numero": "Número do processo", "tribunal": "Tribunal", "andamentos": "Andamentos", "ativo": "Ativo"}

PADRAO = {
    "versao": 1,
    "entregas": ["docx_a", "xlsx_b", "dashboard"],
    "molde_planilha": "padrao",
    "colunas_ativas": COLUNAS_MODELO_B,
    "estilo_texto": "a",
    "profundidade": "padrao",
    "modo_coleta": "continuo",
    "ia": {"provedor": "local", "consentimento_externo": False, "pseudonimizar": True},
    "parametros": {"headcount": None, "empresas_do_grupo": []},
    "janela_coleta": JANELA_PADRAO,
    "pasta_de_trabalho": "",
}

PONTOS_DE_EXTENSAO = []   # funções f(perfil) -> html (WS-18 acrescenta o bloco de IA aqui)


def rotulo_da_coluna(nome):
    import ficha
    if nome in _ROTULOS_EXTRA:
        return _ROTULOS_EXTRA[nome]
    return ficha.CAMPOS[nome][0] if nome in ficha.CAMPOS else nome


# ---------------------------------------------------------------- leitura e gravação

def caminho(slug=None):
    """perfil.json do relatório (o ativo, se `slug` não for dado); None sem relatório."""
    if slug:
        return comum.PROJETOS_DIR / slug / "perfil.json"
    return (comum.PROJETO_DIR / "perfil.json") if comum.PROJETO_DIR else None


def _completar(lido):
    """Mistura o que veio do arquivo com o padrão: o que faltar (ou vier com tipo errado) cai no padrão."""
    perfil = copy.deepcopy(PADRAO)
    if not isinstance(lido, dict):
        return perfil
    for chave, valor in lido.items():
        padrao = perfil.get(chave)
        if isinstance(padrao, dict):
            if isinstance(valor, dict):
                padrao.update(valor)
        elif isinstance(padrao, list):
            if isinstance(valor, list):
                perfil[chave] = valor
        elif chave in perfil:
            if isinstance(valor, type(padrao)) or (padrao is None):
                perfil[chave] = valor
        else:
            perfil[chave] = valor     # chave que esta tela não conhece: preservada
    return perfil


def carregar(slug=None):
    arquivo = caminho(slug)
    lido = None
    if arquivo and arquivo.exists():
        try:
            lido = comum.load_json(arquivo, None)
        except (ValueError, OSError):
            lido = None
    return _completar(lido)


def salvar(perfil, slug=None):
    arquivo = caminho(slug)
    if arquivo is None:
        raise ValueError("Não há relatório ativo para gravar o perfil.")
    comum.save_json(arquivo, perfil)


# ---------------------------------------------------------------- validação do formulário

def _hora(texto):
    texto = (texto or "").strip()
    m = re.fullmatch(r"([01]?\d|2[0-3]):([0-5]\d)", texto)
    return f"{int(m[1]):02d}:{m[2]}" if m else None


def aplicar_formulario(perfil, form, parcial=False):
    """Devolve (perfil novo, [erros em português]). Não grava.

    Com `parcial=True` (formulários dos fluxos, que só mostram parte das escolhas) só mexe nos
    campos que vieram no formulário; sem ele (tela /perfil) o formulário é o perfil inteiro."""
    novo, erros = copy.deepcopy(perfil), []
    # checkbox desmarcado não vem no formulário: o campo oculto `com_entregas` diz que as entregas estavam na tela
    tem = (lambda chave: chave in form or (chave == "entregas" and "com_entregas" in form)) if parcial else (lambda chave: True)
    if tem("entregas"):
        entregas = [e for e in form.getlist("entregas") if e in ENTREGAS]
        if entregas:
            novo["entregas"] = [e for e in ENTREGAS if e in entregas]
        else:
            erros.append("Marque pelo menos uma entrega (texto, planilha ou painel).")
    for chave, opcoes, rotulo in (("molde_planilha", MOLDES, "modelo de planilha"), ("estilo_texto", ESTILOS, "estilo do texto"),
                                  ("profundidade", PROFUNDIDADES, "profundidade"), ("modo_coleta", MODOS, "modo de coleta")):
        if tem(chave):
            valor = form.get(chave)
            if valor in opcoes:
                novo[chave] = valor
            else:
                erros.append(f"Escolha uma opção válida em: {rotulo}.")
    if tem("janela_inicio") or tem("janela_fim"):
        inicio, fim = _hora(form.get("janela_inicio")), _hora(form.get("janela_fim"))
        if inicio and fim:
            novo["janela_coleta"] = {"inicio": inicio, "fim": fim}
        else:
            erros.append("Use horas no formato HH:MM (por exemplo, 20:00) na janela da coleta.")
    if tem("headcount"):
        cabeca = (form.get("headcount") or "").strip()
        if not cabeca:
            novo["parametros"]["headcount"] = None
        elif cabeca.isdigit():
            novo["parametros"]["headcount"] = int(cabeca)
        else:
            erros.append("O número de funcionários deve ser um número inteiro (ou fique em branco).")
    if tem("empresas_do_grupo"):
        empresas = [l.strip() for l in (form.get("empresas_do_grupo") or "").splitlines() if l.strip()]
        novo["parametros"]["empresas_do_grupo"] = list(dict.fromkeys(empresas))
    if tem("colunas_ativas"):
        colunas = [c for c in form.getlist("colunas_ativas") if c in COLUNAS_MODELO_B or c in _campos()]
        if colunas:
            novo["colunas_ativas"] = colunas
        else:
            erros.append("Deixe pelo menos uma coluna ativa na planilha.")
    if tem("pasta_de_trabalho"):
        pasta = (form.get("pasta_de_trabalho") or "").strip()
        if pasta and not Path(pasta).expanduser().is_dir():
            erros.append(f"A pasta de trabalho não existe: {pasta}")
        else:
            novo["pasta_de_trabalho"] = str(Path(pasta).expanduser()) if pasta else ""
    return novo, erros


def _campos():
    import ficha
    return ficha.CAMPOS


# ---------------------------------------------------------------- tela

def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"
    e = html.escape

    @app.get("/perfil")
    def perfil_ver_perfil():
        import ficha
        h = [cabecalho("perfil"), "<h1>Perfil do relatório</h1>", _msg()]
        if not comum.PROJETO:
            return "".join(h) + "<p>Crie ou importe um relatório primeiro.</p>"
        p = carregar()
        marca = lambda cond: "checked" if cond else ""
        sel = lambda atual, valor: "selected" if atual == valor else ""
        h.append(f"<form class='caixa' method='post' action='/perfil/salvar'>{oculto}"
                 "<p class='dica'>Aqui você diz o que este relatório entrega e como a coleta deve rodar. "
                 "Pode mudar quando quiser; vale para as próximas coletas e entregas.</p>")
        h.append("<h2>O que entregar</h2>")
        for chave, rotulo in ENTREGAS.items():
            h.append(f"<p><label><input type='checkbox' name='entregas' value='{chave}' {marca(chave in p['entregas'])}> {e(rotulo)}</label></p>")
        h.append("<p><label>Planilha: partir de<br><select name='molde_planilha'>"
                 + "".join(f"<option value='{k}' {sel(p['molde_planilha'], k)}>{e(v)}</option>" for k, v in MOLDES.items())
                 + "</select></label></p>")
        h.append("<p><label>Texto: estilo<br><select name='estilo_texto'>"
                 + "".join(f"<option value='{k}' {sel(p['estilo_texto'], k)}>{e(v)}</option>" for k, v in ESTILOS.items())
                 + "</select></label></p>")
        h.append("<h2>Coleta</h2><p><label>Profundidade<br><select name='profundidade'>"
                 + "".join(f"<option value='{k}' {sel(p['profundidade'], k)}>{e(v)}</option>" for k, v in PROFUNDIDADES.items())
                 + "</select></label></p>")
        h.append("<p><label>Modo<br><select name='modo_coleta'>"
                 + "".join(f"<option value='{k}' {sel(p['modo_coleta'], k)}>{e(v)}</option>" for k, v in MODOS.items())
                 + "</select></label></p>")
        j = p["janela_coleta"]
        h.append(f"<p>No modo contínuo, coletar entre <input type='text' name='janela_inicio' size='5' value='{e(j['inicio'])}'> "
                 f"e <input type='text' name='janela_fim' size='5' value='{e(j['fim'])}'> (HH:MM; "
                 "se o fim for menor que o início, a janela passa da meia-noite).</p>")
        h.append("<h2>Dados do cliente</h2>")
        par = p["parametros"]
        h.append(f"<p><label>Número de funcionários (para os indicadores por 100 funcionários)<br>"
                 f"<input type='text' name='headcount' size='8' value='{e(str(par.get('headcount') or ''))}'></label></p>"
                 "<p><label>Empresas do grupo (uma por linha; o painel usa para saber o que é \"da empresa\")<br>"
                 f"<textarea name='empresas_do_grupo' rows='4'>{e(chr(10).join(par.get('empresas_do_grupo') or []))}</textarea></label></p>")
        h.append("<h2>Colunas da planilha</h2><p class='dica'>As 29 colunas do modelo B já vêm marcadas; desmarque as que este cliente não usa.</p><div class='colunas'>")
        todas = list(COLUNAS_MODELO_B) + [c for c in ficha.CAMPOS if c not in COLUNAS_MODELO_B]
        for c in todas:
            h.append(f"<label><input type='checkbox' name='colunas_ativas' value='{e(c)}' {marca(c in p['colunas_ativas'])}> "
                     f"{e(rotulo_da_coluna(c))}</label>")
        h.append("</div><h2>Pasta de trabalho</h2>"
                 f"<p class='dica'>Os arquivos que você envia ficam em <b>entrada/</b> e os que o programa entrega em <b>saida/</b>. "
                 f"Por padrão, dentro da pasta do relatório ({e(str(comum.PROJETO_DIR))}). Para sincronizar com o Drive para Desktop, "
                 "indique aqui uma pasta dentro do Drive.</p>"
                 f"<p><input type='text' name='pasta_de_trabalho' size='70' value='{e(p.get('pasta_de_trabalho') or '')}' "
                 "placeholder='deixe em branco para usar a pasta do relatório'></p>")
        ia = p.get("ia") or {}
        externa = ia.get("consentimento_externo") is True   # só o true explícito conta (CONTRATOS §7)
        h.append("<h2>Inteligência artificial</h2><p>Motor atual: <b>"
                 + (f"externo ({e(str(ia.get('provedor')))})" if externa else "local (nada sai do seu computador)")
                 + "</b>. ")
        if any(r.rule == "/ia" for r in app.url_map.iter_rules()):
            h.append("<a href='/ia'>Escolher o motor e o consentimento</a>")
        else:
            h.append("A escolha de motor externo e o consentimento ficarão numa tela própria.")
        h.append("</p>")
        for ponto in PONTOS_DE_EXTENSAO:
            try:
                h.append(ponto(p))
            except Exception:   # um bloco de extensão com defeito não derruba a tela
                pass
        h.append("<p><button class='principal'>Salvar perfil</button></p></form>"
                 "<style>.colunas{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:4px}</style>")
        return "".join(h)

    @app.post("/perfil/salvar")
    def perfil_salvar_perfil():
        token_ok()
        if not comum.PROJETO:
            return _ir("/perfil", "Não há relatório ativo.")
        atual = carregar()
        novo, erros = aplicar_formulario(atual, request.form)
        if erros:
            return _ir("/perfil", "Não salvei o perfil:\n" + "\n".join(erros))
        salvar(novo)
        return _ir("/perfil", "Perfil salvo.")
