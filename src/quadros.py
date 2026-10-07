"""Quadros analíticos da carteira, em estrutura de dados, com as notas metodológicas em português (WS-11).

São os quadros que hoje se montam à mão: quem escreve a planilha (`escritores/xlsx_b`) e o dashboard recebem a
estrutura pronta, e as MESMAS notas vão junto (um número sem a nota que o explica engana o leitor).

    quadros.gerar(fichas, perfil=None, *, top=10, apenas_confirmados=True) -> {
        "acordos_x_economia": Q, "maiores_exposicoes": Q, "condenacao_x_causa": Q,
        "composicao_por_tese": Q, "desfecho_por_tese": Q,
        "notas": [str],        # notas gerais + as de cada quadro, na ordem, já com os números do caso
        "avisos": [Aviso]}     # ficha repetida ignorada etc.
    Q = {"titulo", "colunas": [{"chave", "rotulo", "tipo": texto|inteiro|dinheiro|percentual}],
         "linhas": [{chave: valor}], "resumo": {...}, "detalhe": [...], "notas": [str]}

Cada quadro também sai sozinho: acordos_x_economia(fichas), maiores_exposicoes(fichas, top=10),
condenacao_x_causa(fichas), composicao_por_tese(fichas), desfecho_por_tese(fichas). Dinheiro vai em texto decimal
("1234.56"), percentual em número com 2 casas (12.5 = 12,5%), contagem em inteiro; vazio é None.

COMO CADA QUADRO CALCULA (as notas repetem isto em linguagem simples):

1) acordos_x_economia  Só processos ENCERRADOS. Economia do processo = valor economizado lançado; na falta,
   valor da causa menos valor estimado lançado; sem nenhum dos dois o processo fica fora (e é contado).
   Três camadas, da mais larga à mais estrita:
     total_geral                    todos os encerrados com economia (o número "inflado");
     desembolso_do_cliente          sem acordo pago por terceiro, sem exclusão da lide e sem cliente autor;
     desfecho_pecuniario_definido   o INDICADOR RECOMENDADO: além do anterior, sem acordo sem valor lançado e só
                                    com desfecho de valor definido (acordo com valor, condenação com valor
                                    arbitrado, improcedência).
   As ressalvas vêm de qualidade.ressalvas_de_economia (convenção do marcador em `observacoes`).
2) maiores_exposicoes  Processos ativos em que o cliente NÃO é autor (autor não tem exposição, tem expectativa);
   exposição = o maior valor entre estimado, arbitrado, execução e causa (a coluna `base` diz qual). Empate de
   valor: vale a ordem estimado, arbitrado, execução, causa; empate de ranking: número do processo.
3) condenacao_x_causa  Processos com resultado Procedente ou Parcialmente procedente E valor arbitrado lançado:
   condenação / valor da causa, por resultado e no total.
4) composicao_por_tese  Tese = matéria principal (reconhecida pelo vocabulário quando possível). Peso por número
   de processos e por valor da causa.
5) desfecho_por_tese  SÓ processos julgados no mérito (procedente, parcialmente procedente, improcedente).
   "Favorável ao cliente" olha o polo do cliente: improcedente se réu, procedente se autor; parcial nunca conta
   como favorável. É outra coisa que o campo Probabilidade (esta é a do resultado e não inverte por polo).

`apenas_confirmados=True` (padrão) ignora valores que são só SUGESTÃO do programa (origem `sugerido`, ainda sem
aprovação humana): indicador para cliente não sai de sugestão não revisada; a nota diz quantos ficaram de fora.
Processos duplicados (mesmo número) e linhas-marcador não entram.
"""
from collections import Counter, defaultdict
from decimal import Decimal

import ficha
import qualidade
import taxonomia

RESSALVAS_DE_DESEMBOLSO = ("acordo_terceiro", "exclusao_lide", "cliente_autor")
SEM_MATERIA = "(sem matéria informada)"


# ---------------------------------------------------------------- base

def _preparar(fichas, apenas_confirmados):
    """(fichas v2 únicas e sem marcador, avisos, quantos campos só sugeridos ficaram de fora)."""
    vistas, avisos, fora = {}, [], 0
    for f in (ficha.de_carteira_v1(x) for x in (fichas or [])):
        numero = f.get("numero", "")
        if qualidade.e_marcador(f):
            continue
        if numero in vistas:
            avisos.append({"nivel": "atencao", "codigo": "ficha_repetida_ignorada", "onde": numero,
                           "mensagem": f"O processo {numero} tem mais de uma ficha: valeu a primeira.", "candidatos": []})
            continue
        if apenas_confirmados:
            campos = {k: v for k, v in f.get("campos", {}).items() if v.get("origem") != "sugerido"}
            fora += sum(1 for k, v in f.get("campos", {}).items() if k not in campos and v.get("valor") not in (None, ""))
            f = {**f, "campos": campos}
        vistas[numero] = f
    return list(vistas.values()), avisos, fora


def _v(f, campo):
    return ficha.dinheiro(ficha.obter(f, campo))


def _soma(valores):
    return sum((v for v in valores if v is not None), Decimal(0))


def _t(valor):
    return None if valor is None else f"{valor:.2f}"


def _pct(parte, todo):
    return round(float(parte / todo * 100), 2) if todo else None


def _brl(valor):
    return ficha.dinheiro_br(valor)


def _col(chave, rotulo, tipo="texto"):
    return {"chave": chave, "rotulo": rotulo, "tipo": tipo}


def _quadro(titulo, colunas, linhas, resumo, notas, detalhe=None, avisos=None):
    return {"titulo": titulo, "colunas": colunas, "linhas": linhas, "resumo": resumo, "detalhe": detalhe or [],
            "notas": notas, "avisos": avisos or []}


def _nota_sugeridos(fora):
    return ([f"{fora} valor(es) apenas sugerido(s) pelo programa, ainda sem aprovação, ficaram de fora destes números."]
            if fora else [])


def _tese(f):
    bruto = (ficha.obter(f, "materia_principal") or "").strip()
    if not bruto:
        return SEM_MATERIA
    return taxonomia.normalizar("materia", bruto) or bruto


def economia(f):
    """Economia do processo: valor economizado lançado; senão causa menos estimado (ambos lançados); senão None."""
    lancada = _v(f, "valor_economizado")
    if lancada is not None:
        return lancada
    causa, estimado = _v(f, "valor_causa"), _v(f, "valor_estimado")
    return causa - estimado if causa is not None and estimado is not None else None


# ---------------------------------------------------------------- 1) acordos x economia

def acordos_x_economia(fichas, *, apenas_confirmados=True):
    lista, avisos, fora = _preparar(fichas, apenas_confirmados)
    return _acordos_x_economia(lista, avisos, fora)


def _acordos_x_economia(lista, avisos, fora):
    encerrados = [f for f in lista if qualidade.encerrado(f)]
    universo = [(f, economia(f), qualidade.ressalvas_de_economia(f)) for f in encerrados]
    universo = [(f, e, r) for f, e, r in universo if e is not None]
    camadas = [
        ("total_geral", "Total geral (todos os encerrados com economia)", lambda f, r: True),
        ("desembolso_do_cliente", "Apenas com desembolso do cliente",
         lambda f, r: not set(r) & set(RESSALVAS_DE_DESEMBOLSO)),
        ("desfecho_pecuniario_definido", "Apenas desfecho pecuniário definido (indicador recomendado)",
         lambda f, r: not set(r) & set(RESSALVAS_DE_DESEMBOLSO) and "acordo_sem_valor" not in r
         and qualidade.desfecho_pecuniario_definido(f)),
    ]
    colunas = [_col("camada", "Camada"), _col("processos", "Processos", "inteiro"),
               _col("valor_causa", "Valor da causa", "dinheiro"), _col("valor_desfecho", "Valor do desfecho", "dinheiro"),
               _col("economia", "Economia", "dinheiro"), _col("percentual_economia", "Economia / valor da causa", "percentual"),
               _col("acordos", "Acordos", "inteiro"), _col("valor_acordos", "Valor dos acordos", "dinheiro")]
    linhas, detalhe, ultima = [], [], {}
    for chave, rotulo, regra in camadas:
        membros = [(f, e, r) for f, e, r in universo if regra(f, r)]
        causa = _soma(_v(f, "valor_causa") for f, _, _ in membros)
        total = _soma(e for _, e, _ in membros)
        acordos = [f for f, _, _ in membros if ficha.obter(f, "resultado") == "Acordo"]
        linhas.append({"camada": rotulo, "chave": chave, "processos": len(membros), "valor_causa": _t(causa),
                       "valor_desfecho": _t(causa - total), "economia": _t(total), "percentual_economia": _pct(total, causa),
                       "acordos": len(acordos), "valor_acordos": _t(_soma(_v(f, "valor_acordo") for f in acordos))})
        for f, _, _ in membros:
            ultima[f["numero"]] = chave
    for f, e, r in universo:
        detalhe.append({"numero": f["numero"], "cliente": ficha.obter(f, "cliente") or "", "resultado": ficha.obter(f, "resultado") or "",
                        "valor_causa": _t(_v(f, "valor_causa")), "valor_acordo": _t(_v(f, "valor_acordo")), "economia": _t(e),
                        "ressalvas": [qualidade.RESSALVAS[x] for x in r], "camada": ultima[f["numero"]]})
    motivos = Counter(x for _, _, r in universo for x in r)
    sem_desfecho = sum(1 for f, _, r in universo if not qualidade.desfecho_pecuniario_definido(f)
                       and not set(r) & set(RESSALVAS_DE_DESEMBOLSO) and "acordo_sem_valor" not in r)
    l1, l2, l3 = linhas
    sem_economia = len(encerrados) - len(universo)
    acordos_sem_valor_fora = sum(1 for f in encerrados if "acordo_sem_valor" in qualidade.ressalvas_de_economia(f)) - motivos["acordo_sem_valor"]
    notas = [
        "Economia de um processo = valor economizado lançado; na falta dele, valor da causa menos valor estimado. "
        "Só entram processos encerrados.",
        f"Total geral: {l1['processos']} processo(s), economia de {_brl(l1['economia'])}"
        + (f" ({str(l1['percentual_economia']).replace('.', ',')}% do valor da causa)" if l1['percentual_economia'] is not None else "")
        + ". Este número pode incluir acordos sem valor lançado, acordos pagos por terceiro, exclusões da lide e processos em que o cliente é autor, que o inflam.",
        f"Apenas com desembolso do cliente: tira {l1['processos'] - l2['processos']} processo(s) (acordo pago por terceiro: {motivos['acordo_terceiro']}; "
        f"exclusão da lide: {motivos['exclusao_lide']}; cliente autor: {motivos['cliente_autor']}). Economia: {_brl(l2['economia'])}.",
        f"Desfecho pecuniário definido (indicador recomendado): tira mais {l2['processos'] - l3['processos']} processo(s) "
        f"(acordo sem valor lançado: {motivos['acordo_sem_valor']}; encerrados sem valor definido, como extinção sem mérito, "
        f"arquivamento e incompetência: {sem_desfecho}). Economia: {_brl(l3['economia'])}. Use este número ao falar de economia.",
        f"{sem_economia} processo(s) encerrado(s) não têm valor de economia nem valor estimado lançados e ficaram fora das três camadas"
        + (f" (entre eles, {acordos_sem_valor_fora} acordo(s) sem valor lançado)." if acordos_sem_valor_fora else "."),
        "Marque acordo pago por terceiro e exclusão da lide com [acordo pago por terceiro] e [exclusão da lide] no campo Observações; "
        "sem a marca o programa não consegue separá-los.",
        *_nota_sugeridos(fora)]
    resumo = {"indicador_recomendado": "desfecho_pecuniario_definido", "encerrados": len(encerrados),
              "com_economia": len(universo), "sem_economia": sem_economia,
              "excluidos": {**{k: motivos[k] for k in ("acordo_sem_valor", *RESSALVAS_DE_DESEMBOLSO)},
                            "sem_desfecho_pecuniario_definido": sem_desfecho}}
    return _quadro("Acordos x economia (com ressalvas)", colunas, linhas, resumo, notas, detalhe, avisos)


# ---------------------------------------------------------------- 2) maiores exposições

BASES = (("valor_estimado", "estimado"), ("valor_arbitrado", "arbitrado"), ("valor_execucao", "execução"),
         ("valor_causa", "causa"))


def exposicao(f):
    """(valor, base) do maior valor entre estimado, arbitrado, execução e causa; None se não há nenhum positivo."""
    melhor = None
    for campo, nome in BASES:
        v = _v(f, campo)
        if v is not None and v > 0 and (melhor is None or v > melhor[0]):
            melhor = (v, nome)
    return melhor


def maiores_exposicoes(fichas, top=10, *, incluir_encerrados=False, incluir_cliente_autor=False, apenas_confirmados=True):
    lista, avisos, fora = _preparar(fichas, apenas_confirmados)
    return _maiores_exposicoes(lista, avisos, fora, top, incluir_encerrados, incluir_cliente_autor)


def _maiores_exposicoes(lista, avisos, fora, top=10, incluir_encerrados=False, incluir_cliente_autor=False):
    considerados = []
    for f in lista:
        if (qualidade.encerrado(f) and not incluir_encerrados) or (ficha.obter(f, "polo_cliente") == "ativo" and not incluir_cliente_autor):
            continue
        e = exposicao(f)
        if e:
            considerados.append((e[0], f["numero"], e[1], f))
    considerados.sort(key=lambda x: (-x[0], x[1]))
    colunas = [_col("posicao", "Posição", "inteiro"), _col("numero", "Processo"), _col("cliente", "Cliente"),
               _col("momento_atual", "Momento atual"), _col("exposicao", "Exposição", "dinheiro"),
               _col("base", "Origem do valor"), _col("valor_causa", "Valor da causa", "dinheiro")]
    linhas = [{"posicao": i, "numero": n, "cliente": ficha.obter(f, "cliente") or "", "momento_atual": ficha.obter(f, "momento_atual") or "",
               "exposicao": _t(v), "base": base, "valor_causa": _t(_v(f, "valor_causa"))}
              for i, (v, n, base, f) in enumerate(considerados[:top], 1)]
    total, do_topo = _soma(c[0] for c in considerados), _soma(c[0] for c in considerados[:top])
    resumo = {"processos_considerados": len(considerados), "exposicao_total": _t(total), "exposicao_top": _t(do_topo),
              "concentracao_top": _pct(do_topo, total)}
    notas = [
        "Exposição de um processo = o maior valor entre o estimado, o arbitrado em juízo, o da execução e o da causa; a coluna "
        "'Origem do valor' diz qual foi usado.",
        f"Entram {len(considerados)} processo(s) ativo(s) em que o cliente não é autor"
        + ("" if not incluir_encerrados else " (e encerrados)") + "; processo em que o cliente é autor não tem exposição e fica de fora.",
        f"Os {len(linhas)} maiores somam {_brl(resumo['exposicao_top'])}"
        + (f", {str(resumo['concentracao_top']).replace('.', ',')}% da exposição total de {_brl(resumo['exposicao_total'])}." if total else "."),
        "O valor da causa é o que o autor pediu, não uma previsão de condenação: para exposição realista, lance o valor estimado.",
        *_nota_sugeridos(fora)]
    return _quadro(f"Maiores exposições (top {top})", colunas, linhas, resumo, notas, avisos=avisos)


# ---------------------------------------------------------------- 3) condenação x valor da causa

def condenacao_x_causa(fichas, *, apenas_confirmados=True):
    lista, avisos, fora = _preparar(fichas, apenas_confirmados)
    return _condenacao_x_causa(lista, avisos, fora)


def _condenacao_x_causa(lista, avisos, fora):
    com, sem_valor = [], 0
    for f in lista:
        resultado = ficha.obter(f, "resultado")
        if resultado not in ("Procedente", "Parcialmente procedente"):
            continue
        causa, condenacao = _v(f, "valor_causa"), _v(f, "valor_arbitrado")
        if condenacao and causa and condenacao > 0 and causa > 0:
            com.append((f, resultado, causa, condenacao))
        else:
            sem_valor += 1
    colunas = [_col("resultado", "Resultado"), _col("processos", "Processos", "inteiro"),
               _col("valor_causa", "Valor da causa", "dinheiro"), _col("condenacao", "Condenação (valor arbitrado)", "dinheiro"),
               _col("percentual", "Condenação / valor da causa", "percentual")]
    linhas = []
    for resultado in ("Procedente", "Parcialmente procedente"):
        m = [x for x in com if x[1] == resultado]
        causa, cond = _soma(x[2] for x in m), _soma(x[3] for x in m)
        linhas.append({"resultado": resultado, "processos": len(m), "valor_causa": _t(causa), "condenacao": _t(cond),
                       "percentual": _pct(cond, causa)})
    causa, cond = _soma(x[2] for x in com), _soma(x[3] for x in com)
    linhas.append({"resultado": "Total", "processos": len(com), "valor_causa": _t(causa), "condenacao": _t(cond),
                   "percentual": _pct(cond, causa)})
    acima = sum(1 for x in com if x[3] > x[2])
    detalhe = [{"numero": f["numero"], "cliente": ficha.obter(f, "cliente") or "", "resultado": r, "valor_causa": _t(c),
                "condenacao": _t(k), "percentual": _pct(k, c), "diferenca": _t(c - k)}
               for f, r, c, k in sorted(com, key=lambda x: x[0]["numero"])]
    notas = [
        "Compara o valor arbitrado na condenação com o valor da causa, só nos processos com resultado procedente ou parcialmente "
        "procedente e com o valor arbitrado lançado.",
        f"Total: {len(com)} processo(s); condenação de {_brl(_t(cond))} contra {_brl(_t(causa))} de valor da causa"
        + (f" ({str(_pct(cond, causa)).replace('.', ',')}%)." if causa else "."),
        f"{sem_valor} processo(s) procedente(s) ou parcialmente procedente(s) não têm valor arbitrado (ou valor da causa) lançado e ficaram de fora.",
        *([f"{acima} processo(s) têm condenação acima do valor da causa (juros, correção e reflexos podem explicar): confira."] if acima else []),
        "O valor arbitrado é o da decisão, antes de recurso; não é o que será pago.",
        *_nota_sugeridos(fora)]
    return _quadro("Condenação x valor da causa", colunas, linhas, {"sem_valor_arbitrado": sem_valor, "acima_da_causa": acima},
                   notas, detalhe, avisos)


# ---------------------------------------------------------------- 4) composição por tese

def composicao_por_tese(fichas, *, apenas_confirmados=True):
    lista, avisos, fora = _preparar(fichas, apenas_confirmados)
    return _composicao_por_tese(lista, avisos, fora)


def _composicao_por_tese(lista, avisos, fora):
    grupos = defaultdict(list)
    for f in lista:
        grupos[_tese(f)].append(f)
    total_p, total_v = len(lista), _soma(_v(f, "valor_causa") for f in lista)
    colunas = [_col("tese", "Matéria (tese)"), _col("tema", "Tema"), _col("processos", "Processos", "inteiro"),
               _col("percentual_processos", "% dos processos", "percentual"), _col("ativos", "Ativos", "inteiro"),
               _col("valor_causa", "Valor da causa", "dinheiro"), _col("percentual_valor", "% do valor da causa", "percentual"),
               _col("conta_nos_rankings", "Conta nos rankings")]
    linhas = []
    for tese, membros in grupos.items():
        valor = _soma(_v(f, "valor_causa") for f in membros)
        dados = taxonomia.MATERIA.get(tese)
        linhas.append({"tese": tese, "tema": dados[0] if dados else None, "processos": len(membros),
                       "percentual_processos": _pct(len(membros), total_p), "ativos": sum(not qualidade.encerrado(f) for f in membros),
                       "valor_causa": _t(valor), "percentual_valor": _pct(valor, total_v),
                       "conta_nos_rankings": ("Sim" if dados[2] else "Não") if dados else None})
    linhas.sort(key=lambda r: (-r["processos"], -Decimal(r["valor_causa"]), r["tese"]))
    temas = defaultdict(lambda: [0, Decimal(0)])
    for r in linhas:
        temas[r["tema"] or "(fora do vocabulário)"][0] += r["processos"]
        temas[r["tema"] or "(fora do vocabulário)"][1] += Decimal(r["valor_causa"])
    resumo = {"processos": total_p, "valor_causa": _t(total_v), "teses": len(linhas),
              "por_tema": [{"tema": t, "processos": p, "valor_causa": _t(v)} for t, (p, v) in sorted(temas.items(), key=lambda x: (-x[1][0], x[0]))]}
    sem = grupos.get(SEM_MATERIA, [])
    fora_vocab = sorted(r["tese"] for r in linhas if r["tema"] is None and r["tese"] != SEM_MATERIA)
    notas = [
        "Tese = matéria principal do processo, reconhecida pelo vocabulário de matérias quando possível. Cada processo conta uma vez, "
        "na sua matéria principal (pedidos secundários não entram).",
        f"{total_p} processo(s) em {len(linhas)} tese(s). Os percentuais são sobre o total da carteira, inclusive matérias que não contam nos rankings.",
        *([f"{len(sem)} processo(s) sem matéria principal informada."] if sem else []),
        *([f"Matérias fora do vocabulário (contadas como estão escritas): {', '.join(fora_vocab)}."] if fora_vocab else []),
        "Valor da causa é o pedido do autor, não o risco: para risco, veja o quadro de maiores exposições.",
        *_nota_sugeridos(fora)]
    return _quadro("Composição da carteira por tese", colunas, linhas, resumo, notas, avisos=avisos)


# ---------------------------------------------------------------- 5) desfecho por tese

MERITO = ("Procedente", "Parcialmente procedente", "Improcedente")


def desfecho_por_tese(fichas, *, apenas_confirmados=True):
    lista, avisos, fora = _preparar(fichas, apenas_confirmados)
    return _desfecho_por_tese(lista, avisos, fora)


def _favoravel(resultado, polo):
    """True/False se o resultado é favorável ao cliente conforme o polo; None sem polo ou se for parcial."""
    if polo not in ("ativo", "passivo"):
        return None
    if resultado == "Parcialmente procedente":
        return False
    return resultado == ("Improcedente" if polo == "passivo" else "Procedente")


def _desfecho_por_tese(lista, avisos, fora):
    julgados = [f for f in lista if ficha.obter(f, "resultado") in MERITO]
    fora_do_merito = Counter(ficha.obter(f, "resultado") for f in lista if ficha.obter(f, "resultado") and ficha.obter(f, "resultado") not in MERITO)
    grupos = defaultdict(list)
    for f in julgados:
        grupos[_tese(f)].append(f)
    colunas = [_col("tese", "Matéria (tese)"), _col("julgados", "Julgados no mérito", "inteiro"),
               _col("procedentes", "Procedentes", "inteiro"), _col("parciais", "Parcialmente procedentes", "inteiro"),
               _col("improcedentes", "Improcedentes", "inteiro"), _col("favoraveis", "Favoráveis ao cliente", "inteiro"),
               _col("percentual_favoravel", "% favorável ao cliente", "percentual"), _col("sem_polo", "Sem polo informado", "inteiro")]

    def linha(rotulo, membros):
        r = Counter(ficha.obter(f, "resultado") for f in membros)
        favoraveis = sum(1 for f in membros if _favoravel(ficha.obter(f, "resultado"), ficha.obter(f, "polo_cliente")))
        sem_polo = sum(1 for f in membros if ficha.obter(f, "polo_cliente") not in ("ativo", "passivo"))
        return {"tese": rotulo, "julgados": len(membros), "procedentes": r["Procedente"], "parciais": r["Parcialmente procedente"],
                "improcedentes": r["Improcedente"], "favoraveis": favoraveis,
                "percentual_favoravel": _pct(Decimal(favoraveis), Decimal(len(membros) - sem_polo)), "sem_polo": sem_polo}

    linhas = sorted((linha(t, m) for t, m in grupos.items()), key=lambda r: (-r["julgados"], r["tese"]))
    total = linha("Total", julgados)
    notas = [
        "Só entram processos julgados no mérito (procedente, parcialmente procedente ou improcedente). "
        f"Total: {total['julgados']} processo(s) em {len(linhas)} tese(s).",
        *([f"Ficaram de fora {sum(fora_do_merito.values())} processo(s) sem julgamento de mérito (" + ", ".join(f"{k}: {v}" for k, v in sorted(fora_do_merito.items())) + ")."]
          if fora_do_merito else []),
        "'Favorável ao cliente' olha o polo do cliente: improcedente é favorável ao réu e procedente é favorável ao autor; "
        "parcialmente procedente não conta como favorável. O percentual é sobre os processos com polo informado.",
        "Isto é diferente do campo Probabilidade, que é a do resultado do processo e não inverte por polo.",
        "Decisão de primeira instância ainda sujeita a recurso conta como lançada; o quadro mostra o que foi decidido, não o resultado final.",
        *_nota_sugeridos(fora)]
    return _quadro("Desfecho por tese (julgados no mérito)", colunas, linhas, {"total": total, "fora_do_merito": dict(fora_do_merito)},
                   notas, avisos=avisos)


# ---------------------------------------------------------------- tudo junto

def gerar(fichas, perfil=None, *, top=10, apenas_confirmados=True):
    """Os cinco quadros, com as notas juntas. `perfil` é aceito por simetria com o verificador (por enquanto sem efeito)."""
    lista, avisos, fora = _preparar(fichas, apenas_confirmados)
    q = {"acordos_x_economia": _acordos_x_economia(lista, [], fora),
         "maiores_exposicoes": _maiores_exposicoes(lista, [], fora, top),
         "condenacao_x_causa": _condenacao_x_causa(lista, [], fora),
         "composicao_por_tese": _composicao_por_tese(lista, [], fora),
         "desfecho_por_tese": _desfecho_por_tese(lista, [], fora)}
    notas = ["Os valores são os lançados nas fichas (já revisados); processo sem o valor necessário fica fora da conta e é contado "
             "na nota de cada quadro.",
             "Processos vinculados (agravo, apenso, recurso) contam junto com o principal, como uma linha só.",
             *_nota_sugeridos(fora)]
    for chave, quadro in q.items():
        notas.append(f"{quadro['titulo']}:")
        notas.extend(n for n in quadro["notas"] if n not in _nota_sugeridos(fora))
    q["notas"], q["avisos"] = notas, avisos
    return q
