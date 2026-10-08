"""Sugestão dos campos de julgamento por regra (PLANO 7.2; CONTRATOS §10).

Quatro campos da ficha são sugeridos a partir do teor das decisões: `resultado`, `probabilidade`,
`valor_estimado` e `valor_economizado`. São regras determinísticas e auditáveis, sem IA: o módulo só
LÊ TEXTO de decisões que já foram aprovadas por uma pessoa (a leitura do teor com IA fica com a
síntese, WS-5). Nada é gravado como definitivo: a sugestão volta com a regra aplicada, a evidência
(documento e trecho) e as ressalvas, e só `aplicar` a grava, sempre com origem `sugerido`. Campo que
já tem valor de origem maior (humano, coletado, migrado ou derivado) NÃO aparece na saída e nunca é
sobrescrito; só uma sugestão anterior (origem `sugerido`) é atualizada.

    sugestoes = julgamento.sugerir(ficha, eventos)
    # {"resultado": {"valor": "Procedente", "regra": "resultado_procedente",
    #                "evidencia": {"documento": "Sentença de 18/06/2026", "trecho": "JULGO PROCEDENTE ..."},
    #                "ressalvas": ["Sujeita a recurso: ..."]}, "probabilidade": {...}, ...}
    sugestoes, avisos = julgamento.sugerir_com_avisos(ficha, eventos)   # + o que não deu para sugerir, e por quê
    julgamento.aplicar(ficha, sugestoes)                                # grava origem "sugerido"
    julgamento.concordancia(fichas_migradas)                            # teste retroativo (calibração das regras)

REGRAS (probabilidade é a do RESULTADO do processo; NÃO há inversão por polo: se o cliente é autor,
"Provável" é a chance de o pedido vencer, e se é réu, a de o pedido ser acolhido)

- resultado: teor da decisão mais recente (data; no mesmo dia, a de grau mais alto). Palavras de
  julgamento do texto: Procedente, Parcialmente procedente, Improcedente; e os desfechos Acordo
  (homologação), Arquivado / desistência, Incompetência declarada, Extinto sem resolução de mérito.
  Sem decisão: sem sugestão. Acórdão que nega provimento mantém o resultado anterior; acórdão que dá
  provimento sem dizer o resultado NÃO gera sugestão (aviso `acordao_reforma_sem_resultado`).
- probabilidade: Possível antes de decisão; Provável com procedência ou parcial procedência; Remota
  com improcedência; vazia se encerrado por acordo, extinção, desistência ou incompetência. Decisão de
  1º grau sem trânsito em julgado leva a ressalva "Sujeita a recurso".
- valor_estimado: valor da causa até haver decisão com valor arbitrado; então o arbitrado (campo
  `valor_arbitrado` da ficha ou valor lido da condenação); em acordo, o valor do acordo; improcedência,
  extinção e desistência: 0,00; sem valor claro, mantém o da causa e ressalva.
- valor_economizado = valor da causa − valor estimado, SÓ de processo encerrado. NÃO conta (volta com
  `valor` None e a ressalva): acordo sem valor lançado, acordo pago por terceiro, exclusão da lide,
  cliente autor, incompetência e valor estimado sem base na decisão.

Fontes: eventos APROVADOS (`status` aprovado ou relatado) do processo principal e dos vinculados do tipo
recurso; de cada evento entram o trecho de origem, o conteúdo aprovado, o texto do arquivo extraído e o
título/frase do movimento. Só decisão conta (documento do tipo sentença, acórdão, decisão, despacho ou ata;
movimento que não seja "juntada"): petição que "requer a improcedência" não vira resultado. Também entra,
com ressalva, o texto de andamentos do relatório anterior (`linha_de_base` e `ultimo_texto_gravado`), pois é
a única fonte dos processos migrados que ainda não tiveram evento.

Só dados e textos fictícios nos testes; nada aqui usa rede.
"""
import datetime
import re
import unicodedata
from decimal import Decimal

import ficha as fch
import taxonomia
from traduzir import categoria as _categoria_do_documento

CAMPOS_SUGERIDOS = ("resultado", "probabilidade", "valor_estimado", "valor_economizado")
STATUS_APROVADOS = ("aprovado", "relatado")
LIMITE_TRECHO = 300
LIMITE_TEXTO_CURTO = 700   # fonte curta (resumo, trecho, título): aceita também a palavra solta, sem verbo de julgar
TOLERANCIA = Decimal("0.01")
MERITO = ("Procedente", "Parcialmente procedente", "Improcedente")
SEM_PROBABILIDADE = ("Acordo", "Extinto sem resolução de mérito", "Arquivado / desistência", "Incompetência declarada")
ENCERRAM = ("Acordo", "Extinto sem resolução de mérito", "Arquivado / desistência")

# regra -> o que faz (para a tela explicar ao revisor)
REGRAS = {
    "resultado_procedente": "Decisão julgou procedente o pedido.",
    "resultado_parcial": "Decisão julgou parcialmente procedente o pedido.",
    "resultado_improcedente": "Decisão julgou improcedente o pedido.",
    "resultado_acordo": "Decisão homologou acordo.",
    "resultado_desistencia": "Decisão homologou desistência.",
    "resultado_incompetencia": "Decisão declarou a incompetência do juízo.",
    "resultado_extincao": "Decisão extinguiu o processo sem resolução de mérito.",
    "resultado_mantido": "Acórdão manteve a decisão anterior.",
    "resultado_arquivamento": "Arquivamento sem decisão de mérito identificada.",
    "prob_sem_decisao": "Sem decisão: probabilidade Possível.",
    "prob_procedencia": "Procedência: probabilidade Provável.",
    "prob_parcial": "Parcial procedência: probabilidade Provável.",
    "prob_improcedencia": "Improcedência: probabilidade Remota.",
    "estimado_causa": "Sem decisão: valor da causa.",
    "estimado_arbitrado": "Valor arbitrado na decisão (ficha).",
    "estimado_condenacao": "Valor da condenação lido da decisão.",
    "estimado_acordo": "Valor do acordo.",
    "estimado_zero": "Decisão sem condenação: valor zero.",
    "estimado_causa_sem_valor": "Sem valor claro na decisão: mantido o valor da causa.",
    "economia_causa_menos_estimado": "Valor da causa menos valor estimado (processo encerrado).",
    "economia_nao_conta": "Caso que não conta como economia.",
}

# ------------------------------------------------------------------ texto

def _n(texto):
    """Minúsculas e sem acento, MANTENDO o tamanho (cada caractere vira um), para que a posição achada no
    texto normalizado valha no original e o trecho de evidência saia com a grafia correta."""
    saida = []
    for c in str(texto or ""):
        d = unicodedata.normalize("NFKD", c)
        base = next((x for x in d if ord(x) < 128), " ")
        saida.append(base.lower())
    return "".join(saida)


def _trecho(original, inicio, fim):
    """Janela do texto original em torno de [inicio, fim), em uma linha, no máximo LIMITE_TRECHO caracteres."""
    ini = max(0, inicio - 110)
    ate = min(len(original), max(fim, inicio) + 170)
    # recua/avança até fronteira de palavra para não cortar no meio
    while ini > 0 and not original[ini - 1].isspace():
        ini -= 1
    while ate < len(original) and not original[ate].isspace():
        ate += 1
    texto = " ".join(original[ini:ate].split())
    if len(texto) > LIMITE_TRECHO:
        texto = texto[:LIMITE_TRECHO].rsplit(" ", 1)[0]
    return ("… " if ini > 0 else "") + texto + (" …" if ate < len(original) else "")


def _aviso(nivel, codigo, onde, mensagem, candidatos=None):
    return {"nivel": nivel, "codigo": codigo, "onde": onde, "mensagem": mensagem, "candidatos": candidatos or []}


def _br(d):
    return d.strftime("%d/%m/%Y") if d else "sem data"


# ------------------------------------------------------------------ expressões (texto já normalizado)

_VERBO = r"(?:julg\w+|decid\w+|declar\w+|reconhec\w+|dispo\w+)"
_ESPACO = r"(?:(?!\.\s)[^;]){0,%d}?"        # não atravessa o ponto final de uma frase
_PALAVRA_MERITO = (r"parcial\w*\s+procedent\w*|procedent\w*\s+em\s+parte|procedencia\s+(?:em\s+)?parcial|"
                   r"parcial\s+procedencia|improcedent\w*|improcedencia|\bprocedent\w*|\bprocedencia")
MERITO_VERBO = re.compile(_VERBO + _ESPACO % 60 + r"(" + _PALAVRA_MERITO + r")")
MERITO_SOLTO = re.compile(r"(" + _PALAVRA_MERITO + r")")
ACORDO = re.compile(r"homolog\w*" + _ESPACO % 40 + r"(?:acordo|transacao|composicao)|"
                    r"(?:acordo|transacao)\s+(?:foi\s+|restou\s+)?homologad\w+")
DESISTENCIA = re.compile(r"homolog\w*" + _ESPACO % 40 + r"desistencia|desistencia\s+(?:foi\s+)?homologad\w+|"
                         r"(?:extingu\w+|extint\w+|extingo)" + _ESPACO % 60 + r"desistencia")
INCOMPETENCIA = re.compile(r"(?:declar\w+|reconhec\w+)" + _ESPACO % 40 + r"incompetencia|"
                           r"incompetencia\s+(?:do\s+juizo\s+)?(?:foi\s+)?(?:declarada|reconhecida)|"
                           r"declin\w+\s+(?:da\s+|de\s+)?competencia")
EXTINCAO = re.compile(r"(?:extingu\w+|extint\w+|extingo)" + _ESPACO % 80 + r"sem\s+(?:a\s+)?(?:resolucao|julgamento|exame|analise)"
                      r"\s+(?:do\s+)?merito|sem\s+resolucao\s+(?:do\s+)?merito|indefer\w+\s+(?:a\s+)?(?:peticao\s+)?inicial")
ARQUIVAMENTO = re.compile(r"arquivad\w*\s+definitiv\w+|arquivem-se|arquive-se|baixa\s+definitiva")
NEGA_ANTES = re.compile(r"indefer\w+|indefir\w+|nao\s+homolog\w+|deixo\s+de\s+homolog\w+|rejeit\w+|afast\w+|nega\w*\s+a\s+homolog\w+")
PEDIDO_ANTES = re.compile(r"requer\w*|pede\b|pediu|pedem|pedindo|pleite\w+|postul\w+|sustent\w+|alega\w*")
INCIDENTAL = re.compile(r"impugna\w+|embargos\s+a\s+execucao|embargos\s+do\s+devedor|embargos\s+de\s+terceiro|"
                        r"excecao\s+de\s+pre|embargos\s+de\s+declaracao|embargos\s+declaratorios")
MANTEM = re.compile(r"nego\s+provimento|negou\s+provimento|negado\s+provimento|negar\s+provimento|nao\s+provid\w+|"
                    r"improvid\w+|desprovid\w+|mantenho\s+a\s+sentenca|mantid\w+\s+a\s+sentenca|"
                    r"mantend\w+\s+(?:integralmente\s+)?a\s+sentenca|negad\w+\s+seguimento|"
                    r"nao\s+conhec\w+\s+(?:d[oa]\s+)?(?:recurso|apelacao)")
PROVIMENTO = re.compile(r"(?:dou|deu|dar|dado|dando)\s+(?:integral\s+|parcial\s+|total\s+)?provimento|"
                        r"(?<!nao )\bprovid[oa]s?\b|reform\w+\s+a\s+sentenca|reformad\w+|reformo|reformando|"
                        r"anul\w+\s+a\s+sentenca|cassad\w+\s+a\s+sentenca")
SO_AGRAVO = re.compile(r"agravo\s+(?:de\s+instrumento|interno|regimental)")
DA_SENTENCA = re.compile(r"sentenca|apelacao|recurso\s+ordinario|recurso\s+inominado")
TRANSITO = re.compile(r"transit\w+\s+em\s+julgado|transito\s+em\s+julgado")
SEM_TRANSITO = re.compile(r"nao\s+transit\w+|sem\s+transito|aguard\w+\s+(?:o\s+)?transito")
RECURSO = re.compile(r"apelac\w+|recurso\s+(?:ordinario|inominado|de\s+revista|especial|extraordinario|adesivo)|"
                     r"agravo\s+de\s+peticao|em\s+grau\s+de\s+recurso|contra-?razoes|razoes\s+de\s+recurso|"
                     r"interpos\w+\s+(?:o\s+)?recurso|recurso\s+interposto")
TERCEIRO = re.compile(r"(?:pag\w+|quit\w+|arc\w+)" + _ESPACO % 40 + r"(?:por|pel[oa]s?)\s+(?:terceir\w+|seguradora|denunciad\w+|"
                      r"tomadora|litisconsort\w+|corre\w*)|terceir\w+" + _ESPACO % 40 +
                      r"(?:pagar\w*|arcar\w*|quitar\w*|responsavel\s+pelo\s+pagamento)")
EXCLUSAO_LIDE = re.compile(r"exclu\w+" + _ESPACO % 50 + r"(?:lide|polo\s+passivo|polo\s+ativo|feito)|"
                           r"exclusao" + _ESPACO % 30 + r"(?:lide|polo|feito)")
ATO_PETICIONANTE = re.compile(r"apresent\w+|interpos\w+|protocol\w+|requer\w+|pleite\w+|peticion\w+")
ATO_DECISORIO = re.compile(r"proferid\w+|prolat\w+|sentenc\w+|acordao|julgou|homolog\w+|\bjulgo\b|\bdecido\b|\bdeclaro\b|"
                           r"extingo|(?:dou|deu)\s+provimento")
MOEDA = r"r\$\s*(\d[\d.]*(?:,\d{2})?)"
VALOR_CONDENACAO = re.compile(r"(?:conden\w*|arbitr\w*)" + _ESPACO % 200 + MOEDA)
VALOR_ACORDO = re.compile(r"(?:acordo|transacao)" + _ESPACO % 200 + MOEDA)
NAO_E_CONDENACAO = re.compile(r"honorari|custas|multa|pericia|sucumb")
GRAU_DO_TRIBUNAL = re.compile(r"acordao|desembargador|relator|turma|camara|sessao\s+de\s+julgamento|segundo\s+grau|2o\s+grau")


def _antes(n, pos, regex, janela):
    """O regex aparece nos `janela` caracteres que antecedem `pos`?"""
    return bool(regex.search(n[max(0, pos - janela):pos]))


# ------------------------------------------------------------------ atos (eventos já filtrados e preparados)

def _rotulo(ev, tipo_evento, data):
    if tipo_evento == "documento":
        base = ev.get("tipo") or "Documento"
        desc = ev.get("descricao")
        if desc and _n(desc) != _n(base):
            base += f" - {desc}"
        if ev.get("doc_id"):
            base += f" (doc. {ev['doc_id']})"
        return f"{base} de {_br(data)}"
    if tipo_evento == "texto_relatorio":
        return f"Texto do relatório anterior ({_br(data)})"
    titulo = " ".join(str(ev.get("titulo") or ev.get("frase") or "movimento").split())
    return f"Movimento de {_br(data)}: {titulo[:80]}"


def _grau_declarado(ev):
    if re.search(r"\btst\b", str(ev.get("grau") or ""), re.I):
        return 3                      # Tribunal Superior do Trabalho: acima do 2º grau
    m = re.search(r"(\d+)", str(ev.get("grau") or ""))
    return int(m.group(1)) if m else 1


def _fontes_do_ato(ev, tipo_evento, avisos, numero):
    """Textos do evento, do mais confiável ao menos: trecho de origem e conteúdo aprovados, arquivo extraído,
    frase e título. Cada fonte é (nome, texto original, texto normalizado)."""
    brutas = [("trecho", ev.get("trecho_origem")), ("conteudo", ev.get("conteudo"))]
    arquivo = ev.get("texto_arquivo")
    if tipo_evento == "documento" and arquivo:
        try:
            with open(arquivo, encoding="utf-8") as f:
                brutas.append(("arquivo", f.read()))
        except OSError:
            avisos.append(_aviso("info", "texto_arquivo_ilegivel", numero,
                                 "O texto extraído de um documento não pôde ser lido; foram usados só o resumo e o trecho."))
    brutas += [("frase", ev.get("frase")), ("titulo", ev.get("titulo")), ("descricao", ev.get("descricao"))]
    fontes = []
    for nome, texto in brutas:
        if isinstance(texto, str) and texto.strip() and not any(texto == f[1] for f in fontes):
            fontes.append((nome, texto, _n(texto)))
    return fontes


def _eh_decisao(ev, tipo_evento):
    if tipo_evento == "texto_relatorio":
        return True
    if tipo_evento == "documento":
        referencia = " ".join(str(ev.get(c) or "") for c in ("tipo", "descricao")).strip() or str(ev.get("titulo") or "")
        return _categoria_do_documento(referencia) in ("decisao", "audiencia")
    return not re.match(r"\s*(juntada|expedi)", str(ev.get("titulo") or ev.get("frase") or ""), re.I)


def _data_do_evento(ev):
    return fch.data(fch.parse_data(ev.get("data")))


def _montar_ato(ev, indice, avisos, numero):
    tipo_evento = ev.get("tipo_evento") or ("documento" if ev.get("tipo") else "movimento")
    fontes = _fontes_do_ato(ev, tipo_evento, avisos, numero)
    grau = _grau_declarado(ev)
    if tipo_evento != "texto_relatorio":  # só tipo/título: o corpo de uma sentença cita acórdãos de outros
        cabecalho = _n(" ".join(str(ev.get(c) or "") for c in ("tipo", "descricao", "titulo")))
    else:
        cabecalho = fontes[0][2] if fontes else ""
    if GRAU_DO_TRIBUNAL.search(cabecalho):
        grau = max(grau, 2)
    data = _data_do_evento(ev)
    return {"ev": ev, "indice": indice, "tipo_evento": tipo_evento, "data": data, "grau": grau, "fontes": fontes,
            "decisao": _eh_decisao(ev, tipo_evento), "documento": _rotulo(ev, tipo_evento, data),
            "do_relatorio": tipo_evento == "texto_relatorio"}


def eventos_do_relatorio(ficha):
    """Frases do texto de andamentos do relatório anterior (linha de base e último texto gravado), uma por data
    ('Em 18/06/2026 ...'), como eventos de tipo `texto_relatorio`: a única fonte de decisões anteriores à
    ferramenta. Devolve lista (vazia se não há texto)."""
    textos = []
    base = ficha.get("linha_de_base") or {}
    gravado = ficha.get("ultimo_texto_gravado") or {}
    for bloco in (base.get("andamentos_texto"), gravado.get("texto")):
        if isinstance(bloco, str) and bloco.strip() and bloco not in textos:
            textos.append(bloco)
    eventos = []
    for texto in textos:
        marcas = [m.start(1) for m in re.finditer(r"(?:^|(?<=[.!?])\s+|(?<=\n))\s*((?:Em\s+)?\d{2}/\d{2}/\d{4})", texto)]
        for i, ini in enumerate(marcas):
            trecho = texto[ini:marcas[i + 1] if i + 1 < len(marcas) else len(texto)].strip()
            achada = re.search(r"\d{2}/\d{2}/\d{4}", trecho)
            eventos.append({"tipo_evento": "texto_relatorio", "status": "aprovado", "numero": ficha.get("numero"),
                            "data": fch.parse_data(achada.group(0)) if achada else None, "titulo": trecho})
    return eventos


def _atos(ficha, eventos, avisos, usar_relatorio):
    numero = ficha.get("numero", "")
    # processo principal e vinculados do tipo recurso; agravo, apenso e afins têm decisão própria e não decidem a causa
    aceitos = {numero} | {v["numero"] for v in ficha.get("vinculados", []) if v.get("tipo") == "recurso"}
    lista = [ev for ev in (eventos or []) if isinstance(ev, dict) and ev.get("status") in STATUS_APROVADOS
             and (not ev.get("numero") or ev["numero"] in aceitos)]
    if usar_relatorio:
        lista += eventos_do_relatorio(ficha)
    atos = [_montar_ato(ev, i, avisos, numero) for i, ev in enumerate(lista)]
    ordem = {"movimento": 0, "texto_relatorio": 1, "documento": 2}
    # cronológico; no mesmo dia, grau mais alto por último e documento depois do movimento (evidência melhor)
    atos.sort(key=lambda a: (a["data"] or datetime.date.min, a["grau"], ordem.get(a["tipo_evento"], 0), a["indice"]))
    return atos


# ------------------------------------------------------------------ leitura do teor de uma decisão

def _classe_do_merito(achado):
    if "parcial" in achado or "em parte" in achado:
        return "Parcialmente procedente"
    return "Improcedente" if achado.startswith("improcedenc") or achado.startswith("improcedent") else "Procedente"


def _merito(n, curto):
    """(resultado, posição, misto) lido das palavras de julgamento do mérito; None se não houver."""
    achados = []
    for regex in ((MERITO_VERBO,) + ((MERITO_SOLTO,) if curto else ())):
        for m in regex.finditer(n):
            pos = m.start(1)
            if INCIDENTAL.search(n[max(0, pos - 80):pos + 80]) or _antes(n, pos, PEDIDO_ANTES, 60):
                continue  # decisão de impugnação/embargos, ou palavra de quem pede (não de quem julga)
            achados.append((pos, _classe_do_merito(m.group(1))))
        if achados:
            break
    if not achados:
        return None
    classes = {c for _, c in achados}
    for m in MERITO_SOLTO.finditer(n):  # a mesma decisão pode julgar duas coisas (ação e reconvenção): só para avisar
        pos = m.start(1)
        if not (INCIDENTAL.search(n[max(0, pos - 80):pos + 80]) or _antes(n, pos, PEDIDO_ANTES, 60)):
            classes.add(_classe_do_merito(m.group(1)))
    if "Parcialmente procedente" in classes:
        return "Parcialmente procedente", min(p for p, c in achados if c == "Parcialmente procedente"), False
    achados.sort()
    return achados[0][1], achados[0][0], len(classes) > 1


def _desfecho(n, curto):
    """Primeiro desfecho reconhecido em `n`: (resultado, regra, início, fim, misto) ou None."""
    for regex, resultado, regra in ((ACORDO, "Acordo", "resultado_acordo"),
                                    (DESISTENCIA, "Arquivado / desistência", "resultado_desistencia"),
                                    (INCOMPETENCIA, "Incompetência declarada", "resultado_incompetencia"),
                                    (EXTINCAO, "Extinto sem resolução de mérito", "resultado_extincao")):
        for m in regex.finditer(n):
            if not _antes(n, m.start(), NEGA_ANTES, 40):
                return resultado, regra, m.start(), m.end(), False
    achado = _merito(n, curto)
    if achado:
        resultado, pos, misto = achado
        regra = {"Procedente": "resultado_procedente", "Parcialmente procedente": "resultado_parcial",
                 "Improcedente": "resultado_improcedente"}[resultado]
        return resultado, regra, pos, pos + 12, misto
    return None


def _ler_decisao(ato):
    """Classifica o ato: {"tipo": "resultado"|"mantem"|"reforma_indefinida"|"arquivamento", ...} ou None."""
    if not ato["decisao"]:
        return None
    for nome, original, n in ato["fontes"]:
        curto = len(original) <= LIMITE_TEXTO_CURTO
        if ATO_PETICIONANTE.search(n) and not ATO_DECISORIO.search(n):
            continue
        mantem, prov = MANTEM.search(n), PROVIMENTO.search(n)
        if mantem and not (prov and prov.start() < mantem.start()):
            ressalva_agravo = SO_AGRAVO.search(n) and not DA_SENTENCA.search(n)
            if ressalva_agravo or _antes(n, mantem.start(), INCIDENTAL, 60) or INCIDENTAL.search(n[mantem.start():mantem.start() + 60]):
                continue
            return {"tipo": "mantem", "trecho": _trecho(original, mantem.start(), mantem.end()), "fonte": nome, "grau": 2}
        if prov:
            if INCIDENTAL.search(n[max(0, prov.start() - 60):prov.end() + 60]) or (
                    SO_AGRAVO.search(n) and not DA_SENTENCA.search(n)):
                continue
            achado = _desfecho(n[prov.start():], curto)
            if achado:
                resultado, regra, ini, fim, misto = achado
                return {"tipo": "resultado", "resultado": resultado, "regra": regra, "misto": misto, "grau": 2,
                        "trecho": _trecho(original, prov.start() + ini, prov.start() + fim), "fonte": nome}
            return {"tipo": "reforma_indefinida", "trecho": _trecho(original, prov.start(), prov.end()), "fonte": nome,
                    "grau": 2}
        achado = _desfecho(n, curto)
        if achado:
            resultado, regra, ini, fim, misto = achado
            return {"tipo": "resultado", "resultado": resultado, "regra": regra, "misto": misto, "grau": ato["grau"],
                    "trecho": _trecho(original, ini, fim), "fonte": nome}
        m = ARQUIVAMENTO.search(n)
        if m and not re.search(r"provisori|sobrest", n):
            return {"tipo": "arquivamento", "trecho": _trecho(original, m.start(), m.end()), "fonte": nome, "grau": ato["grau"]}
    return None


def _valores(ato, regex, descartar=None):
    """Valores em reais (Decimal) lidos do ato pelo regex ancorado em verbo; usa a primeira fonte que tiver."""
    for _, original, n in ato["fontes"]:
        achados = []
        for m in regex.finditer(n):
            if descartar and descartar.search(m.group(0)):
                continue
            valor = fch.dinheiro(fch.parse_dinheiro(m.group(1).rstrip(".")))
            if valor is not None:
                achados.append((valor, _trecho(original, m.start(), m.end())))
        if achados:
            return achados
    return []


def _texto_do_ato(ato):
    return " ".join(n for _, _, n in ato["fontes"])


# ------------------------------------------------------------------ percurso das decisões

def _decisao_corrente(atos, avisos, numero):
    """Estado final do processo depois de percorrer as decisões em ordem. Devolve dict com `resultado`,
    `ato` (de onde vem o resultado), `grau`, `regra`, `trecho`, `misto`, `reformou_de`, `confirmado_por`,
    `indefinido`; ou None quando não há decisão. Arquivamento sem decisão só vale se nada mais foi achado."""
    estado, fraco = None, None
    for ato in atos:
        leitura = _ler_decisao(ato)
        if leitura is None:
            continue
        tipo = leitura["tipo"]
        if tipo == "arquivamento":
            fraco = {"resultado": "Arquivado / desistência", "ato": ato, "grau": ato["grau"], "regra": "resultado_arquivamento",
                     "trecho": leitura["trecho"], "misto": False, "reformou_de": None, "confirmado_por": None,
                     "indefinido": False, "fraco": True, "base": ato}
        elif tipo == "resultado":
            anterior = estado["resultado"] if estado and estado.get("resultado") else None
            reformou = anterior if anterior and anterior != leitura["resultado"] and leitura["grau"] >= 2 else None
            estado = {"resultado": leitura["resultado"], "ato": ato, "base": ato, "grau": max(ato["grau"], leitura["grau"]),
                      "regra": leitura["regra"], "trecho": leitura["trecho"], "misto": leitura["misto"],
                      "reformou_de": reformou, "confirmado_por": None, "indefinido": False, "fraco": False}
        elif tipo == "mantem":
            if estado and estado.get("resultado"):
                estado["confirmado_por"] = {"ato": ato, "trecho": leitura["trecho"]}
                estado["grau"] = max(estado["grau"], 2)
            elif estado is None:
                avisos.append(_aviso("atencao", "acordao_sem_sentenca", numero,
                                     "Há acórdão mantendo a decisão anterior, mas a decisão anterior não está entre os eventos "
                                     "aprovados: resultado não sugerido."))
        else:  # reforma_indefinida
            estado = {"resultado": None, "ato": ato, "grau": 2, "regra": None, "trecho": leitura["trecho"], "misto": False,
                      "reformou_de": None, "confirmado_por": None, "indefinido": True, "fraco": False}
            avisos.append(_aviso("atencao", "acordao_reforma_sem_resultado", numero,
                                 f"O acórdão de {_br(ato['data'])} deu provimento ao recurso sem dizer o resultado do processo: "
                                 "resultado, probabilidade e valores não foram sugeridos; conferir o acórdão."))
    return estado or fraco


def _ha_transito(atos, ficha, desde):
    """Trânsito em julgado depois (ou no dia) da decisão: evento, data lançada na ficha ou momento atual."""
    if fch.obter(ficha, "data_transito"):
        return True
    momento = _momento_base(ficha)
    if momento == "TRÂNSITO EM JULGADO" or taxonomia.categoria_do_momento(momento) in ("execução", "encerrado"):
        return True
    for ato in atos:
        if desde and ato["data"] and ato["data"] < desde:
            continue
        texto = _texto_do_ato(ato)
        if TRANSITO.search(texto) and not SEM_TRANSITO.search(texto):
            return True
    return False


def _ha_recurso(atos, ficha, decisao):
    momento = _momento_base(ficha)
    if taxonomia.categoria_do_momento(momento) == "recurso":
        return True
    desde = decisao["ato"]["data"]
    for ato in atos:
        if ato is decisao["ato"]:
            continue
        if desde and (not ato["data"] or ato["data"] <= desde):
            continue
        if RECURSO.search(_texto_do_ato(ato)):
            return True
    return False


def _momento_base(ficha):
    """Momento atual sem o qualificador entre parênteses."""
    momento = fch.obter(ficha, "momento_atual") or ""
    return re.sub(r"\s*\(.*\)\s*$", "", momento).strip().upper()


def _ressalva_de_recurso(atos, ficha, decisao):
    """'Sujeita a recurso' para decisão de mérito de 1º grau sem trânsito em julgado."""
    if decisao["resultado"] not in MERITO or decisao["grau"] >= 2 or decisao.get("confirmado_por"):
        return None
    desde = decisao["ato"]["data"]
    em_recurso = _ha_recurso(atos, ficha, decisao)
    if _ha_transito(atos, ficha, desde) and not taxonomia.categoria_do_momento(_momento_base(ficha)) == "recurso":
        return None
    if em_recurso:
        return "Sujeita a recurso: há recurso pendente contra a decisão de 1º grau."
    return "Sujeita a recurso: decisão de 1º grau sem trânsito em julgado registrado."


# ------------------------------------------------------------------ ficha

def _encerrado(ficha, resultado):
    if fch.obter(ficha, "situacao") == "Encerrado" or ficha.get("ativo") is False:
        return True
    if taxonomia.momento_ativo(_momento_base(ficha)) is False:
        return True
    return resultado in ENCERRAM


def _dinheiro_da_ficha(ficha, campo):
    return fch.dinheiro(fch.obter(ficha, campo))


def _dinheiro_txt(v):
    return f"{v.quantize(Decimal('0.01')):.2f}"


def _evidencia_da_ficha(ficha, campo):
    rotulo = fch.CAMPOS[campo][0]
    return {"documento": f"Ficha: {rotulo} ({fch.origem(ficha, campo) or 'sem origem'})",
            "trecho": fch.dinheiro_br(fch.obter(ficha, campo))}


def _evidencia_da_decisao(decisao):
    ato = decisao["ato"]
    documento, trecho = ato["documento"], decisao["trecho"]
    if decisao.get("confirmado_por"):
        conf = decisao["confirmado_por"]
        documento, trecho = f"{conf['ato']['documento']}; confirma {ato['documento']}", conf["trecho"]
    return {"documento": documento, "trecho": trecho}


def _ressalvas_da_decisao(decisao, atos, ficha):
    r = []
    if decisao["misto"]:
        r.append("O texto cita procedência e improcedência: conferir o resultado.")
    if decisao["ato"]["do_relatorio"]:
        r.append("Lido do texto do relatório anterior, não de documento aprovado.")
    if decisao.get("reformou_de"):
        r.append(f"Decisão do tribunal reformou a de 1º grau (antes: {decisao['reformou_de']}).")
    if decisao.get("fraco"):
        r.append("Arquivamento sem decisão de mérito identificada: conferir o motivo.")
    recurso = _ressalva_de_recurso(atos, ficha, decisao)
    if recurso:
        r.append(recurso)
    return r


# ------------------------------------------------------------------ campos

def _entrada(valor, regra, evidencia, ressalvas):
    vistas = []
    for r in ressalvas:
        if r and r not in vistas:
            vistas.append(r)
    return {"valor": valor, "regra": regra, "evidencia": evidencia, "ressalvas": vistas}


def _sem_evidencia():
    return {"documento": "", "trecho": ""}


def _resultado(decisao, atos, ficha):
    if decisao is None or decisao.get("indefinido"):
        return None
    return _entrada(decisao["resultado"], decisao["regra"] if not decisao.get("confirmado_por") else "resultado_mantido",
                    _evidencia_da_decisao(decisao), _ressalvas_da_decisao(decisao, atos, ficha))


def _probabilidade(decisao, atos, ficha, avisos, numero):
    if decisao is not None and decisao.get("indefinido"):
        return None
    if decisao is None:
        if _encerrado(ficha, None):
            avisos.append(_aviso("atencao", "encerrado_sem_decisao", numero,
                                 "Processo encerrado sem decisão achada nos eventos aprovados: probabilidade não sugerida."))
            return None
        return _entrada("Possível", "prob_sem_decisao", _sem_evidencia(), ["Sem decisão de mérito nos eventos aprovados."])
    resultado = decisao["resultado"]
    if resultado in SEM_PROBABILIDADE or decisao.get("fraco"):
        avisos.append(_aviso("info", "sem_probabilidade", numero,
                             f"Resultado '{resultado}': a probabilidade fica vazia (processo sem julgamento de mérito)."))
        return None
    valor, regra = {"Procedente": ("Provável", "prob_procedencia"), "Parcialmente procedente": ("Provável", "prob_parcial"),
                    "Improcedente": ("Remota", "prob_improcedencia")}[resultado]
    return _entrada(valor, regra, _evidencia_da_decisao(decisao), _ressalvas_da_decisao(decisao, atos, ficha))


def _valor_estimado(decisao, atos, ficha, avisos, numero):
    """Devolve (entrada ou None, base_incerta). `base_incerta`: o valor é o da causa por falta de valor na decisão."""
    causa = _dinheiro_da_ficha(ficha, "valor_causa")

    def da_causa(regra, ressalvas, incerta):
        if causa is None:
            avisos.append(_aviso("atencao", "valor_causa_ausente", numero,
                                 "Valor da causa não informado: valor estimado não sugerido."))
            return None, incerta
        return _entrada(_dinheiro_txt(causa), regra, _evidencia_da_ficha(ficha, "valor_causa"), ressalvas), incerta

    if decisao is not None and decisao.get("indefinido"):
        return None, True
    if decisao is None or decisao.get("fraco"):
        return da_causa("estimado_causa", [], False)
    resultado, ressalvas = decisao["resultado"], _ressalvas_da_decisao(decisao, atos, ficha)
    if resultado in ("Improcedente", "Extinto sem resolução de mérito", "Arquivado / desistência"):
        if resultado != "Improcedente":
            ressalvas.append("Extinção sem julgamento de mérito: a ação pode ser proposta de novo.")
        return _entrada("0.00", "estimado_zero", _evidencia_da_decisao(decisao), ressalvas), False
    if resultado == "Incompetência declarada":
        return da_causa("estimado_causa_sem_valor", ressalvas + ["Incompetência declarada: o processo segue em outro juízo."], True)
    if resultado == "Acordo":
        valor, evidencia = _dinheiro_da_ficha(ficha, "valor_acordo"), None
        if valor is not None:
            evidencia = _evidencia_da_ficha(ficha, "valor_acordo")
        else:
            lidos = _valores(decisao["ato"], VALOR_ACORDO)
            for ato in atos:  # o valor às vezes está na petição ou na ata, não na sentença homologatória
                if lidos or ato is decisao["ato"] or not re.search(r"acordo|transacao", _texto_do_ato(ato)):
                    continue
                lidos = _valores(ato, VALOR_ACORDO)
            unicos = {v for v, _ in lidos}
            if len(unicos) == 1:
                valor = unicos.pop()
                evidencia = {"documento": decisao["ato"]["documento"], "trecho": lidos[0][1]}
            elif len(unicos) > 1:
                ressalvas.append("O texto cita mais de um valor para o acordo: valor não definido.")
        if valor is None:
            return da_causa("estimado_causa_sem_valor", ressalvas + ["Acordo sem valor lançado: mantido o valor da causa."], True)
        return _entrada(_dinheiro_txt(valor), "estimado_acordo", evidencia, ressalvas), False
    # Procedente ou Parcialmente procedente: valor arbitrado (ficha) ou valor da condenação lido da decisão
    lidos = _valores(decisao["ato"], VALOR_CONDENACAO, NAO_E_CONDENACAO)
    if not lidos and decisao["base"] is not decisao["ato"]:  # acórdão que manteve: o valor está na sentença
        lidos = _valores(decisao["base"], VALOR_CONDENACAO, NAO_E_CONDENACAO)
    unicos = {v for v, _ in lidos}
    arbitrado = _dinheiro_da_ficha(ficha, "valor_arbitrado")
    if arbitrado is not None:
        if len(unicos) == 1 and abs(next(iter(unicos)) - arbitrado) > TOLERANCIA:
            ressalvas.append(f"O valor da ficha difere do valor lido na decisão ({fch.dinheiro_br(next(iter(unicos)))}).")
        if decisao.get("reformou_de"):
            ressalvas.append("Acórdão reformou a decisão: conferir se o valor arbitrado da ficha ainda vale.")
        return _entrada(_dinheiro_txt(arbitrado), "estimado_arbitrado", _evidencia_da_ficha(ficha, "valor_arbitrado"),
                        ressalvas), False
    if len(unicos) == 1:
        return _entrada(_dinheiro_txt(next(iter(unicos))), "estimado_condenacao",
                        {"documento": decisao["ato"]["documento"], "trecho": lidos[0][1]}, ressalvas), False
    motivo = ("A decisão cita mais de um valor de condenação: valor não definido; mantido o valor da causa."
              if len(unicos) > 1 else "Valor da condenação não identificado na decisão: mantido o valor da causa.")
    return da_causa("estimado_causa_sem_valor", ressalvas + [motivo], True)


def _nao_conta(ficha, decisao, atos, estimado_incerto):
    """Motivos (texto curto) pelos quais o processo encerrado NÃO conta como economia."""
    motivos = []
    polo = fch.obter(ficha, "polo_cliente")
    if polo == "ativo":
        motivos.append("Cliente é autor: não conta como economia.")
    resultado = decisao["resultado"] if decisao else None
    if resultado == "Acordo":
        textos = [_texto_do_ato(a) for a in atos if re.search(r"acordo|transacao", _texto_do_ato(a))]
        obs = _n(fch.obter(ficha, "observacoes") or "")
        if re.search("acordo", obs):
            textos.append(obs)
        if any(TERCEIRO.search(t) for t in textos):
            motivos.append("Acordo pago por terceiro: não conta como economia.")
        if estimado_incerto:
            motivos.append("Acordo sem valor lançado: não conta como economia.")
    elif resultado == "Incompetência declarada":
        motivos.append("Incompetência declarada: o processo segue em outro juízo; não conta como economia.")
    elif estimado_incerto:
        motivos.append("Valor estimado sem base na decisão: economia não calculada.")
    textos = [_texto_do_ato(a) for a in atos if a["decisao"]] + [_n(fch.obter(ficha, "observacoes") or "")]
    if any(not _antes(t, m.start(), NEGA_ANTES, 60) for t in textos for m in EXCLUSAO_LIDE.finditer(t)):
        motivos.append("Exclusão da lide: não conta como economia.")
    return motivos


def _valor_economizado(decisao, atos, ficha, estimado, estimado_incerto, avisos, numero):
    if decisao is not None and decisao.get("indefinido"):
        return None
    resultado = decisao["resultado"] if decisao else None
    if not _encerrado(ficha, resultado):
        return None
    motivos = _nao_conta(ficha, decisao, atos, estimado_incerto)
    if motivos:
        return _entrada(None, "economia_nao_conta", estimado["evidencia"] if estimado else _sem_evidencia(), motivos)
    causa = _dinheiro_da_ficha(ficha, "valor_causa")
    if causa is None:
        avisos.append(_aviso("atencao", "valor_causa_ausente", numero, "Valor da causa não informado: economia não sugerida."))
        return None
    if estimado is None:
        return None
    diferenca = causa - fch.dinheiro(estimado["valor"])
    ressalvas = list(estimado["ressalvas"])
    if fch.obter(ficha, "polo_cliente") is None:
        ressalvas.append("Polo do cliente não informado: conferir se o cliente é autor (autor não conta como economia).")
    if diferenca < 0:
        ressalvas.append("Valor estimado acima do valor da causa: a diferença é negativa.")
    return _entrada(_dinheiro_txt(diferenca), "economia_causa_menos_estimado", estimado["evidencia"], ressalvas)


# ------------------------------------------------------------------ API

def _analisar(ficha, eventos, usar_relatorio=True):
    """Todas as sugestões calculadas, SEM descartar campo humano (quem filtra é `sugerir`; `concordancia` precisa
    do cálculo completo para compará-lo com o que a pessoa lançou). Devolve (campos, avisos)."""
    avisos, numero = [], ficha.get("numero", "")
    atos = _atos(ficha, eventos, avisos, usar_relatorio)
    decisao = _decisao_corrente(atos, avisos, numero)
    campos = {}
    resultado = _resultado(decisao, atos, ficha)
    if resultado:
        campos["resultado"] = resultado
    probabilidade = _probabilidade(decisao, atos, ficha, avisos, numero)
    if probabilidade:
        campos["probabilidade"] = probabilidade
    estimado, incerto = _valor_estimado(decisao, atos, ficha, avisos, numero)
    if estimado:
        campos["valor_estimado"] = estimado
    economizado = _valor_economizado(decisao, atos, ficha, estimado, incerto, avisos, numero)
    if economizado:
        campos["valor_economizado"] = economizado
    return campos, avisos


def _vale_sugerir(ficha, campo):
    """Só sugere onde não há valor de origem maior que `sugerido` (humano, coletado, migrado, derivado)."""
    origem = fch.origem(ficha, campo)
    return origem is None or origem == "sugerido"


def sugerir_com_avisos(ficha, eventos, usar_relatorio=True):
    """(sugestões, avisos): as sugestões de `sugerir` e os avisos estruturados (CONTRATOS §0) do que não foi
    sugerido e por quê (ex.: `acordao_reforma_sem_resultado`, `encerrado_sem_decisao`, `valor_causa_ausente`)."""
    campos, avisos = _analisar(ficha, eventos, usar_relatorio)
    return {c: v for c, v in campos.items() if _vale_sugerir(ficha, c)}, avisos


def sugerir(ficha, eventos, usar_relatorio=True):
    """{campo: {"valor", "regra", "evidencia": {"documento", "trecho"}, "ressalvas": [str]}} para resultado,
    probabilidade, valor_estimado e valor_economizado. Não altera a ficha. Campo de origem humana (ou outra
    maior que `sugerido`) não aparece. `valor` None (só em valor_economizado) quer dizer: caso que NÃO conta
    como economia, com o motivo nas ressalvas; `aplicar` ignora. `usar_relatorio=False` ignora o texto do
    relatório anterior e usa só os eventos."""
    return sugerir_com_avisos(ficha, eventos, usar_relatorio)[0]


def aplicar(ficha, sugestoes):
    """Grava as sugestões na ficha com origem `sugerido` (evidência, regra e ressalvas vão no campo de evidência).
    Nunca sobrescreve origem maior; atualiza sugestão anterior. Devolve a lista de campos gravados."""
    gravados = []
    for campo, s in (sugestoes or {}).items():
        if campo not in CAMPOS_SUGERIDOS or s.get("valor") in (None, ""):
            continue
        ev = s.get("evidencia") or {}
        texto = f"[{s.get('regra', '')}] {ev.get('documento', '')}"
        if ev.get("trecho"):
            texto += f": «{ev['trecho']}»"
        if s.get("ressalvas"):
            texto += " | Ressalvas: " + "; ".join(s["ressalvas"])
        antiga = fch.origem(ficha, campo) == "sugerido"
        if fch.definir(ficha, campo, s["valor"], "sugerido", evidencia=texto, forcar=antiga):
            gravados.append(campo)
    return gravados


def _mesmo_valor(campo, humano, sugerido):
    if fch.CAMPOS[campo][2] == "dinheiro":
        a, b = fch.dinheiro(humano), fch.dinheiro(sugerido)
        return a is not None and b is not None and abs(a - b) <= TOLERANCIA
    return str(humano) == str(sugerido)


def concordancia(fichas_migradas, eventos=None):
    """Teste retroativo: compara a sugestão com o que uma pessoa lançou (origem `humano`) nos campos de julgamento
    de relatórios migrados, só onde há valor humano. `eventos` (opcional): lista de eventos aprovados ou
    {número: [eventos]}; sem ele vale o texto de andamentos do relatório (linha de base), a única fonte dos migrados.

    {campo: {"concordam": n, "total": n, "casos_divergentes": [numero], "por_regra": {regra: {"concordam", "total"}}}}
    Sugestão ausente, ou `valor` None, contra valor humano conta como divergência (a regra não reproduziu o
    lançamento). Dinheiro compara com tolerância de um centavo."""
    por_numero = {}
    if isinstance(eventos, dict):
        por_numero = eventos
    elif eventos:
        for ev in eventos:
            por_numero.setdefault(ev.get("numero"), []).append(ev)
    saida = {c: {"concordam": 0, "total": 0, "casos_divergentes": [], "por_regra": {}} for c in CAMPOS_SUGERIDOS}
    for f in fichas_migradas:
        campos, _ = _analisar(f, por_numero.get(f.get("numero"), []))
        for campo in CAMPOS_SUGERIDOS:
            if fch.origem(f, campo) != "humano":
                continue
            sugestao = campos.get(campo)
            valor = sugestao["valor"] if sugestao else None
            regra = sugestao["regra"] if sugestao else "sem_sugestao"
            igual = valor is not None and _mesmo_valor(campo, fch.obter(f, campo), valor)
            bloco = saida[campo]
            bloco["total"] += 1
            r = bloco["por_regra"].setdefault(regra, {"concordam": 0, "total": 0})
            r["total"] += 1
            if igual:
                bloco["concordam"] += 1
                r["concordam"] += 1
            else:
                bloco["casos_divergentes"].append(f.get("numero"))
    return saida
