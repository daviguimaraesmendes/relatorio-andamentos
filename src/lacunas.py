"""O que falta para a transição: relatório de lacunas de uma migração.

Depois de ler uma planilha "desformatada" (por exemplo, de contingências jurídicas), o programa precisa dizer,
com clareza, o que o arquivo NÃO trouxe e como cada falta se resolve. Para cada campo do modelo B (agrupado como em
`ficha.CAMPOS`), `lacunas` informa quantos processos têm o campo preenchido, de onde ele veio ou virá e, em português,
o que fazer:

    from lacunas import lacunas
    lac = lacunas(relatorio_lido)                      # RelatorioLido (leitores.ler) ou lista de fichas v2
    lac = lacunas(fichas, mapeamento=rel["mapeamento"], colunas_sem_destino=rel["colunas_sem_destino"])
    lac["grupos"][0]["campos"][0]
    # {"campo": "vara", "rotulo": "Vara / Juízo", "grupo": "capa", "tipo": "texto", "preenchidos": 0, "total": 50,
    #  "percentual": 0.0, "origem": "buscável nos tribunais", "completar_por": "buscável nos tribunais",
    #  "colunas": [], "aplica_a": "todos", "opcional": False, "a_confirmar": 0}

Origem (o que dizer da fonte do campo):
    "do arquivo, coluna X"      o arquivo tem uma coluna ligada ao campo (ou, sem o mapeamento, o campo veio preenchido)
    "buscável nos tribunais"    a capa e a coleta (PJe/jus.br, DJEN, DataJud) preenchem: vara, município, UF, ajuizamento,
                                classe, assunto, partes e valor da causa (quando a capa traz)
    "deduzível pelas regras/IA" sai dos andamentos e das decisões: momento atual, fase, situação, resultado,
                                probabilidade, matéria, área, êxito, valor economizado...
    "precisa de você"           só uma pessoa sabe: cliente, responsável, passivo potencial, provisão, depósitos,
                                pagamentos, valores de acordo/execução...
`completar_por` diz como se completa o que FALTA do campo (a mesma lista, menos "do arquivo"); None quando nada falta.

Alguns campos só se aplicam a parte dos processos (`aplica_a`): "encerrados" (data de trânsito, pagamento realizado,
passivo atualizado...), "risco" (provisão: processos ativos com perda provável ou possível) ou "com_deposito" (valor do
depósito, quando há depósito). O `total` do campo já leva isso em conta. Campos `opcional` (apelido, contato,
observações...) aparecem na tabela, mas não geram "o que falta" nem entram no percentual do grupo.

Resultado:
    {"total_processos", "ativos", "encerrados",
     "grupos": [{"grupo", "rotulo", "campos": [...], "preenchidos", "total", "percentual", "o_que_falta": [texto, ...]}],
     "o_que_falta": [texto, ...]            # todos os grupos, na ordem
     "colunas_sem_destino": [{"coluna", "aba", "amostra"}],
     "resumo": {"percentual", "campos_completos", "campos_com_falta", "campos_vazios", "a_confirmar"}}

Só lê; não grava nada nem usa rede nem IA. Tudo em português, determinístico.
"""
import ficha as fch
import taxonomia

BUSCAVEL = "buscável nos tribunais"
DEDUZIVEL = "deduzível pelas regras/IA"
VOCE = "precisa de você"

ROTULO_DO_GRUPO = {"gestao": "Gestão e identificação", "partes": "Partes", "capa": "Capa do processo",
                   "situacao": "Situação atual", "julgamento": "Julgamento e valores",
                   "contingencia": "Contingência (risco, provisão e depósitos)"}

# o que a capa e a coleta preenchem (ver capa.CAMPOS_DA_CAPA)
CAMPOS_BUSCAVEIS = frozenset({"vara", "municipio", "uf", "data_ajuizamento", "data_citacao", "classe", "assunto",
                              "valor_causa", "autores", "reus", "outras_partes"})
# o que as regras e a síntese deduzem dos andamentos e das decisões (taxonomia, julgamento, consolidar)
CAMPOS_DEDUZIVEIS = frozenset({"parte_contraria", "momento_atual", "momento_qualificador", "situacao", "fase", "ultimo_andamento", "houve_recurso",
                               "area", "materia_principal", "objeto", "polo_cliente", "resultado", "probabilidade",
                               "valor_estimado", "valor_economizado", "taxa_resolucao_dias", "data_transito",
                               "percentual_exito", "percentual_provisao", "deposito_judicial", "justificativa_probabilidade"})
CAMPOS_OPCIONAIS = frozenset({"apelido", "contato", "observacoes", "momento_qualificador", "outras_partes", "terceirizado",
                              "data_citacao", "custas", "garantias", "valor_acordo", "valor_execucao", "valor_arbitrado",
                              "percentual_exito", "ativo_potencial", "justificativa_probabilidade", "houve_recurso",
                              "taxa_resolucao_dias", "valor_economizado"})
# campos que só se aplicam a parte dos processos
APLICA_A = {"data_transito": "encerrados", "taxa_resolucao_dias": "encerrados", "valor_economizado": "encerrados",
            "pagamento_realizado": "encerrados", "passivo_atualizado": "encerrados", "percentual_exito": "encerrados",
            "provisao": "risco", "percentual_provisao": "risco", "depositos_recursais": "com_deposito"}
QUALIFICADOR = {"encerrados": "só dos {n} processos encerrados", "risco": "só dos {n} processos ativos com perda provável ou possível",
                "com_deposito": "só dos {n} processos com depósito judicial", "todos": ""}

# texto próprio de alguns campos quando eles aparecem sozinhos na lista do que falta
DICAS = {
    "valor_causa": "a capa do tribunal costuma trazer; se a coleta não achar, informe",
    "cliente": "o arquivo não diz quem é o cliente; marque na conferência quem é cliente ou informe um cliente padrão",
    "responsavel": "informe o advogado responsável (na planilha ou na ficha do processo)",
    "passivo_potencial": "informe o valor em risco de cada processo (é estimativa do escritório; nenhum tribunal informa)",
    "provisao": "informe a provisão constituída (é decisão contábil do cliente; nenhum tribunal informa)",
    "deposito_judicial": "informe se houve depósito judicial (Sim ou Não); o programa marca Sim sozinho quando há valor depositado",
    "depositos_recursais": "o depósito está marcado como Sim, mas falta o valor depositado",
    "pagamento_realizado": "informe quanto foi efetivamente pago em cada processo encerrado",
    "passivo_atualizado": "informe o passivo com correção e juros dos processos encerrados",
    "probabilidade": "informe o grau (Remota, Possível ou Provável); o programa sugere pelas decisões, mas quem confirma é você",
    "momento_atual": "o programa deduz dos andamentos (se o arquivo trouxer o histórico) ou da coleta; confira depois",
    "area": "o programa deduz do tribunal e da classe; confira depois",
    "percentual_provisao": "o programa calcula provisão ÷ passivo potencial quando a provisão estiver informada; sem ela, informe",
    frozenset({"polo_cliente", "parte_contraria"}): "o programa define quando você marca quem é o cliente (na tela de conferência)",
    "materia_principal": "o programa classifica pelo assunto e pelo objeto; confira depois",
}
# campos que ganham a própria frase (a solução deles difere dos vizinhos)
SOZINHOS = frozenset({"valor_causa"})
CAUDA = {
    BUSCAVEL: "o programa busca no PJe/jus.br ao coletar",
    DEDUZIVEL: "o programa deduz pelas regras (e pela IA, se estiver ligada) a partir dos andamentos e das decisões",
    VOCE: "precisa de você: informe na planilha ou na ficha do processo",
}


# ---------------------------------------------------------------- entrada: fichas ou RelatorioLido

def _ehrel(fonte):
    return isinstance(fonte, dict) and "processos" in fonte


def fichas_do_relatorio(rel):
    """Fichas v2 simples (sem consolidar nem gravar) de um RelatorioLido, com a mesma regra de origem e de ativo do
    assistente: serve para contar o que o arquivo trouxe."""
    fichas = []
    for p in rel.get("processos", []):
        numero = p.get("numero")
        if not numero:
            continue
        f = fch.nova_ficha(numero)
        for campo, c in (p.get("campos") or {}).items():
            valor = c.get("valor") if isinstance(c, dict) else c
            origem = c.get("origem") if isinstance(c, dict) else None
            if campo in fch.CAMPOS and valor not in (None, ""):
                fch.definir(f, campo, valor, origem if origem in fch.PRIORIDADE else "migrado", forcar=True)
        if not fch.obter(f, "cliente") and rel.get("cliente"):
            fch.definir(f, "cliente", rel["cliente"], "migrado")
        fch.derivar_contingencia(f["campos"])
        if not fch.obter(f, "momento_atual") and p.get("andamentos"):
            movs = [{"data": a.get("data"), "texto": a.get("texto") or "", "grau": None} for a in p["andamentos"]]
            deduzido, evidencia = taxonomia.momento_por_regras(movs)
            if deduzido:
                fch.definir(f, "momento_atual", deduzido, "derivado", evidencia=evidencia)
        momento = fch.obter(f, "momento_atual")
        ativo = taxonomia.momento_ativo(momento) if momento else None
        if ativo is None and fch.obter(f, "situacao") == "Encerrado":
            ativo = False
        if ativo is None and p.get("ativo") is False:
            ativo = False
        if ativo is not None:
            f["ativo"] = ativo
        fichas.append(f)
    return fichas


# ---------------------------------------------------------------- contagem

def _ativo(f):
    return bool(f.get("ativo", True))


def _com_risco(f):
    """Processo ativo cuja perda é provável ou possível (ou ainda sem grau): é onde há provisão a constituir."""
    return _ativo(f) and fch.obter(f, "probabilidade") != "Remota"


def _aplica(f, chave):
    if chave == "encerrados":
        return not _ativo(f)
    if chave == "risco":
        return _com_risco(f)
    if chave == "com_deposito":
        return fch.obter(f, "deposito_judicial") == "Sim"
    return True


def _lista_em_portugues(itens):
    itens = list(itens)
    if len(itens) <= 1:
        return "".join(itens)
    return ", ".join(itens[:-1]) + " e " + itens[-1]


def _colunas_por_campo(mapeamento):
    """{campo: [nomes de coluna]} das colunas aplicadas do mapeamento (formatos de `rel["mapeamento"]` ou da tela)."""
    saida = {}
    for m in mapeamento or []:
        if not isinstance(m, dict):
            continue
        campo = m.get("campo")
        if not campo or m.get("aplicado") is False:
            continue
        nome = str(m.get("coluna") or "").strip()
        if nome and nome not in saida.setdefault(campo, []):
            saida[campo].append(nome)
    return saida


# campo que o leitor tira de dentro de OUTRA coluna do arquivo ("REMOTA - texto": o texto vai para a justificativa)
VEM_DA_COLUNA_DE = {"justificativa_probabilidade": "probabilidade"}


def _origem_do_campo(campo, colunas, do_arquivo):
    if colunas:
        return "do arquivo, " + ("coluna " if len(colunas) == 1 else "colunas ") + " e ".join(f"«{c}»" for c in colunas)
    if do_arquivo:
        return "do arquivo"
    return _como_completar(campo)


def _como_completar(campo):
    if campo in CAMPOS_BUSCAVEIS:
        return BUSCAVEL
    if campo in CAMPOS_DEDUZIVEIS:
        return DEDUZIVEL
    return VOCE


def _contar(fichas, campo):
    """(preenchidos, total, a_confirmar, do_arquivo) do campo, respeitando a quem ele se aplica. `a_confirmar`: valores
    que o programa deduziu ou sugeriu (origem derivado/sugerido); `do_arquivo`: valores que vieram do que a pessoa escreveu."""
    chave = APLICA_A.get(campo, "todos")
    alvo = [f for f in fichas if _aplica(f, chave)]
    cheios = [f for f in alvo if fch.obter(f, campo) not in (None, "")]
    a_confirmar = sum(1 for f in cheios if fch.origem(f, campo) in ("sugerido", "derivado"))
    return len(cheios), len(alvo), a_confirmar, len(cheios) - a_confirmar


def _campo(fichas, campo, colunas_do_campo, colunas_por_campo=None):
    colunas_por_campo = colunas_por_campo or {}
    rotulo, grupo, tipo, _ = fch.CAMPOS[campo]
    p, t, a_confirmar, do_arquivo = _contar(fichas, campo)
    if campo == "depositos_recursais" and not t:
        # nenhum processo tem depósito marcado como Sim: o valor só aparece quando existe (e não é falta)
        p = do_arquivo = sum(1 for f in fichas if fch.obter(f, campo) not in (None, ""))
    chave = APLICA_A.get(campo, "todos")
    colunas_do_campo = colunas_do_campo or (colunas_por_campo.get(VEM_DA_COLUNA_DE.get(campo)) if do_arquivo else []) or []
    return {"campo": campo, "rotulo": rotulo, "grupo": grupo, "tipo": tipo, "preenchidos": p, "total": t,
            "percentual": (p / t) if t else None, "origem": _origem_do_campo(campo, colunas_do_campo, do_arquivo),
            "completar_por": _como_completar(campo) if t and p < t else None, "colunas": list(colunas_do_campo),
            "aplica_a": chave, "opcional": campo in CAMPOS_OPCIONAIS, "a_confirmar": a_confirmar}


def _mensagens_do_grupo(campos):
    """Frases do que falta no grupo (campos obrigatórios com lacuna), agrupando os que têm a mesma situação."""
    faltas = [c for c in campos if not c["opcional"] and c["total"] and c["preenchidos"] < c["total"]]
    clusters = {}
    for c in faltas:
        clusters.setdefault((c["completar_por"], c["preenchidos"], c["total"], c["aplica_a"],
                             c["campo"] if c["campo"] in SOZINHOS else ""), []).append(c)
    frases = []
    for (como, p, t, chave, _), cs in clusters.items():
        rotulos = _lista_em_portugues([c["rotulo"].split(" / ")[0].split(" (")[0] for c in cs])
        qualificador = QUALIFICADOR[chave].format(n=t) if chave != "todos" else ""
        onde = f"no arquivo ({qualificador})" if qualificador else "no arquivo"
        conjunto = frozenset(c["campo"] for c in cs)
        if conjunto in DICAS:
            cauda = DICAS[conjunto]
        elif len(cs) == 1 and cs[0]["campo"] in DICAS:
            cauda = DICAS[cs[0]["campo"]]
        else:
            cauda = CAUDA[como]
        if p == 0:
            frases.append(f"{rotulos}: {p} de {t} {onde}; {cauda}.")
        else:
            frases.append(f"{rotulos}: {p} de {t} {onde}; faltam {t - p}: {cauda}.")
    ordem = {BUSCAVEL: 0, DEDUZIVEL: 1, VOCE: 2}
    chaves = sorted(clusters, key=lambda k: (ordem[k[0]], -(k[2] - k[1]), k[0]))
    por_chave = dict(zip(clusters, frases))
    return [por_chave[k] for k in chaves]


# ---------------------------------------------------------------- principal

def lacunas(fonte, mapeamento=None, colunas_sem_destino=None):
    """Relatório de lacunas (ver o cabeçalho do módulo). `fonte`: RelatorioLido (dict com "processos") ou lista de
    fichas v2. `mapeamento` (opcional): lista de {"coluna", "campo", "aplicado"} (a de `rel["mapeamento"]` ou a da tela de
    migração), para dizer de qual coluna cada campo vem. `colunas_sem_destino`: como em `rel["colunas_sem_destino"]`."""
    if _ehrel(fonte):
        rel = fonte
        fichas = fichas_do_relatorio(rel)
        mapeamento = mapeamento if mapeamento is not None else rel.get("mapeamento")
        colunas_sem_destino = colunas_sem_destino if colunas_sem_destino is not None else rel.get("colunas_sem_destino")
    else:
        fichas = [fch.de_carteira_v1(f) for f in (fonte or [])]
    colunas = _colunas_por_campo(mapeamento)
    ativos = sum(1 for f in fichas if _ativo(f))
    grupos = []
    for grupo, rotulo in ROTULO_DO_GRUPO.items():
        campos = [_campo(fichas, c, colunas.get(c, []), colunas) for c, v in fch.CAMPOS.items() if v[1] == grupo]
        obrigatorios = [c for c in campos if not c["opcional"] and c["total"]]
        base = obrigatorios or [c for c in campos if c["total"]]
        p, t = sum(c["preenchidos"] for c in base), sum(c["total"] for c in base)
        grupos.append({"grupo": grupo, "rotulo": rotulo, "campos": campos, "preenchidos": p, "total": t,
                       "percentual": (p / t) if t else None, "o_que_falta": _mensagens_do_grupo(campos)})
    todos = [c for g in grupos for c in g["campos"]]
    exigidos = [c for c in todos if not c["opcional"] and c["total"]]
    p, t = sum(c["preenchidos"] for c in exigidos), sum(c["total"] for c in exigidos)
    sem_destino = [{"coluna": str(c.get("coluna") or ""), "aba": c.get("aba") or "", "amostra": list(c.get("amostra") or [])[:3]}
                   for c in (colunas_sem_destino or []) if c.get("coluna")]
    return {"total_processos": len(fichas), "ativos": ativos, "encerrados": len(fichas) - ativos, "grupos": grupos,
            "o_que_falta": [m for g in grupos for m in g["o_que_falta"]], "colunas_sem_destino": sem_destino,
            "resumo": {"percentual": (p / t) if t else None, "campos_completos": sum(1 for c in exigidos if c["preenchidos"] == c["total"]),
                       "campos_com_falta": sum(1 for c in exigidos if 0 < c["preenchidos"] < c["total"]),
                       "campos_vazios": sum(1 for c in exigidos if c["preenchidos"] == 0),
                       "a_confirmar": sum(c["a_confirmar"] for c in todos)}}


def percentual_texto(valor):
    """0.4 -> '40%'; None -> '—'."""
    return "—" if valor is None else f"{round(valor * 100)}%"


def linhas_para_planilha(lac):
    """Linhas da aba "Faltas da migração": [{"Grupo", "Campo", "Preenchidos", "Total", "Percentual", "Origem", "O que fazer"}].
    Uma linha por campo e, no fim de cada grupo, uma linha "(resumo do grupo)" com o que falta."""
    linhas = []
    for g in lac["grupos"]:
        for c in g["campos"]:
            if not c["total"] and not c["preenchidos"]:
                continue
            fazer = ""
            if c["total"] and c["preenchidos"] < c["total"]:
                fazer = DICAS.get(c["campo"]) or CAUDA.get(c["completar_por"], "")
                if c["opcional"]:
                    fazer = "(opcional) " + fazer
            linhas.append({"Grupo": g["rotulo"], "Campo": c["rotulo"], "Preenchidos": c["preenchidos"], "Total": c["total"],
                           "Percentual": c["percentual"], "Origem": c["origem"], "O que fazer": fazer})
        if g["o_que_falta"]:
            linhas.append({"Grupo": g["rotulo"], "Campo": "(resumo do grupo)", "Preenchidos": g["preenchidos"], "Total": g["total"],
                           "Percentual": g["percentual"], "Origem": "", "O que fazer": "\n".join(g["o_que_falta"])})
    return linhas
