"""Coletor simulado: o mesmo contrato do coletor real (docs/fase2/CONTRATOS.md, seção 6), sem tribunal,
certificado nem rede. Serve para testar a fila, a revisão e os relatórios de ponta a ponta.

    c = ColetorSimulado(fichas, semente=1, taxa_falha=0.1)
    r = c.coletar({"numero": fichas[0]["numero"]}, "padrao", desde="2026-01-01")
    r["capa"], r["movimentos"], r["documentos"], r["erro"]

Tudo é DETERMINÍSTICO por (semente, número do processo): a mesma pergunta devolve a mesma resposta, em
qualquer ordem e em qualquer máquina. O que o coletor devolve nasce da própria ficha (momento atual,
resultado, datas, partes), de modo que capa, movimentos e documentos são coerentes entre si.

- capa: campos de capa/partes/situação da ficha (os que o tribunal mostraria);
- movimentos: em ordem cronológica, no texto do tribunal (os mesmos padrões de movimentos.json), com
  `chave` única; só os posteriores a `desde`;
- documentos: arquivos pequenos GERADOS no disco (HTML ou PDF de texto, que `extrair.py` lê). `rapido` não
  devolve documentos; `padrao`, só os documentos-chave (sentença, acórdão, decisão); `completo`, todos;
- erros: proporção `taxa_falha` dos processos falha com um código do contrato. `captcha`, `segredo` e
  `nao_encontrado` falham sempre (a fila os manda para "manual"); `timeout`, `sessao_expirada` e `outro`
  falham só nas primeiras `tentativas_transitorias` chamadas e depois passam (provam a repetição);
- `falhar_em={numero: codigo}` (ou `{numero: (codigo, n_falhas)}`) força um erro específico;
- `chamadas` e `chamadas_por_numero` contam o trabalho feito, para provar que a fila não repete processo.

Também expõe os blocos que a geração de fixtures reaproveita: `roteiro`, `planejar_datas`, `fatos`,
`frase_do_fato`, `historico_texto` e `pdf_minimo`. Nenhum texto vem de documento real: tudo é inventado.
"""
import datetime
import html
import random
import tempfile
import textwrap
import time
from collections import Counter
from decimal import Decimal
from pathlib import Path

import comum
import ficha as fch

HOJE = "2026-10-07"          # relógio fictício das fixtures (a data "de hoje" da construção da Fase 2)
PROFUNDIDADES = ("rapido", "padrao", "completo")
CODIGOS = ("captcha", "segredo", "nao_encontrado", "timeout", "sessao_expirada", "outro")
PESOS_DOS_CODIGOS = (25, 15, 15, 20, 10, 15)
PERMANENTES = ("captcha", "segredo", "nao_encontrado")
MENSAGENS = {
    "captcha": "O tribunal pediu verificação humana (captcha).",
    "segredo": "Processo em segredo de justiça: sem acesso aos autos.",
    "nao_encontrado": "Processo não localizado no tribunal.",
    "timeout": "Tempo esgotado ao consultar o tribunal.",
    "sessao_expirada": "A sessão no tribunal expirou.",
    "outro": "Falha inesperada na consulta ao tribunal.",
}
TIPOS_CHAVE = ("Sentença", "Acórdão", "Decisão")
CAMPOS_DA_CAPA = ("vara", "municipio", "uf", "data_ajuizamento", "data_citacao", "classe", "assunto", "area",
                  "materia_principal", "objeto", "valor_causa", "autores", "reus", "momento_atual", "situacao",
                  "fase", "ultimo_andamento")

# ------------------------------------------------------------------ roteiro do processo

INICIO = ["distribuicao", "despacho"]
_ATE_CONTESTACAO = INICIO + ["citacao", "contestacao"]
_ATE_REPLICA = _ATE_CONTESTACAO + ["replica"]
# duração típica (dias) de cada etapa; só a proporção importa (as datas são esticadas entre o ajuizamento e o último andamento)
DURACAO = {"distribuicao": 0, "despacho": 8, "citacao": 20, "decisao_prazo": 12, "contestacao": 25, "replica": 15,
           "audiencia_designada": 10, "audiencia_realizada": 40, "pericia_designada": 20, "conclusos": 30,
           "final": 25, "recurso": 20, "acordao": 150, "transito": 30, "execucao": 20, "arquivamento": 15,
           "suspensao": 20}


def cenario_final(f, rng=None):
    """Como termina o processo, em palavras da simulação: procedencia, parcial, improcedencia, acordo,
    extincao, desistencia ou incompetencia."""
    momento = (fch.obter(f, "momento_atual") or "").upper()
    if momento.startswith("ACORDO"):
        return "acordo"
    if momento.startswith("EXTINTO"):
        return "extincao"
    por_resultado = {"Procedente": "procedencia", "Parcialmente procedente": "parcial", "Improcedente": "improcedencia",
                     "Acordo": "acordo", "Extinto sem resolução de mérito": "extincao",
                     "Arquivado / desistência": "desistencia", "Incompetência declarada": "incompetencia"}
    resultado = por_resultado.get(fch.obter(f, "resultado"))
    if resultado:
        return resultado
    rng = rng or random.Random(f["numero"])
    if momento.startswith("PROCESSO ARQUIVADO"):
        return rng.choice(["desistencia", "improcedencia"])
    return rng.choice(["procedencia", "parcial", "improcedencia"])


def roteiro(momento, houve_recurso=False):
    """Etapas que o processo já cumpriu até o momento atual (a última é a mais recente). Etapa 'final' é a
    decisão que encerra a instância (sentença, homologação de acordo ou extinção, conforme cenario_final)."""
    m = (momento or "").upper()
    recursal = ["recurso", "acordao"] if houve_recurso else []
    if m.startswith("AGUARDANDO CITAÇÃO") or m.startswith("AGUARDANDO INTIMAÇÃO DO RÉU"):
        return list(INICIO)
    if m == "AGUARDANDO CONTESTAÇÃO":
        return INICIO + ["citacao", "decisao_prazo"]
    if m == "AGUARDANDO RÉPLICA":
        return list(_ATE_CONTESTACAO)
    if m == "AGUARDANDO AUDIÊNCIA":
        return _ATE_REPLICA + ["audiencia_designada"]
    if m == "AGUARDANDO PROVA PERICIAL":
        return _ATE_REPLICA + ["pericia_designada"]
    if m in ("AGUARDANDO SENTENÇA", "AGUARDANDO JULGAMENTO", "AGUARDANDO JULGAMENTO EM 1º GRAU",
             "CONCLUSOS PARA DECISÃO"):
        return _ATE_REPLICA + ["audiencia_realizada", "conclusos"]
    if "APELAÇÃO" in m or "RECURSO" in m or "AGRAVO" in m:
        return _ATE_REPLICA + ["audiencia_realizada", "final", "recurso"]
    if m in ("CUMPRIMENTO DE SENTENÇA", "AGUARDANDO CONVERSÃO EM PENHORA", "AGUARDANDO PAGAMENTO"):
        return _ATE_REPLICA + ["audiencia_realizada", "final", *recursal, "transito", "execucao"]
    if m in ("AGUARDANDO PARCELAMENTO DAS CUSTAS", "AGUARDANDO MANIFESTAÇÃO DE TERCEIROS",
             "AGUARDANDO SUBSTITUIÇÃO PROCESSUAL"):
        return _ATE_CONTESTACAO + ["decisao_prazo"]
    if m == "SUSPENSO":
        return _ATE_CONTESTACAO + ["suspensao"]
    if m == "TRÂNSITO EM JULGADO":
        return _ATE_REPLICA + ["audiencia_realizada", "final", *recursal, "transito"]
    if m == "PROCESSO ARQUIVADO":
        return _ATE_REPLICA + ["audiencia_realizada", "final", "transito", "arquivamento"]
    if m == "ACORDO HOMOLOGADO":
        return _ATE_CONTESTACAO + ["audiencia_realizada", "final"]
    if m.startswith("EXTINTO"):
        return _ATE_CONTESTACAO + ["final"]
    return list(_ATE_CONTESTACAO)


def planejar_datas(etapas, ajuizamento, ultimo):
    """Datas ISO das etapas: a primeira no ajuizamento e a última no último andamento, esticadas na proporção
    das durações típicas. Sem acaso: a ficha e o coletor chegam sempre às mesmas datas."""
    inicio, fim = fch.data(ajuizamento), fch.data(ultimo)
    if len(etapas) == 1 or inicio is None or fim is None or fim <= inicio:
        return [(inicio or fim or fch.data(HOJE)).isoformat()] * len(etapas)
    acumulado, soma = [], 0
    for e in etapas:
        soma += DURACAO.get(e, 15)
        acumulado.append(soma)
    total = acumulado[-1] or 1
    return [(inicio + datetime.timedelta(days=round((fim - inicio).days * a / total))).isoformat() for a in acumulado]


# ------------------------------------------------------------------ contexto e fatos

def _rng(semente, numero, sal=""):
    return random.Random(f"{semente}:{numero}:{sal}")


def _br(iso):
    return fch.data_br(iso)


def _contexto(f):
    cliente = fch.obter(f, "cliente") or "Cliente Exemplo"
    autores = fch.obter(f, "autores") or ("Parte Autora Fictícia" if fch.obter(f, "polo_cliente") != "ativo" else cliente)
    reus = fch.obter(f, "reus") or (cliente if fch.obter(f, "polo_cliente") != "ativo" else "Parte Ré Fictícia")
    return {"numero": f["numero"], "tribunal": f.get("tribunal") or "", "cliente": cliente, "autores": autores,
            "reus": reus, "polo": fch.obter(f, "polo_cliente") or "passivo",
            "vara": fch.obter(f, "vara") or "1ª Vara Fictícia", "municipio": fch.obter(f, "municipio") or "Cidade Exemplo",
            "valor_causa": fch.dinheiro(fch.obter(f, "valor_causa")) or Decimal("10000.00"),
            "valor_acordo": fch.dinheiro(fch.obter(f, "valor_acordo")),
            "valor_arbitrado": fch.dinheiro(fch.obter(f, "valor_arbitrado")),
            "materia": fch.obter(f, "materia_principal") or "o objeto da ação",
            "objeto": fch.obter(f, "objeto") or "o pedido da inicial", "area": fch.obter(f, "area") or ""}


def _recursal(ctx):
    return "recurso ordinário" if ctx["tribunal"].startswith("TRT") else "apelação"


def fatos(f, semente=1):
    """Linha do tempo do processo, em ordem: lista de {"data", "etapa", "cenario", "movimentos": [texto do tribunal],
    "documento": None | {"tipo", "descricao", "chave"}}. É a verdade da simulação; movimentos, documentos e o
    histórico em texto corrido saem daqui."""
    ctx = _contexto(f)
    rng = _rng(semente, f["numero"], "fatos")
    final = cenario_final(f, rng)
    etapas = roteiro(fch.obter(f, "momento_atual"), fch.obter(f, "houve_recurso") == "Sim")
    ajuizamento = fch.obter(f, "data_ajuizamento")
    ultimo = fch.obter(f, "ultimo_andamento")
    if not ajuizamento and ultimo:
        ajuizamento = (fch.data(ultimo) - datetime.timedelta(days=30 * len(etapas))).isoformat()
    if not ultimo:
        base = fch.data(ajuizamento) or fch.data(HOJE)
        ultimo = (base + datetime.timedelta(days=30 * (len(etapas) - 1))).isoformat() if ajuizamento else HOJE
        ajuizamento = ajuizamento or (fch.data(ultimo) - datetime.timedelta(days=30 * len(etapas))).isoformat()
    datas = planejar_datas(etapas, ajuizamento, ultimo)
    resultado = []
    for etapa, data in zip(etapas, datas):
        cenario = final if etapa == "final" else None
        tipo_etapa = etapa
        if etapa == "final":
            tipo_etapa = {"acordo": "acordo", "extincao": "extincao"}.get(final, "sentenca")
        resultado.append(_montar_fato(tipo_etapa, cenario or etapa, data, ctx, rng))
    return resultado


def _quando(data, rng, dias_min=20, dias_max=45):
    """Audiência: DD/MM/AAAA e hora."""
    d = fch.data(data) + datetime.timedelta(days=rng.randint(dias_min, dias_max))
    while d.weekday() >= 5:
        d += datetime.timedelta(days=1)
    return d.strftime("%d/%m/%Y"), rng.choice(["09:00", "10:30", "13:30", "14:00", "15:30"])


def _montar_fato(etapa, cenario, data, ctx, rng):
    d = _br(data)
    ruido = rng.choice([[], [], ["Expedida/certificada a comunicação eletrônica"], ["Confirmada a comunicação eletrônica"]])
    fato = {"data": data, "etapa": etapa, "cenario": cenario if etapa in ("sentenca", "acordo", "extincao") else None,
            "movimentos": [], "documento": None, "detalhe": {}}
    mov, doc = fato["movimentos"], None
    if etapa == "distribuicao":
        mov += ["Distribuído por sorteio", "Juntada de Petição de petição inicial"]
        doc = ("Petição Inicial", "Petição Inicial", False)
    elif etapa == "despacho":
        mov += ["Conclusos para despacho", "Proferido despacho de mero expediente"]
        doc = ("Despacho", "Despacho", False)
    elif etapa == "citacao":
        mov += [f"Expedido(a) citação a(o) {ctx['reus'].split(';')[0]}", "Juntada de certidão de citação"]
        fato["detalhe"]["citacao"] = data
    elif etapa == "decisao_prazo":
        prazo = rng.choice([5, 10, 15])
        mov += ["Conclusos para decisão", "Indeferido o pedido de tutela" if ctx["polo"] == "ativo" else
                "Deferida a tutela de urgência", f"Publicado Decisão em {d}."]
        doc = ("Decisão", "Decisão", True)
        fato["detalhe"]["prazo"] = prazo
    elif etapa == "contestacao":
        mov += ["Juntada de Petição de contestação"]
        doc = ("Contestação", "Contestação", False)
    elif etapa == "replica":
        mov += ["Juntada de Petição de réplica"]
        doc = ("Réplica", "Réplica", False)
    elif etapa == "audiencia_designada":
        dia, hora = _quando(data, rng)
        mov += ["Conclusos para decisão", f"Audiência de conciliação designada ({dia} {hora}:00)"]
        doc = ("Decisão", "Decisão designa audiência", True)
        fato["detalhe"].update(audiencia=dia, hora=hora)
    elif etapa == "audiencia_realizada":
        mov += [f"Audiência de instrução realizada ({d} 10:00:00)"]
        doc = ("Ata de audiência", "Ata de audiência", False)
    elif etapa == "pericia_designada":
        mov += ["Conclusos para decisão", "Deferido o pedido de prova pericial"]
        doc = ("Decisão", "Decisão nomeia perito", True)
        fato["detalhe"]["prazo"] = 10
    elif etapa == "conclusos":
        mov += ["Conclusos para julgamento"]
    elif etapa == "sentenca":
        mov += ["Conclusos para julgamento", {
            "procedencia": "Julgado procedente o pedido", "parcial": "Julgado parcialmente procedente o pedido",
            "improcedencia": "Julgado improcedente o pedido", "desistencia": "Homologada a desistência da ação",
            "incompetencia": "Declarada a incompetência do juízo"}.get(cenario, "Julgado o pedido"),
            f"Publicado Sentença em {d}."]
        doc = ("Sentença", "Sentença", True)
    elif etapa == "acordo":
        mov += [f"Audiência de conciliação realizada ({d} 09:00:00)", "Homologado o acordo entre as partes",
                f"Publicado Sentença em {d}."]
        doc = ("Sentença", "Sentença homologatória de acordo", True)
    elif etapa == "extincao":
        mov += ["Conclusos para julgamento", "Extinto o processo sem resolução do mérito", f"Publicado Sentença em {d}."]
        doc = ("Sentença", "Sentença de extinção", True)
    elif etapa == "recurso":
        mov += [f"Juntada de Petição de {_recursal(ctx)}", "Remetidos os Autos (em grau de recurso) ao Tribunal"]
        doc = (_recursal(ctx).capitalize(), _recursal(ctx).capitalize(), False)
    elif etapa == "acordao":
        mov += ["Deliberado em Sessão - Julgado", f"Publicado Acórdão em {d}."]
        doc = ("Acórdão", "Acórdão", True)
    elif etapa == "transito":
        mov += ["Transitado em julgado"]
        doc = ("Certidão", "Certidão de trânsito em julgado", False)
    elif etapa == "execucao":
        mov += ["Juntada de Petição de cumprimento de sentença", "Conclusos para decisão", f"Publicado Decisão em {d}."]
        doc = ("Decisão", "Decisão cumprimento de sentença", True)
        fato["detalhe"]["prazo"] = 15
    elif etapa == "arquivamento":
        mov += ["Arquivado Definitivamente"]
        doc = ("Despacho", "Despacho arquive-se", False)
    elif etapa == "suspensao":
        mov += ["Suspenso o processo por decisão judicial"]
        doc = ("Decisão", "Decisão suspende o processo", True)
    mov += ruido
    if doc:
        fato["documento"] = {"tipo": doc[0], "descricao": doc[1], "chave": doc[2], "etapa": etapa}
    return fato


# ------------------------------------------------------------------ texto corrido (histórico do cliente)

def frase_do_fato(f, fato):
    """O fato em uma frase de relatório ao cliente: 'Em 18/06/2026 foi proferida sentença julgando ...'"""
    ctx, d, det = _contexto(f), _br(fato["data"]), fato["detalhe"]
    etapa, cen = fato["etapa"], fato["cenario"]
    nos_somos_reu = ctx["polo"] != "ativo"
    if etapa == "distribuicao":
        return f"Em {d} foi distribuída a ação perante a {ctx['vara']}."
    if etapa == "despacho":
        return f"Em {d} foi proferido despacho inicial, determinando a citação da parte ré."
    if etapa == "citacao":
        return f"Em {d} foi realizada a citação."
    if etapa == "decisao_prazo":
        return (f"Em {d} foi proferida decisão deferindo a tutela de urgência requerida pela parte contrária, com prazo de "
                f"{det['prazo']} dias para cumprimento.") if nos_somos_reu else (
            f"Em {d} foi proferida decisão indeferindo o pedido de tutela de urgência, com prazo de {det['prazo']} dias "
            "para manifestação.")
    if etapa == "contestacao":
        return f"Em {d} foi apresentada contestação" + (" pelo cliente." if nos_somos_reu else " pela parte contrária.")
    if etapa == "replica":
        return f"Em {d} foi apresentada réplica à contestação."
    if etapa == "audiencia_designada":
        return f"Em {d} foi designada audiência de conciliação para o dia {det['audiencia']}, às {det['hora']}."
    if etapa == "audiencia_realizada":
        return f"Em {d} foi realizada audiência, sem acordo entre as partes."
    if etapa == "pericia_designada":
        return f"Em {d} foi deferida a produção de prova pericial e nomeado perito, com prazo de {det['prazo']} dias para os quesitos."
    if etapa == "conclusos":
        return f"Em {d} os autos foram conclusos ao juiz para sentença."
    if etapa == "sentenca":
        texto = {"procedencia": "julgando procedente o pedido formulado na inicial",
                 "parcial": "julgando parcialmente procedentes os pedidos formulados na inicial",
                 "improcedencia": "julgando improcedente o pedido formulado na inicial",
                 "desistencia": "homologando a desistência da ação",
                 "incompetencia": "declarando a incompetência do juízo"}[cen]
        return f"Em {d} foi proferida sentença {texto}."
    if etapa == "acordo":
        valor = ctx["valor_acordo"]
        return f"Em {d} foi homologado acordo entre as partes" + (f", no valor de {fch.dinheiro_br(valor)}." if valor else ".")
    if etapa == "extincao":
        return f"Em {d} foi proferida sentença extinguindo o processo sem resolução do mérito."
    if etapa == "recurso":
        return f"Em {d} foi interposto {_recursal(ctx)}, com remessa dos autos ao tribunal."
    if etapa == "acordao":
        return f"Em {d} foi julgado o recurso, mantida a sentença."
    if etapa == "transito":
        return f"Em {d} a decisão transitou em julgado."
    if etapa == "execucao":
        return f"Em {d} teve início o cumprimento de sentença, com intimação para pagamento em {det['prazo']} dias."
    if etapa == "arquivamento":
        return f"Em {d} o processo foi arquivado definitivamente."
    if etapa == "suspensao":
        return f"Em {d} o processo foi suspenso por decisão judicial."
    return f"Em {d} houve movimentação processual."


def historico_texto(f, semente=1):
    """Histórico completo em texto corrido (o que um relatório de escritório traria na coluna de andamentos)."""
    return " ".join(frase_do_fato(f, fato) for fato in fatos(f, semente))


# ------------------------------------------------------------------ documentos (HTML e PDF mínimo)

def pdf_minimo(texto, linhas_por_pagina=46, largura=92):
    """PDF de texto, escrito à mão (Helvetica, WinAnsi): sem dependências, legível por pypdf e pdftotext."""
    linhas = []
    for paragrafo in texto.split("\n"):
        linhas += textwrap.wrap(paragrafo, largura) or [""]
    paginas = [linhas[i:i + linhas_por_pagina] for i in range(0, len(linhas), linhas_por_pagina)] or [[]]

    def literal(s):
        b = s.encode("cp1252", "replace")
        return b"(" + b.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"

    objetos = [b"<< /Type /Catalog /Pages 2 0 R >>", None,
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    ids_paginas = []
    for pagina in paginas:
        fluxo = b"BT /F1 11 Tf 14 TL 50 800 Td\n" + b"".join(literal(l) + b" Tj T*\n" for l in pagina) + b"ET"
        ids_paginas.append(len(objetos) + 1)
        objetos.append(b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 3 0 R >> >> "
                       b"/Contents %d 0 R >>" % (len(objetos) + 2))
        objetos.append(b"<< /Length %d >>\nstream\n" % len(fluxo) + fluxo + b"\nendstream")
    objetos[1] = b"<< /Type /Pages /Kids [" + b" ".join(b"%d 0 R" % i for i in ids_paginas) + b"] /Count %d >>" % len(ids_paginas)
    saida, posicoes = bytearray(b"%PDF-1.4\n"), []
    for i, corpo in enumerate(objetos, 1):
        posicoes.append(len(saida))
        saida += b"%d 0 obj\n" % i + corpo + b"\nendobj\n"
    inicio_xref = len(saida)
    saida += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objetos) + 1)
    saida += b"".join(b"%010d 00000 n \n" % p for p in posicoes)
    saida += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objetos) + 1, inicio_xref)
    return bytes(saida)


def _dinheiro(valor):
    return fch.dinheiro_br(valor)


def _valor_da_condenacao(ctx, cenario, rng):
    if ctx["valor_arbitrado"]:
        return ctx["valor_arbitrado"]
    fracao = Decimal(str(round(rng.uniform(0.5, 1.0) if cenario == "procedencia" else rng.uniform(0.2, 0.6), 2)))
    return (ctx["valor_causa"] * fracao).quantize(Decimal("0.01"))


def corpo_do_documento(fato, f, rng):
    """(título, [parágrafos]) do documento do fato, em linguagem de peça processual; texto inventado."""
    ctx, doc, det = _contexto(f), fato["documento"], fato["detalhe"]
    etapa, cen, d = doc["etapa"], fato["cenario"], _br(fato["data"])
    partes = f"Autor(es): {ctx['autores']}. Réu(s): {ctx['reus']}."
    intro = (f"Trata-se de ação ajuizada por {ctx['autores']} em face de {ctx['reus']}, na qual se discute {ctx['materia'].lower()} "
             f"({ctx['objeto'].lower()}). Valor da causa: {_dinheiro(ctx['valor_causa'])}.")
    cliente_reu = ctx["polo"] != "ativo"
    p = []
    if etapa == "sentenca":
        p = [intro, "Dispensado o relatório, nos termos da lei. Decido. As provas dos autos são suficientes para o julgamento."]
        if cen == "procedencia":
            p += [f"Ante o exposto, JULGO PROCEDENTE o pedido formulado na inicial, para condenar {ctx['reus']} ao pagamento de "
                  f"{_dinheiro(_valor_da_condenacao(ctx, cen, rng))}, com correção monetária e juros de mora. Custas e honorários "
                  "de 10% sobre a condenação pela parte ré."]
        elif cen == "parcial":
            p += [f"Ante o exposto, JULGO PARCIALMENTE PROCEDENTES os pedidos, apenas quanto a {ctx['materia'].lower()}, "
                  f"condenando {ctx['reus']} ao pagamento de {_dinheiro(_valor_da_condenacao(ctx, cen, rng))}; improcedentes os "
                  "demais. Sucumbência recíproca."]
        elif cen == "improcedencia":
            p += [f"Ante o exposto, JULGO IMPROCEDENTE o pedido formulado na inicial. Condeno {ctx['autores']} ao pagamento de "
                  "custas e honorários de 10% sobre o valor da causa, observada a gratuidade, se concedida."]
        elif cen == "desistencia":
            p += [f"{ctx['autores']} requereu a desistência da ação. HOMOLOGO a desistência e JULGO EXTINTO o processo, sem "
                  "resolução de mérito, nos termos do art. 485, VIII, do Código de Processo Civil."]
        else:
            p += ["DECLARO a incompetência deste juízo para processar a causa e determino a remessa dos autos ao juízo competente."]
        p += ["Publique-se. Registre-se. Intimem-se."]
    elif etapa == "acordo":
        valor = ctx["valor_acordo"]
        p = [intro, "As partes noticiaram composição amigável." + (
            f" O acordo prevê pagamento de {_dinheiro(valor)}, em parcela única." if valor else
            " Os termos constam da petição conjunta juntada aos autos."),
            "HOMOLOGO o acordo celebrado entre as partes e JULGO EXTINTO o processo, com resolução de mérito, nos termos do "
            "art. 487, III, alínea b, do Código de Processo Civil. Arquive-se oportunamente."]
    elif etapa == "extincao":
        p = [intro, "Verifico a ausência de pressuposto de desenvolvimento válido do processo, apesar de a parte autora ter sido intimada.",
             "Ante o exposto, JULGO EXTINTO o processo, sem resolução do mérito, com fundamento no art. 485, VI, do Código de "
             "Processo Civil. Sem condenação em honorários."]
    elif etapa == "decisao_prazo":
        if cliente_reu:
            p = [intro, "A parte autora requer tutela de urgência. Presentes a probabilidade do direito e o perigo de dano, DEFIRO "
                 f"o pedido para determinar que {ctx['reus']} cumpra a obrigação, no prazo de {det['prazo']} dias, sob pena de multa "
                 "diária de R$ 500,00. Cite-se e intime-se a parte ré."]
        else:
            p = [intro, "A parte autora requer tutela de urgência. Ausente o perigo de dano, INDEFIRO o pedido. "
                 f"Intime-se {ctx['autores']} para, no prazo de {det['prazo']} dias, emendar a inicial, sob pena de indeferimento."]
    elif etapa == "audiencia_designada":
        p = [intro, f"Recebida a inicial. DESIGNO audiência de conciliação para o dia {det['audiencia']}, às {det['hora']}. "
             "Intimem-se as partes e seus advogados. A ausência injustificada sujeita a parte às sanções legais."]
    elif etapa == "pericia_designada":
        p = [intro, "DEFIRO a produção de prova pericial e nomeio perito de confiança do juízo. As partes terão "
             f"{det['prazo']} dias para apresentar quesitos e indicar assistentes técnicos. Intimem-se."]
    elif etapa == "execucao":
        p = [intro, "Iniciado o cumprimento de sentença, INTIME-SE o executado para pagar o débito no prazo de "
             f"{det['prazo']} dias, sob pena de multa de 10% e honorários de 10%, nos termos do art. 523 do Código de Processo Civil."]
    elif etapa == "suspensao":
        p = [intro, "Diante do pedido conjunto das partes, SUSPENDO o processo pelo prazo de 90 dias. Decorrido o prazo, "
             "intimem-se as partes para dar andamento ao feito."]
    elif etapa == "acordao":
        p = [intro, "Vistos, relatados e discutidos os autos, a Turma, por unanimidade, NEGOU PROVIMENTO ao recurso, mantendo "
             "integralmente a sentença recorrida. Custas na forma da lei."]
    elif etapa == "despacho":
        p = [intro, "Recebo a petição inicial. Cite-se a parte ré para responder no prazo legal. Intimem-se."]
    elif etapa == "distribuicao":
        p = [f"{ctx['autores']}, já qualificado(a), vem, por seu advogado, propor a presente ação em face de {ctx['reus']}, "
             f"para discutir {ctx['materia'].lower()}: {ctx['objeto'].lower()}.",
             f"Dá-se à causa o valor de {_dinheiro(ctx['valor_causa'])}. Nestes termos, pede deferimento."]
    elif etapa == "contestacao":
        p = [f"{ctx['reus']}, já qualificado(a), apresenta CONTESTAÇÃO à ação movida por {ctx['autores']}, impugnando os fatos "
             f"narrados quanto a {ctx['materia'].lower()} e requerendo a improcedência dos pedidos. Nestes termos, pede deferimento."]
    elif etapa == "replica":
        p = [f"{ctx['autores']} apresenta RÉPLICA à contestação, reiterando os termos da inicial e requerendo a procedência do pedido."]
    elif etapa == "audiencia_realizada":
        p = [f"ATA DE AUDIÊNCIA. Aos {d}, realizou-se audiência, presentes as partes e seus advogados. Não houve acordo. "
             "Colhida a prova oral, encerrou-se a instrução. Os autos seguem conclusos para sentença."]
    elif etapa == "recurso":
        p = [f"{ctx['reus'] if cliente_reu else ctx['autores']} interpõe {_recursal(ctx).upper()} contra a sentença, pelas razões "
             "anexas, requerendo a reforma da decisão e o seu regular processamento."]
    elif etapa == "transito":
        p = [f"CERTIDÃO. Certifico que a decisão proferida nestes autos transitou em julgado em {d}, sem interposição de recurso."]
    elif etapa == "arquivamento":
        p = ["Cumpridas as formalidades legais, ARQUIVEM-SE os autos, com baixa na distribuição."]
    else:
        p = [intro]
    return doc["tipo"].upper(), [partes, *p]


def _documento_html(titulo, paragrafos, ctx, data):
    corpo = "".join(f"<p>{html.escape(t)}</p>" for t in paragrafos)
    return ("<html><head><meta charset=\"utf-8\"><title>" + html.escape(titulo) + "</title></head><body>"
            f"<p>PODER JUDICIÁRIO (documento fictício)</p><p>{html.escape(ctx['vara'])}</p><p>Processo nº {ctx['numero']}</p>"
            f"<p>{html.escape(titulo)}</p>{corpo}<p>{html.escape(ctx['municipio'])}, {_br(data)}. Juiz(a) de Direito (fictício).</p>"
            "<p>Documento sintético gerado para testes.</p></body></html>")


def _documento_texto(titulo, paragrafos, ctx, data):
    return "\n".join(["PODER JUDICIÁRIO (documento fictício)", ctx["vara"], f"Processo nº {ctx['numero']}", "", titulo, "",
                      *[t + "\n" for t in paragrafos], f"{ctx['municipio']}, {_br(data)}. Juiz(a) de Direito (fictício).", "",
                      "Documento sintético gerado para testes."])


def gravar_documento(fato, f, semente, pasta, ordem):
    """Grava o documento do fato (HTML ou PDF, conforme o acaso da semente) e devolve a entrada do contrato."""
    rng = _rng(semente, f["numero"], f"doc{ordem}")
    ctx, doc = _contexto(f), fato["documento"]
    titulo, paragrafos = corpo_do_documento(fato, f, rng)
    em_pdf = rng.random() < 0.5
    identificador = 190000000 + rng.randint(0, 9999999)
    extensao = "pdf" if em_pdf else "html"
    nome = f"{identificador} - {doc['tipo']} - {doc['descricao']}.{extensao}"
    destino = Path(pasta) / nome
    destino.parent.mkdir(parents=True, exist_ok=True)
    if em_pdf:
        destino.write_bytes(pdf_minimo(_documento_texto(titulo, paragrafos, ctx, fato["data"])))
    else:
        destino.write_text(_documento_html(titulo, paragrafos, ctx, fato["data"]), encoding="utf-8")
    return {"nome": nome, "tipo": doc["tipo"], "data": fato["data"], "caminho": str(destino)}


# ------------------------------------------------------------------ movimentos

def movimentos_dos_fatos(lista, grau="1º grau"):
    """Movimentos no formato do contrato, em ordem cronológica, com chave única 'DD/MM/AAAA|texto|n'."""
    contagem, saida = Counter(), []
    for fato in lista:
        for texto in fato["movimentos"]:
            base = f"{_br(fato['data'])}|{texto}"
            contagem[base] += 1
            saida.append({"data": fato["data"], "texto": texto, "grau": grau, "chave": f"{base}|{contagem[base]}"})
    saida.sort(key=lambda m: m["data"])  # estável: dentro do dia, a ordem em que aconteceram
    return saida


# ------------------------------------------------------------------ coletor

class ColetorSimulado:
    """Implementa o protocolo `Coletor` (CONTRATOS.md, seção 6). Veja o cabeçalho do módulo."""

    def __init__(self, fichas, semente=1, taxa_falha=0.1, atraso_s=0.0, pasta=None, falhar_em=None,
                 tentativas_transitorias=1):
        self.semente, self.taxa_falha, self.atraso_s = semente, taxa_falha, atraso_s
        self.falhar_em = dict(falhar_em or {})
        self.tentativas_transitorias = tentativas_transitorias
        self.fichas = {x["numero"]: x for x in fichas}
        self.vinculados = {v["numero"]: (x, v) for x in fichas for v in x.get("vinculados", [])}
        if pasta is None:
            pasta = (Path(comum.DOCS_DIR) / "simulado") if comum.DOCS_DIR else Path(tempfile.mkdtemp(prefix="simulado-"))
        self.pasta = Path(pasta)
        self.chamadas = 0
        self.chamadas_por_numero = Counter()
        self.registro = []   # (numero, profundidade, desde) de cada chamada, em ordem

    # -- erros
    def _erro(self, numero):
        tentativa = self.chamadas_por_numero[numero]   # já inclui esta chamada
        if numero in self.falhar_em:
            pedido = self.falhar_em[numero]
            codigo, falhas = pedido if isinstance(pedido, tuple) else (pedido, None)
            if falhas is None or tentativa <= falhas:
                return codigo
            return None
        if _rng(self.semente, numero, "falha").random() >= self.taxa_falha:
            return None
        codigo = _rng(self.semente, numero, "codigo").choices(CODIGOS, PESOS_DOS_CODIGOS)[0]
        if codigo in PERMANENTES or tentativa <= self.tentativas_transitorias:
            return codigo
        return None

    def codigo_de_falha_previsto(self, numero):
        """Código que a PRIMEIRA chamada devolveria para o número (ou None), sem contar chamada."""
        antes = self.chamadas_por_numero[numero]
        self.chamadas_por_numero[numero] = 1
        try:
            return self._erro(numero)
        finally:
            if antes:
                self.chamadas_por_numero[numero] = antes
            else:
                del self.chamadas_por_numero[numero]

    # -- coleta
    def coletar(self, processo, profundidade="padrao", desde=None):
        if profundidade not in PROFUNDIDADES:
            raise ValueError(f"Profundidade desconhecida: {profundidade!r}")
        numero = processo if isinstance(processo, str) else processo["numero"]
        self.chamadas += 1
        self.chamadas_por_numero[numero] += 1
        self.registro.append((numero, profundidade, desde))
        if self.atraso_s:
            time.sleep(self.atraso_s)
        codigo = self._erro(numero)
        if codigo is None and numero not in self.fichas and numero not in self.vinculados:
            codigo = "nao_encontrado"
        if codigo:
            return {"capa": {}, "movimentos": [], "documentos": [], "erro": {"codigo": codigo, "mensagem": MENSAGENS[codigo]}}
        if numero in self.fichas:
            ficha_do_processo = self.fichas[numero]
            capa = {c: fch.obter(ficha_do_processo, c) for c in CAMPOS_DA_CAPA if fch.obter(ficha_do_processo, c) is not None}
            lista = fatos(ficha_do_processo, self.semente)
        else:
            principal, vinculo = self.vinculados[numero]
            capa, lista = _capa_e_fatos_do_vinculado(principal, vinculo, self.semente)
            ficha_do_processo = {**principal, "numero": numero}
        corte = fch.parse_data(desde)
        movimentos = [m for m in movimentos_dos_fatos(lista) if corte is None or fch.data(m["data"]) > corte]
        documentos = []
        if profundidade != "rapido":
            for ordem, fato in enumerate(lista):
                if fato["documento"] is None or (corte and fch.data(fato["data"]) <= corte):
                    continue
                if profundidade == "padrao" and not fato["documento"]["chave"]:
                    continue
                documentos.append(gravar_documento(fato, ficha_do_processo, self.semente, self.pasta / numero, ordem))
        return {"capa": capa, "movimentos": movimentos, "documentos": documentos, "erro": None}


def _capa_e_fatos_do_vinculado(principal, vinculo, semente):
    """Processo vinculado (agravo, apenso, recurso): capa enxuta e três movimentos, perto do último andamento."""
    ctx = _contexto(principal)
    rng = _rng(semente, vinculo["numero"], "vinculado")
    ultimo = fch.data(fch.obter(principal, "ultimo_andamento") or HOJE)
    tipo = vinculo.get("tipo")
    classe = {"agravo": "Agravo de Instrumento", "recurso": "Recurso Ordinário" if ctx["tribunal"].startswith("TRT") else "Apelação Cível",
              "apenso": "Incidente (apenso)"}.get(tipo, "Processo vinculado")
    momento = {"agravo": "AGUARDA-SE JULGAMENTO DO AGRAVO DE INSTRUMENTO", "recurso": "AGUARDANDO JULGAMENTO DO RECURSO"}.get(
        tipo, fch.obter(principal, "momento_atual"))
    datas = [(ultimo - datetime.timedelta(days=d)).isoformat() for d in (rng.randint(60, 90), rng.randint(30, 50), rng.randint(0, 20))]
    datas.sort()
    capa = {"classe": classe, "uf": fch.obter(principal, "uf"), "municipio": fch.obter(principal, "municipio"),
            "vara": "1ª Câmara (fictícia)", "autores": ctx["autores"], "reus": ctx["reus"], "data_ajuizamento": datas[0],
            "ultimo_andamento": datas[-1], "fase": "Recurso", "area": ctx["area"] or None}
    if momento:
        capa["momento_atual"] = momento
    capa = {k: v for k, v in capa.items() if v}
    lista = []
    for etapa, data in zip(("distribuicao", "conclusos", "decisao_prazo"), datas):
        fato = _montar_fato(etapa, etapa, data, ctx, rng)
        if etapa == "distribuicao":
            fato["documento"] = {"tipo": classe, "descricao": classe, "chave": False, "etapa": etapa}
        lista.append(fato)
    return capa, lista
