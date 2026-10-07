"""Triagem da revisão: dá a cada evento um nível de risco (verde, amarelo, vermelho) por
REGRAS, para que 200 processos (centenas de linhas por ciclo) sejam revisados por exceção.
Não fala com tribunal, não usa IA e não tem tela: é só a lógica; as telas estão em
painel/revisao_lote.py (lista, filtros e aprovação em lote) e painel/processo.py (visão por processo).

    triagem.classificar(evento, ficha=None) -> {"nivel": "verde|amarelo|vermelho", "motivos": [texto, ...]}

VERMELHO (sempre olho humano; nunca entra em lote)
    desfavoravel         efeito desfavorável ao cliente (campo `efeito` ou alerta da IA)
    prazo                prazo no campo `prazo` ou citado no texto ("prazo", "15 dias")
    audiencia            audiência no campo `audiencia` ou citada no texto
    valor                qualquer valor monetário (R$ 1.000,00; 1.000,00; "mil reais") na frase, conteúdo,
                         prazo, audiência ou trecho de origem
    mudanca_resultado    texto de julgamento (procedente, improcedente, homologação, extinção, trânsito em
                         julgado, condenação, provimento...) ou campo `resultado` diferente do da ficha
    decisao_de_merito    documento do tipo sentença ou acórdão, e andamento "publicada sentença/acórdão"
                         (regra conservadora: a decisão em si decide o rumo do processo)
    trecho_nao_confere   alerta da IA de que o trecho citado não está no documento, ou, quando o texto do
                         documento está no disco (`texto_arquivo`), conferência própria do trecho
AMARELO (revisão normal, mas nunca em lote)
    alerta               qualquer alerta já gravado no evento por regra existente (resumir.conferir,
                         conferir_contexto, "andamento sem tradução", "sem resumo automático"...)
    autoria_nao_identificada, sem_traducao, sem_frase, sem_cliente, polo_nao_informado (só documento),
    efeito_incerto (só documento), sem_trecho (resumo da IA sem trecho de origem),
    fora_da_carteira (só em classificar_lista, que sabe quais processos existem)
VERDE
    o resto: sem alerta e sem nenhum dos motivos acima.

Observações das regras
    - Elas são propositalmente "largas": é melhor mandar um evento tranquilo para olho humano do que
      deixar passar um relevante. Falsos positivos conhecidos: "prazo" e "dias" em frases de rotina
      ("Terminou o prazo de X" é vermelho de propósito), "homologou os cálculos" (homolog...) e a
      palavra "condenação" em texto que só descreve o pedido.
    - O trecho só é conferido pelo disco quando `texto_arquivo` existe; sem o arquivo vale o alerta
      que a IA/`resumir.conferir` já gravou (ausência de alerta = não conferido de novo).
    - `classificar_detalhado` devolve também os códigos estáveis acima (usados nos testes e nos filtros).

APROVAÇÃO EM LOTE (só verdes, com amostragem obrigatória)
    triagem.preparar_lote(eventos, fichas, filtros=None, pct=None, semente=None) -> dict
    triagem.aplicar_lote(eventos, fichas, aprovador, filtros=None, pct=None, semente=None, agora=None) -> dict

    - Só entra em lote evento `rascunho`, de nível verde, com frase, que ainda não tenha sido sorteado
      para a amostra de um lote anterior e que passe pelo filtro. Cada candidato é reclassificado no
      momento de aprovar (a "regra sempre humano" vale mesmo que a tela mande um id errado).
    - Amostra obrigatória: `pct` por cento dos verdes (padrão 10, arredondando para cima, no mínimo 1)
      fica de fora e vai para revisão manual. A escolha é reprodutável: ordena os ids pelo
      SHA-256 de "semente|id"; mesmo conjunto + mesma semente = mesma amostra, em qualquer ordem. O
      sorteado recebe `evento["amostra_lote"] = id do lote` e nunca mais entra em lote: precisa de
      olho humano.
    - Cada evento aprovado em lote ganha `aprovado_por`, `aprovado_em`, `lote` (id do lote) e `triagem`
      ({"nivel", "motivos"}); o lote fica em data/lotes.json (quem, quando, filtro, amostra, ids).

Configuração (config.json, tudo opcional)
    "triagem": {"amostragem_pct": 10, "semente": "triagem-v1", "sugerir_a_partir_de": 20}
"""
import datetime
import hashlib
import math
import re
from pathlib import Path

import comum
import ficha as fch
import relatorio
import resumir
from comum import normalizar

NIVEIS = ("verde", "amarelo", "vermelho")
RISCO = {"vermelho": 0, "amarelo": 1, "verde": 2}      # ordem de apresentação: mais arriscado primeiro
AMOSTRAGEM_PADRAO = 10.0
SEMENTE_PADRAO = "triagem-v1"
# o que a revisão em lote jamais pode aprovar, em qualquer nível (rede de segurança dupla)
SEMPRE_HUMANO = ("desfavoravel", "mudanca_resultado", "decisao_de_merito", "valor", "audiencia", "prazo",
                 "trecho_nao_confere")

_VALOR = re.compile(r"r\$\s*\d|\b\d{1,3}(?:\.\d{3})*,\d{2}\b|\d\s*reais\b|\b(?:mil|milhao|milhoes)\s+(?:de\s+)?reais\b")
_PRAZO = re.compile(r"\bprazo\b|\b\d+\s+dias\b|\bdias\s+uteis\b")
_AUDIENCIA = re.compile(r"\baudiencia\b")
_RESULTADO = re.compile(
    r"\bprocedente\b|\bimprocedente\b|\bprocedencia\b|\bimprocedencia\b|\bhomolog\w+|\bextin\w+|"
    r"transit\w+ em julgado|\bcondena\w*|\bprovimento\b|\bimprovid[oa]\b|\bprovid[oa]\b|\bdesistencia\b|"
    r"\bincompetencia\b")
_DECISAO_DOC = re.compile(r"\bsentenca\b|\bacordao\b")
_DECISAO_MOV = re.compile(r"\bpublicad[oa]\s+(?:a\s+)?(?:sentenca|acordao)\b|\bproferid[oa]\s+(?:a\s+)?(?:sentenca|acordao)\b")


# ------------------------------------------------------------------ configuração

def configuracao():
    """Bloco "triagem" do config.json, com os padrões aplicados."""
    try:
        bloco = comum.config().get("triagem") or {}
    except Exception:
        bloco = {}
    try:
        pct = float(bloco.get("amostragem_pct", AMOSTRAGEM_PADRAO))
    except (TypeError, ValueError):
        pct = AMOSTRAGEM_PADRAO
    try:
        a_partir = int(bloco.get("sugerir_a_partir_de", 20))
    except (TypeError, ValueError):
        a_partir = 20
    return {"amostragem_pct": min(max(pct, 0.0), 100.0), "semente": str(bloco.get("semente") or SEMENTE_PADRAO),
            "sugerir_a_partir_de": a_partir}


# ------------------------------------------------------------------ classificação

def _txt(ev, *campos):
    return normalizar(" ".join(str(ev.get(c) or "") for c in campos))


def _ficha_valor(ficha, campo):
    if not ficha:
        return None
    return fch.obter(ficha, campo)


def _trecho_nao_confere(ev):
    """True só quando dá para conferir (texto do documento no disco) e o trecho não está lá."""
    trecho, arq = (ev.get("trecho_origem") or "").strip(), ev.get("texto_arquivo")
    if not trecho or not arq:
        return False
    try:
        texto = Path(arq).read_text(encoding="utf-8")
    except OSError:
        return False
    return not resumir.trecho_confere(trecho, texto)


def classificar_detalhado(evento, ficha=None, *, exigir_ficha=False):
    """Como classificar(), mais a lista de códigos estáveis em "codigos" (vermelhos e amarelos)."""
    vermelho, amarelo = [], []          # [(codigo, motivo)]
    alertas = [a for a in (evento.get("alertas") or []) if a]
    documento = evento.get("tipo_evento") == "documento"
    corpo = _txt(evento, "frase", "conteudo")
    tudo = _txt(evento, "frase", "conteudo", "prazo", "audiencia", "trecho_origem")

    # ---- vermelho
    if evento.get("efeito") == "desfavoravel" or any("desfavor" in normalizar(a) for a in alertas):
        vermelho.append(("desfavoravel", "Efeito desfavorável ao cliente."))
    if (evento.get("prazo") or "").strip() or _PRAZO.search(corpo):
        vermelho.append(("prazo", "Há prazo."))
    if (evento.get("audiencia") or "").strip() or _AUDIENCIA.search(corpo):
        vermelho.append(("audiencia", "Há audiência."))
    if _VALOR.search(tudo) or evento.get("valor") or evento.get("valores"):
        vermelho.append(("valor", "Há valor em dinheiro."))
    resultado_ev = (evento.get("resultado") or "").strip()
    if _RESULTADO.search(corpo) or (resultado_ev and resultado_ev != (_ficha_valor(ficha, "resultado") or "")):
        vermelho.append(("mudanca_resultado", "Pode mudar o resultado do processo."))
    decisao = (documento and _DECISAO_DOC.search(_txt(evento, "tipo", "titulo"))) or \
              (not documento and _DECISAO_MOV.search(_txt(evento, "frase", "titulo")))
    if decisao:
        vermelho.append(("decisao_de_merito", "Sentença ou acórdão: sempre conferir."))
    if any("trecho citado" in normalizar(a) and "nao foi encontrado" in normalizar(a) for a in alertas) \
            or _trecho_nao_confere(evento):
        vermelho.append(("trecho_nao_confere", "O trecho de origem não confere com o documento."))

    # ---- amarelo
    ja_dito = [normalizar(a) for a in alertas]
    for a in alertas:
        n = normalizar(a)
        if "desfavor" in n or ("trecho citado" in n and "nao foi encontrado" in n):
            continue                     # já virou motivo vermelho
        amarelo.append(("alerta", a))
    if evento.get("autoria") == "outro" and not any("autoria nao identificada" in a for a in ja_dito):
        amarelo.append(("autoria_nao_identificada", "Autoria não identificada: confirmar quem apresentou o documento."))
    frase = (evento.get("frase") or "").strip()
    if not frase:
        amarelo.append(("sem_frase", "Sem frase para o relatório."))
    elif (not documento and evento.get("tipo_evento") == "movimento" and frase == (evento.get("titulo") or "").strip()
          and not any("sem traducao" in a for a in ja_dito)):
        amarelo.append(("sem_traducao", "Andamento sem tradução cadastrada."))
    if not (evento.get("cliente") or _ficha_valor(ficha, "cliente")):
        amarelo.append(("sem_cliente", "Processo sem cliente."))
    polo = evento.get("polo_cliente") or _ficha_valor(ficha, "polo_cliente")
    if documento and polo not in ("ativo", "passivo") and not any("polo do cliente nao informado" in a for a in ja_dito):
        amarelo.append(("polo_nao_informado", "Polo do cliente não informado."))
    if documento and evento.get("efeito") == "incerto":
        amarelo.append(("efeito_incerto", "A IA não soube dizer o efeito para o cliente."))
    if documento and (evento.get("conteudo") or "").strip() and not (evento.get("trecho_origem") or "").strip():
        amarelo.append(("sem_trecho", "Resumo sem trecho de origem."))
    if exigir_ficha and ficha is None:
        amarelo.append(("fora_da_carteira", "O processo não está na carteira."))

    nivel = "vermelho" if vermelho else "amarelo" if amarelo else "verde"
    motivos = [m for _, m in vermelho] + [m for _, m in amarelo]
    codigos = [c for c, _ in vermelho] + [c for c, _ in amarelo]
    return {"nivel": nivel, "motivos": motivos, "codigos": codigos}


def classificar(evento, ficha=None):
    """{"nivel": "verde|amarelo|vermelho", "motivos": [...]} (regras no cabeçalho do módulo)."""
    r = classificar_detalhado(evento, ficha)
    return {"nivel": r["nivel"], "motivos": r["motivos"]}


def exige_humano(evento, ficha=None):
    """Motivos "sempre humano" (desfavorável, resultado, valor, audiência, prazo...): lista vazia = pode ir em lote."""
    r = classificar_detalhado(evento, ficha)
    return [m for c, m in zip(r["codigos"], r["motivos"]) if c in SEMPRE_HUMANO]


# ------------------------------------------------------------------ lista, filtros e contagem

def indice_de_fichas(fichas):
    """{número: ficha}, incluindo os números vinculados (o relatório trata o conjunto como uma linha)."""
    indice = {}
    for f in fichas:
        for n in [f.get("numero"), *[v.get("numero") for v in f.get("vinculados", [])]]:
            if n:
                indice.setdefault(n, f)
    return indice


def classificar_lista(eventos, fichas, status=("rascunho",)):
    """[{"ev", "ficha", "nivel", "motivos", "codigos"}] só dos eventos nos `status` pedidos (None = todos)."""
    indice = indice_de_fichas(fichas)
    itens = []
    for ev in eventos:
        if status is not None and ev.get("status") not in status:
            continue
        f = indice.get(ev.get("numero"))
        itens.append({"ev": ev, "ficha": f, **classificar_detalhado(ev, f, exigir_ficha=True)})
    return itens


def ordenar_por_risco(itens):
    """Vermelho, amarelo, verde; dentro do nível, o mais recente primeiro, depois por número."""
    def chave(i):
        try:
            data = relatorio.ordem(i["ev"])[0].timestamp()
        except Exception:               # evento sem data legível: vai para o fim do nível
            data = 0
        return (RISCO[i["nivel"]], -data, i["ev"].get("numero") or "", i["ev"].get("id") or "")
    return sorted(itens, key=chave)


def cliente_de(i):
    return i["ev"].get("cliente") or (fch.obter(i["ficha"], "cliente") if i["ficha"] else "") or ""


def responsavel_de(i):
    return (fch.obter(i["ficha"], "responsavel") if i["ficha"] else "") or ""


def tribunal_de(i):
    return i["ev"].get("tribunal") or (i["ficha"] or {}).get("tribunal") or ""


def filtrar(itens, cliente=None, responsavel=None, tribunal=None, nivel=None, processo=None):
    """Filtros da tela (valor vazio = não filtra). `processo` casa por trecho do número, sem pontuação."""
    so_digitos = lambda s: re.sub(r"\D", "", s or "")
    saida = []
    for i in itens:
        if cliente and cliente_de(i) != cliente:
            continue
        if responsavel and responsavel_de(i) != responsavel:
            continue
        if tribunal and tribunal_de(i) != tribunal:
            continue
        if nivel and i["nivel"] != nivel:
            continue
        if processo and so_digitos(processo) not in so_digitos(i["ev"].get("numero")):
            continue
        saida.append(i)
    return saida


def contar(itens):
    c = {n: 0 for n in NIVEIS}
    for i in itens:
        c[i["nivel"]] += 1
    c["total"] = len(itens)
    return c


# ------------------------------------------------------------------ aprovação em lote

def amostra_obrigatoria(ids, pct=None, semente=None):
    """Conjunto de ids que NÃO podem ser aprovados em lote (revisão manual obrigatória): `pct`% do total,
    arredondando para cima (mínimo 1 quando há ids e pct > 0). Reprodutável: independe da ordem dos ids."""
    cfg = configuracao()
    pct = cfg["amostragem_pct"] if pct is None else min(max(float(pct), 0.0), 100.0)
    semente = cfg["semente"] if semente is None else semente
    ids = sorted({i for i in ids if i is not None})
    if not ids or pct <= 0:
        return set()
    k = min(len(ids), max(1, math.ceil(len(ids) * pct / 100.0)))
    ordenados = sorted(ids, key=lambda i: hashlib.sha256(f"{semente}|{i}".encode("utf-8")).hexdigest())
    return set(ordenados[:k])


def preparar_lote(eventos, fichas, filtros=None, pct=None, semente=None):
    """O que um lote faria agora, sem gravar nada:
    {"elegiveis": [item], "amostra": [item], "aprovar": [item], "barrados": {"amarelo": n, "vermelho": n, "amostra_anterior": n}}.
    Vale o filtro de cliente/responsável/tribunal/processo; o nível é sempre verde."""
    filtros = {k: v for k, v in (filtros or {}).items() if k in ("cliente", "responsavel", "tribunal", "processo")}
    todos = filtrar(classificar_lista(eventos, fichas), **filtros)
    barrados = {"amarelo": 0, "vermelho": 0, "amostra_anterior": 0}
    elegiveis = []
    for i in todos:
        if i["nivel"] != "verde":
            barrados[i["nivel"]] += 1
        elif i["ev"].get("amostra_lote"):
            barrados["amostra_anterior"] += 1
        elif exige_humano(i["ev"], i["ficha"]) or not (i["ev"].get("frase") or "").strip():
            barrados["vermelho"] += 1      # não acontece com as regras de hoje; é a segunda trava
        else:
            elegiveis.append(i)
    sorteados = amostra_obrigatoria([i["ev"]["id"] for i in elegiveis], pct, semente)
    amostra = [i for i in elegiveis if i["ev"]["id"] in sorteados]
    aprovar = [i for i in elegiveis if i["ev"]["id"] not in sorteados]
    return {"elegiveis": elegiveis, "amostra": amostra, "aprovar": aprovar, "barrados": barrados}


def aplicar_lote(eventos, fichas, aprovador, filtros=None, pct=None, semente=None, agora=None):
    """Aprova em lote os verdes fora da amostra, MODIFICANDO os eventos da lista (quem chama grava com
    comum.salvar_eventos e registra o lote com registrar_lote). Devolve o registro do lote."""
    if not (aprovador or "").strip():
        raise ValueError("Informe quem está aprovando o lote.")
    agora = agora or datetime.datetime.now()
    plano = preparar_lote(eventos, fichas, filtros, pct, semente)
    ids = [i["ev"]["id"] for i in plano["aprovar"]]
    amostra = [i["ev"]["id"] for i in plano["amostra"]]
    lote_id = f"lote-{agora:%Y%m%d-%H%M%S}-{hashlib.sha1('|'.join(sorted(ids + amostra)).encode()).hexdigest()[:6]}"
    carimbo = agora.isoformat(timespec="seconds")
    for i in plano["aprovar"]:
        i["ev"].update(status="aprovado", aprovado_por=aprovador.strip(), aprovado_em=carimbo, lote=lote_id,
                       triagem={"nivel": i["nivel"], "motivos": list(i["motivos"])})
    for i in plano["amostra"]:
        i["ev"]["amostra_lote"] = lote_id
    cfg = configuracao()
    return {"id": lote_id, "aprovado_por": aprovador.strip(), "em": carimbo,
            "filtros": {k: v for k, v in (filtros or {}).items() if v},
            "amostragem_pct": cfg["amostragem_pct"] if pct is None else pct,
            "semente": cfg["semente"] if semente is None else semente,
            "aprovados": ids, "amostra": amostra, "barrados": plano["barrados"]}


def _arquivo_de_lotes():
    return comum.DATA / "lotes.json"


def registrar_lote(entrada):
    """Acrescenta o lote ao registro do relatório (data/lotes.json)."""
    lista = comum.load_json(_arquivo_de_lotes(), [])
    lista.append(entrada)
    comum.save_json(_arquivo_de_lotes(), lista)


def lotes():
    """Lotes já aprovados neste relatório, do mais antigo ao mais recente."""
    return comum.load_json(_arquivo_de_lotes(), [])
