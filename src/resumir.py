"""Transforma eventos coletados em rascunhos de linha de relatório.

- Movimentação sem documento: tradução fixa (traduzir.py), sem IA.
- Documento: a primeira metade da frase sai por regra ("O juiz proferiu
  decisão"); o modelo local (Ollama) completa com o que o documento diz e
  copia o trecho que sustenta o resumo. Esse trecho é conferido contra o
  texto: se a IA "citou" algo que não está no documento, o rascunho vai para
  a revisão com alerta.

Uso:
    python resumir.py              # processa a fila
    python resumir.py --modelo     # mostra o modelo escolhido para esta máquina
    python resumir.py --testar ARQ.pdf [tipo]   # resume um arquivo avulso
"""
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from difflib import SequenceMatcher
from pathlib import Path

from comum import config, eventos, normalizar, salvar_eventos
from traduzir import autoria, frase_documento, traduzir_movimento
import carteira as cart
import comum

LIMITE_TEXTO = 9000  # caracteres enviados ao modelo; acima disso, início + fim
AUTOR_LEGIVEL = {"nos": "o nosso escritório", "contraria": "a parte contrária", "juizo": "o juiz ou tribunal",
                 "mp": "o Ministério Público", "perito": "o perito", "cartorio": "o cartório", "outro": "não identificado"}
POLO_LEGIVEL = {"ativo": "autor da ação (polo ativo)", "passivo": "réu (polo passivo)"}
EFEITOS = ["favoravel", "desfavoravel", "neutro", "incerto"]

# Modelo sugerido por memória da máquina (GB). Só modelos pequenos: o relatório
# descreve o que aconteceu, não analisa o mérito.
MODELOS_POR_MEMORIA = [(12, "llama3.2:3b"), (10**6, "gemma3:4b")]

ESQUEMA = {
    "type": "object",
    "properties": {
        "conteudo": {"type": "string"},
        "trecho_origem": {"type": "string"},
        "prazo": {"type": ["string", "null"]},
        "audiencia": {"type": ["string", "null"]},
        "efeito": {"type": "string", "enum": EFEITOS},
    },
    "required": ["conteudo", "trecho_origem", "prazo", "audiencia", "efeito"],
}

SISTEMA = (
    "Você resume documentos de processos judiciais para o cliente do escritório, uma pessoa leiga. "
    "Escreva sempre do ponto de vista desse cliente: deixe claro de quem era o pedido (do cliente ou da parte "
    "contrária) e o que o resultado significa para ele, em tom sóbrio, sem comemorar, sem alarmar e sem prometer resultado. "
    "Use só o que está escrito no texto; nunca complete com suposição. "
    "Não cite número de lei, artigo nem jurisprudência. "
    "Se o texto não permitir saber o conteúdo, escreva exatamente: 'Não foi possível identificar o conteúdo.' "
    "Responda apenas com o JSON pedido."
)


def contexto_do_processo(numero):
    proc = comum.carteira().get(numero, {})
    return {"cliente": proc.get("cliente", ""), "polo": proc.get("polo_cliente", ""),
            "contraria": proc.get("parte_contraria", ""), "variacoes": cart.variacoes_do_cliente(proc.get("cliente", ""))}


def memoria_gb():
    if sys.platform.startswith("win"):
        try:
            import ctypes

            class Mem(ctypes.Structure):
                _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
            m = Mem()
            m.dwLength = ctypes.sizeof(Mem)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m))
            return m.ullTotalPhys / 2**30
        except Exception:
            return 8
    try:
        return int(subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout) / 2**30
    except (ValueError, FileNotFoundError):
        return 8


def modelo_escolhido():
    escolhido = config().get("modelo", "auto")
    if escolhido != "auto":
        return escolhido
    mem = memoria_gb()
    return next(m for limite, m in MODELOS_POR_MEMORIA if mem < limite)


def _ollama(caminho, corpo=None, timeout=300):
    url = config().get("ollama_url", "http://127.0.0.1:11434") + caminho
    dados = json.dumps(corpo).encode() if corpo is not None else None
    req = urllib.request.Request(url, data=dados, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def ollama_pronto(modelo):
    """None se pronto; senão, a mensagem do que falta."""
    try:
        nomes = {m["name"] for m in _ollama("/api/tags", timeout=5).get("models", [])}
    except (urllib.error.URLError, OSError):
        return "A IA local não está instalada ou não está rodando (no painel, link \"IA local\" no alto da página)."
    if modelo not in nomes and f"{modelo}:latest" not in nomes:
        return f"O modelo {modelo} ainda não foi baixado (no painel, link \"IA local\" no alto da página)."
    return None


def recorte(texto):
    if len(texto) <= LIMITE_TEXTO:
        return texto
    return texto[:3000] + "\n\n[...]\n\n" + texto[-(LIMITE_TEXTO - 3000):]


def montar_pedido(texto, tipo, quem, frase, ctx):
    cliente = ctx.get("cliente") or "não informado"
    polo = POLO_LEGIVEL.get(ctx.get("polo"), "posição no processo não informada")
    return (
        f"Nosso cliente: {cliente}, que no processo é {polo}.\n"
        f"Parte contrária: {ctx.get('contraria') or 'não informada'}.\n"
        f"Tipo do documento: {tipo}\n"
        f"Quem apresentou: {AUTOR_LEGIVEL.get(quem, quem)}\n"
        f"Frase inicial do relatório, já pronta: \"{frase}\"\n\n"
        "Complete em JSON:\n"
        "- conteudo: a CONTINUAÇÃO da frase inicial (ela já diz quem fez e o quê), começando com verbo no gerúndio, "
        "UMA frase de até 40 palavras, em português simples, dizendo o que o documento pede, decide ou determina, do ponto de vista do nosso cliente. "
        "Exemplos: 'intimando a parte contrária a replicar a contestação', 'negando o pedido de urgência da parte contrária', "
        "'pedindo a juntada do comprovante das custas'. Não comece com 'O documento'. Sem termos técnicos quando houver palavra comum.\n"
        "- trecho_origem: copie LITERALMENTE do texto a frase que sustenta o conteúdo (até 300 caracteres).\n"
        "- prazo: prazo ou data fixada para alguém cumprir algo (ex.: '15 dias para o autor se manifestar'); null se não houver.\n"
        "- audiencia: data e hora de audiência marcada; null se não houver.\n"
        "- efeito: para o nosso cliente, o documento é 'favoravel', 'desfavoravel', 'neutro' (andamento sem ganho nem perda) "
        "ou 'incerto' (não dá para saber pelo texto).\n\n"
        f"TEXTO DO DOCUMENTO:\n<<<\n{recorte(texto)}\n>>>"
    )


GERUNDIO = {"determina": "determinando", "intima": "intimando", "defere": "deferindo", "indefere": "indeferindo",
            "homologa": "homologando", "julga": "julgando", "mantém": "mantendo", "mantem": "mantendo",
            "acolhe": "acolhendo", "rejeita": "rejeitando", "nega": "negando", "concede": "concedendo",
            "condena": "condenando", "extingue": "extinguindo", "suspende": "suspendendo", "designa": "designando",
            "decide": "decidindo", "reconhece": "reconhecendo", "pede": "pedindo", "requer": "requerendo",
            # no passado, como o modelo às vezes escreve
            "determinou": "determinando", "intimou": "intimando", "deferiu": "deferindo", "indeferiu": "indeferindo",
            "homologou": "homologando", "julgou": "julgando", "manteve": "mantendo", "acolheu": "acolhendo",
            "rejeitou": "rejeitando", "negou": "negando", "concedeu": "concedendo", "condenou": "condenando",
            "extinguiu": "extinguindo", "suspendeu": "suspendendo", "designou": "designando", "decidiu": "decidindo",
            "reconheceu": "reconhecendo", "pediu": "pedindo", "requereu": "requerendo"}


def limpar_conteudo(conteudo):
    """Rede de segurança para o encaixe na frase: tira 'O documento ...' / 'o juiz ...'
    do começo e converte 'determina-se', 'determina que' para o gerúndio."""
    conteudo = re.sub(r"^(o|este|esse)\s+(documento|ato|despacho|ato ordinatório)\s+", "", conteudo.strip(), flags=re.I)
    conteudo = re.sub(r"^(o juiz|a juíza|o tribunal|o magistrado)\s+", "", conteudo, flags=re.I)
    m = re.match(r"^(\w+)(-se)?\b", conteudo, re.I)
    if m and m.group(1).lower() in GERUNDIO:
        conteudo = GERUNDIO[m.group(1).lower()] + conteudo[m.end():]
    conteudo = re.sub(r",?\s*(conforme|como)\s+(determinado|disposto|consta|indicado)\s+no\s+(documento|texto)\.?$", "", conteudo, flags=re.I)
    return conteudo.rstrip(".")


def trecho_confere(trecho, texto):
    t, base = normalizar(trecho), normalizar(texto)
    if len(t) < 15:
        return False
    if t in base:
        return True
    m = SequenceMatcher(None, base, t, autojunk=False).find_longest_match(0, len(base), 0, len(t))
    return m.size / len(t) >= 0.85


MESES_NUM = {m: i for i, m in enumerate(["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho",
                                          "agosto", "setembro", "outubro", "novembro", "dezembro"], start=1)}


DATA_NUM = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
DATA_EXTENSO = re.compile(r"\b(\d{1,2})\s+de\s+([a-z]+)\s+de\s+(\d{4})")
# datas que são do próprio documento (certidão, assinatura, local e data), não de um ato marcado
CONTEXTO_DO_DOCUMENTO = re.compile(r"(nesta data|assinado eletronicamente.{0,80}|[a-z]+/[a-z]{2}|fortaleza)[\s,]*$")


def _datas(texto, ignorar_do_documento=False):
    """Datas do texto como (dia, mês, ano), em '06/10/2026' ou '6 de outubro de 2026'."""
    achadas = set()
    for padrao, conv in ((DATA_NUM, lambda d, m, a: (int(d), int(m), int(a))),
                         (DATA_EXTENSO, lambda d, m, a: (int(d), MESES_NUM.get(m, 0), int(a)))):
        for m in padrao.finditer(texto):
            if ignorar_do_documento and CONTEXTO_DO_DOCUMENTO.search(texto[max(0, m.start() - 40):m.start()]):
                continue
            data = conv(*m.groups())
            if data[1]:
                achadas.add(data)
    return achadas


def data_de_audiencia_confere(valor, texto):
    """A data informada pela IA precisa estar no documento a até ~120 caracteres
    da palavra 'audiência', e não pode ser a data da certidão ou da assinatura."""
    alvo = _datas(normalizar(valor))
    if not alvo:
        return False
    base = normalizar(texto)
    for m in re.finditer(r"audiencia", base):
        if alvo & _datas(base[max(0, m.start() - 120):m.end() + 120], ignorar_do_documento=True):
            return True
    return False


def conferir(resultado, texto):
    """Checagens determinísticas sobre a saída do modelo."""
    alertas = []
    if not trecho_confere(resultado.get("trecho_origem", ""), texto):
        alertas.append("O trecho citado pela IA não foi encontrado no documento: conferir o resumo.")
    base = normalizar(texto)
    for campo in ("prazo", "audiencia"):
        valor = resultado.get(campo) or ""
        for numero in re.findall(r"\d+(?:/\d+)*", valor):
            if numero not in base:
                alertas.append(f"O {campo} '{valor}' tem número que não aparece no documento.")
                break
    if resultado.get("audiencia") and not data_de_audiencia_confere(resultado["audiencia"], texto):
        alertas.append(f"A data de audiência '{resultado['audiencia']}' não aparece junto da palavra audiência no documento.")
    if re.search(r"\bart(igo)?s?\.?\s*\d|\blei\s+n?º?\s*\d", resultado.get("conteudo", ""), re.I):
        alertas.append("A IA citou dispositivo legal: conferir.")
    if "nao foi possivel identificar" in normalizar(resultado.get("conteudo", "")):
        alertas.append("A IA não identificou o conteúdo: resumir manualmente.")
    if resultado.get("efeito") == "desfavoravel":
        alertas.append("Resultado desfavorável ao cliente, segundo a IA: avaliar contato pessoal antes de enviar o relatório.")
    return alertas


def conferir_contexto(ev, texto, ctx):
    """O que dá para conferir sem IA sobre o cliente e o lado dele."""
    alertas = []
    if not ctx.get("cliente"):
        alertas.append("Processo sem cliente na carteira: o ponto de vista do resumo não pôde ser definido.")
        return alertas
    if ctx.get("polo") not in POLO_LEGIVEL:
        alertas.append("Polo do cliente não informado na carteira: conferir o ponto de vista do resumo.")
    if len(texto) > 300:
        corrido = " ".join(re.sub(r"[^a-z0-9]+", " ", normalizar(texto)).split())
        if not any(" ".join(cart._sem_sufixo(v)) in corrido for v in ctx["variacoes"]):
            alertas.append("O nome do cliente não aparece no documento: confirmar se é do processo certo.")
    return alertas


def resumir_texto(texto, tipo, quem, frase, modelo, ctx):
    resposta = _ollama("/api/chat", {
        "model": modelo,
        "stream": False,
        "format": ESQUEMA,
        "options": {"temperature": 0, "num_ctx": 8192},
        "messages": [{"role": "system", "content": SISTEMA},
                     {"role": "user", "content": montar_pedido(texto, tipo, quem, frase, ctx)}],
    })
    resultado = json.loads(resposta["message"]["content"])
    primeira = (limpar_conteudo(resultado.get("conteudo", "")).split() or [""])[0].lower()
    if not primeira.endswith("ndo") and "nao foi possivel" not in normalizar(resultado.get("conteudo", "")):
        # modelo pequeno às vezes ignora o formato: pede de novo, mostrando o erro
        resposta = _ollama("/api/chat", {
            "model": modelo, "stream": False, "format": ESQUEMA,
            "options": {"temperature": 0, "num_ctx": 8192},
            "messages": [{"role": "system", "content": SISTEMA},
                         {"role": "user", "content": montar_pedido(texto, tipo, quem, frase, ctx)},
                         {"role": "assistant", "content": json.dumps(resultado, ensure_ascii=False)},
                         {"role": "user", "content": "O campo conteudo precisa CONTINUAR a frase inicial começando com "
                                                     "um verbo no gerúndio (ex.: 'determinando...', 'acolhendo...', "
                                                     "'intimando...'), em uma só frase de até 40 palavras. Corrija."}],
        })
        resultado = json.loads(resposta["message"]["content"])
    return resultado, conferir(resultado, texto)


def processar_movimento(ev, docs_da_rodada=()):
    frase, relevante, data = traduzir_movimento(ev["titulo"])
    ev["data"] = data if re.search(r"\bem \d{2}/\d{2}/\d{4}", ev["titulo"]) and data else (ev.get("data") or data)
    if re.match(r"juntada de", ev["titulo"], re.I) and (ev["numero"], ev["detectado_em"][:10]) in docs_da_rodada:
        ev.update(status="descartado", motivo="Juntada coberta pelo documento baixado na mesma rodada.")
        return
    if not relevante:
        ev.update(status="descartado", motivo="Movimentação de rotina, sem interesse para o cliente.")
        return
    ev.update(frase=frase or ev["titulo"], conteudo="", status="rascunho")
    if frase is None:
        ev.setdefault("alertas", []).append("Movimentação sem tradução cadastrada: reescrever (e cadastrar em movimentos.json).")


def processar_documento(ev, modelo, falta):
    if ev["status"] == "sem_arquivo":
        texto, falta = "", "o documento não foi baixado; abrir nos autos e resumir manualmente."
    else:
        texto = Path(ev["texto_arquivo"]).read_text(encoding="utf-8")
    ctx = contexto_do_processo(ev["numero"])
    quem = autoria(texto, ev["tipo"], ev.get("descricao", ""))
    frase = frase_documento(ev["tipo"], ev.get("descricao", ""), quem, ctx.get("contraria", ""))
    ev.update(autoria=quem, frase=frase, modelo=None, polo_cliente=ctx.get("polo"))
    alertas = ev.setdefault("alertas", [])
    if quem == "outro" and texto:
        alertas.append("Autoria não identificada: confirmar quem apresentou o documento.")
    alertas.extend(conferir_contexto(ev, texto, ctx))
    if falta:
        ev.update(conteudo="", status="rascunho")
        alertas.append(f"Sem resumo automático: {falta}")
        return
    try:
        res, avisos = resumir_texto(texto, ev["tipo"], quem, frase, modelo, ctx)
    except Exception as e:  # modelo caiu no meio: o evento volta para a fila
        print(f"  falha ao resumir {ev['id']}: {e}")
        ev["alertas"] = []
        return
    ev.update(conteudo=limpar_conteudo(res["conteudo"]), trecho_origem=res["trecho_origem"].strip(),
              prazo=res.get("prazo"), audiencia=res.get("audiencia"), efeito=res.get("efeito"),
              modelo=modelo, status="rascunho")
    alertas.extend(avisos)


ATO_JUDICIAL = re.compile(r"acolhid|rejeitad|procedente|homolog|deferid|concedid|negad|proferid|julgad|"
                         r"senten[cç]a|decis[aã]o|despacho|ac[oó]rd[aã]o|embargos", re.I)


def marcar_repetidos(lista):
    """O que o ensaio mostrou: o PJe lista o mesmo 'Decorrido prazo... em 02/09' em
    vários dias seguidos; o mesmo documento é juntado duas vezes; e o andamento
    que anuncia uma decisão repete o documento já resumido. Nada é apagado:
    vira 'descartado' com o motivo, visível na revisão."""
    pendentes = [e for e in lista if e["status"] in ("coletado", "extraido", "sem_arquivo")]
    # andamentos com a própria data no texto: um só por processo
    vistos = {(e["numero"], e["titulo"]) for e in lista
              if e["tipo_evento"] == "movimento" and e["status"] not in ("coletado",)}
    for ev in pendentes:
        if ev["tipo_evento"] == "movimento" and re.search(r"\bem \d{2}/\d{2}/\d{4}", ev["titulo"]):
            chave = (ev["numero"], ev["titulo"])
            if chave in vistos:
                ev.update(status="descartado", motivo="Mesmo andamento já listado em outro dia.")
            vistos.add(chave)
    # documentos com o mesmo texto: um só
    textos = {}
    for ev in lista:
        if ev["tipo_evento"] == "documento" and ev.get("texto_arquivo") and Path(ev["texto_arquivo"]).exists():
            assinatura = (ev["numero"], normalizar(Path(ev["texto_arquivo"]).read_text(encoding="utf-8"))[:4000])
            if assinatura in textos and ev["status"] in ("extraido",):
                ev.update(status="descartado", motivo=f"Mesmo teor do documento {textos[assinatura]}.")
            else:
                textos.setdefault(assinatura, ev.get("doc_id") or ev["titulo"])
    # andamento que anuncia ato já coberto por documento baixado (mesmo dia ou "Documento: <id>")
    docs = [e for e in lista if e["tipo_evento"] == "documento" and e["status"] != "descartado"]
    for ev in pendentes:
        if ev["tipo_evento"] != "movimento" or ev["status"] != "coletado":
            continue
        ref = re.search(r"Documento:\s*(\d+)", ev["titulo"])
        cobre = any(d["numero"] == ev["numero"] and (
            (ref and d.get("doc_id") == ref.group(1)) or
            (d.get("data") == ev.get("data") and ATO_JUDICIAL.search(ev["titulo"]))) for d in docs)
        if cobre:
            ev.update(status="descartado", motivo="Coberto pelo documento resumido.")


def rodar():
    modelo = modelo_escolhido()
    falta = ollama_pronto(modelo)
    if falta:
        print(f"Aviso: {falta} Os documentos entram na revisão sem resumo.")
    lista = eventos()
    marcar_repetidos(lista)
    docs_da_rodada = {(e["numero"], e["detectado_em"][:10]) for e in lista if e["tipo_evento"] == "documento"}
    n = 0
    for ev in lista:
        if ev["tipo_evento"] == "movimento" and ev["status"] == "coletado":
            processar_movimento(ev, docs_da_rodada); n += 1
        elif ev["tipo_evento"] == "documento" and ev["status"] in ("extraido", "sem_arquivo"):
            print(f"  resumindo {ev['numero']} – {ev['tipo']}...")
            processar_documento(ev, modelo, falta); n += 1
            salvar_eventos(lista)  # salva a cada documento: o modelo local é lento
    # andamentos diferentes que viram a mesma frase no mesmo dia (ex.: "Encerrada" e
    # "Levantada" a suspensão): uma linha só
    vistos = set()
    for ev in lista:
        if ev["tipo_evento"] == "movimento" and ev["status"] == "rascunho":
            chave = (ev["numero"], ev.get("data"), ev.get("frase"))
            if chave in vistos:
                ev.update(status="descartado", motivo="Mesma informação no mesmo dia.")
            vistos.add(chave)
    salvar_eventos(lista)
    print(f"{n} evento(s) processado(s).")


def _arg(nome, padrao=""):
    return sys.argv[sys.argv.index(nome) + 1] if nome in sys.argv else padrao


if __name__ == "__main__":
    if "--modelo" in sys.argv:
        m = modelo_escolhido()
        print(f"Memória: {memoria_gb():.0f} GB -> modelo {m}. {ollama_pronto(m) or 'Pronto.'}")
    elif "--testar" in sys.argv:
        # python resumir.py --testar ARQ.pdf --tipo Decisão --cliente "RAZÃO" --polo passivo --contraria "FULANO"
        from extrair import extrair_arquivo
        texto, _ = extrair_arquivo(_arg("--testar"))
        tipo = _arg("--tipo", "Documento")
        ctx = {"cliente": _arg("--cliente"), "polo": _arg("--polo"), "contraria": _arg("--contraria"),
               "variacoes": [_arg("--cliente")] if _arg("--cliente") else []}
        quem = autoria(texto, tipo)
        frase = frase_documento(tipo, "", quem, ctx["contraria"])
        print(frase, *conferir_contexto({}, texto, ctx), sep="\n")
        modelo = modelo_escolhido()
        falta = ollama_pronto(modelo)
        if falta:
            sys.exit(falta)
        res, avisos = resumir_texto(texto, tipo, quem, frase, modelo, ctx)
        print(json.dumps(res, ensure_ascii=False, indent=2), *avisos, sep="\n")
        import relatorio
        print("Linha do relatório:", relatorio.linha({"frase": frase, "conteudo": limpar_conteudo(res["conteudo"]),
                                                     "prazo": res.get("prazo"), "audiencia": res.get("audiencia")}))
    else:
        rodar()
