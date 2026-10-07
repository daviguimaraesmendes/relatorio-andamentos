"""Síntese do processo (Fase 2, WS-5): momento atual, data do último andamento e narrativa.

Entradas, sempre em memória e sem rede:
    ficha       ficha v2 (ficha.py)
    eventos     eventos no formato de comum.py (tipo_evento "movimento" ou "documento"; `data` em DD/MM/AAAA)
    movimentos  movimentos no formato de ResultadoColeta (CONTRATOS §6): {"data": ISO, "texto", "grau", "chave"}
    provedor    objeto com `gerar(sistema, usuario, *, esquema=None, cliente) -> {"texto", "json", "motor"}`
                (CONTRATOS §8); local, externo ou, nos testes, um provedor falso. Pode ser None: então
                nada é perguntado a IA e o que dependeria dela fica sem resposta, com alerta.

API pública
    momento_atual(ficha, eventos, movimentos, provedor=None) -> {"momento", "qualificador", "evidencia", "origem", ...}
        1º regras sobre os movimentos mais recentes (taxonomia.momento_por_regras, do WS-1; enquanto ela não
        existir vale a tabela provisória deste módulo, ver `_REGRAS_PROVISORIAS`);
        2º, sem regra, o provedor de IA com VOCABULÁRIO FECHADO (esquema JSON com `enum` dos momentos) e
        exigência de trecho de origem, conferido contra as linhas enviadas;
        sem evidência: momento None e um alerta. Nunca devolve valor fora de taxonomia.MOMENTO_ATUAL.
        `origem` é "regra" ou "ia" (None se não houve resposta); `origem_ficha` diz com que origem gravar na
        ficha ("derivado" ou "sugerido"); `alertas` é uma lista de textos; `motor` só quando a IA respondeu.
    ultimo_andamento(eventos, movimentos, *, ignorar_rotina=True, eh_rotina=None) -> "AAAA-MM-DD" | None
        maior data entre movimentos e documentos; movimento de rotina (relevante=false em movimentos.json) só
        é ignorado se existir outro item relevante. A regra é configurável: `ignorar_rotina=False` conta tudo,
        e `eh_rotina(item)` troca o critério (item = {"data", "texto", "tipo": "movimento"|"documento"}).
    narrativa_inicial(ficha, eventos, profundidade, provedor=None) -> texto
    narrativa_incremental(ficha, eventos_novos) -> texto
    detalhar_inicial(...) / detalhar_incremental(...)  mesma coisa, devolvendo {"texto", "frases", "ignorados",
        "alertas"}: cada frase com camada e origem (evento ou campo da ficha), para a revisão e para o escritor.

Narrativa
    Estilo dos relatórios do escritório: "Em 01/10/2026 foi proferida decisão determinando ...", datas em
    DD/MM/AAAA, ordem cronológica, voz do escritório ("Apresentamos ...") quando a assinatura é do escritório
    (traduzir.autoria). As frases reutilizam relatorio.linha / planilha.frase_planilha (o mesmo texto da Fase 1).
    Camadas: CAPA (distribuição e citação, só dos campos da ficha que têm origem) -> MOVIMENTOS (os relevantes
    de movimentos.json, traduzidos por regra) -> DOCUMENTOS-CHAVE (resumo do documento).
        rapido    capa + movimentos relevantes (nenhum documento é aberto)
        padrao    + documentos-chave (petição inicial, sentença, acórdão, decisão com efeito)
        completo  + todos os documentos
    Movimento de rotina nunca entra. Evento descartado nunca entra. Nenhuma frase nasce sem um evento (ou um
    campo da ficha) por trás: movimento sem tradução cadastrada fica de fora e vira alerta (não se inventa
    frase). O texto de resumo do documento (`conteudo`) só entra se o trecho de origem confere com o documento
    (ou se uma pessoa já aprovou o evento); sem isso entra só a frase de regra ("Foi proferida sentença.").
    Quando falta o resumo de um documento que entra na narrativa e há provedor, o resumo é pedido a ele
    (resumir.resumir_com_provedor) e vira `conteudo`/`trecho_origem` do evento, com o `motor` que respondeu.

    HISTÓRICO MIGRADO NUNCA É REESCRITO: se a ficha tem linha_de_base com texto, narrativa_inicial devolve esse
    texto intacto seguido só do que veio depois dele (a camada de capa não se repete).
    narrativa_incremental só ACRESCENTA: ignora o que já consta em ficha["ultimo_texto_gravado"] ou na linha de
    base (mesma data + mesmo núcleo do texto, ver `_TextoExistente.ja_consta` e LIMIAR_NUCLEO) e tudo o que for anterior à última data do texto
    existente (volta em `ignorados`, com código estável: andamento_ja_presente, andamento_anterior_ao_texto).
    O fecho "Em DD/MM/AAAA, sem atualizações." do texto existente não conta como data de andamento.

Marcações nos eventos usados (mudança em memória; quem chama salva): `motor` ("regra" quando nenhuma IA
escreveu o evento; não é identificador de IA, confira antes de mostrar o selo) e `profundidade` (se ainda não
tinha). Estado do evento (`status`) não muda aqui.

Limites conhecidos: o vocabulário de "momento atual" é o de taxonomia.MOMENTO_ATUAL; a tabela provisória de
regras é pequena e conservadora (na dúvida, devolve None); só foi exercitado com dados fictícios e com provedor
falso, nunca com IA real.
"""
import json
import re
import unicodedata
from pathlib import Path

import comum
import ficha as fch
import planilha
import relatorio
import resumir
import taxonomia
import traduzir

PROFUNDIDADES = ("rapido", "padrao", "completo")
LIMITE_LINHAS_IA = 25          # linhas de movimentos/documentos enviadas ao provedor para o momento atual
LIMITE_TRECHO = 300            # tamanho máximo aceito para o trecho de origem da IA
LIMIAR_NUCLEO = 0.5            # fração do núcleo do texto que precisa aparecer perto da data para contar como repetido
ORIGEM_FICHA = {"regra": "derivado", "ia": "sugerido"}

# --------------------------------------------------------------------------------------- datas e textos


def _iso(valor):
    return fch.parse_data(valor)


def _br(iso):
    return fch.data_br(iso)


def _sem_acento(texto):
    """Minúsculas e sem acento, caractere por caractere (o tamanho não muda: posições valem no original)."""
    saida = []
    for c in str(texto):
        d = unicodedata.normalize("NFKD", c)
        saida.append((d[0] if d else c).lower())
    return "".join(saida)


def _norm(texto):
    return comum.normalizar(str(texto or ""))


def _texto_do_movimento(titulo):
    """'Conclusos para decisão (31/08/2026 13:20:05)' -> 'Conclusos para decisão' (a data fica de fora)."""
    return traduzir.DATA_FINAL.sub("", str(titulo or "")).strip()


def _data_do_evento(ev):
    """ISO da data do evento: `data` (DD/MM/AAAA ou ISO); para movimento cru, a data do próprio texto; por fim a
    data em que foi detectado (igual a relatorio._data_evento)."""
    d = _iso(ev.get("data"))
    if d:
        return d
    if ev.get("tipo_evento") == "movimento":
        d = _iso(traduzir.traduzir_movimento(ev.get("titulo") or "")[2])
        if d:
            return d
    return _iso(str(ev.get("detectado_em") or "")[:10])


def _eh_rotina_texto(texto):
    """Movimento que movimentos.json marca como sem interesse para o cliente (relevante=false)."""
    return not traduzir.traduzir_movimento(texto)[1]


def separar_qualificador(texto):
    """'CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)' -> ('CUMPRIMENTO DE SENTENÇA', 'HONORÁRIOS SUSPENSOS')."""
    m = re.match(r"^(.*?)\s*\(([^()]+)\)\s*$", str(texto or "").strip())
    if m and m.group(1):
        return m.group(1).strip(), m.group(2).strip()
    return str(texto or "").strip(), None


def _momento_do_vocabulario(texto):
    """O valor de taxonomia.MOMENTO_ATUAL que é IGUAL ao texto (sem acento nem caixa); None se não houver.
    Aqui não se adivinha: nada de 'parecido'."""
    chave = _sem_acento(texto).strip(" .;:,-")
    for canonico in taxonomia.MOMENTO_ATUAL:
        if _sem_acento(canonico) == chave:
            return canonico
    return None


# --------------------------------------------------------------------------------------- movimentos

def _movimentos_do_processo(eventos, movimentos):
    """[{"data": ISO, "texto", "origem"}] em ordem cronológica (empate: ordem de entrada), juntando os
    movimentos coletados e os eventos de movimento, sem repetir (data, texto)."""
    itens, vistos = [], set()

    def somar(data, texto, origem):
        texto = _texto_do_movimento(texto)
        if not texto or not data:
            return
        chave = (data, _norm(texto))
        if chave not in vistos:
            vistos.add(chave)
            itens.append({"data": data, "texto": texto, "origem": origem})

    for m in movimentos or []:
        somar(_iso(m.get("data")), m.get("texto"), m.get("chave") or "movimento coletado")
    for ev in eventos or []:
        if ev.get("tipo_evento") == "movimento":
            somar(_data_do_evento(ev), ev.get("titulo"), ev.get("id") or "evento")
    return sorted(itens, key=lambda i: i["data"])  # sorted é estável


# Tabela PROVISÓRIA de regras (TODO(WS-1): trocar por taxonomia.momento_por_regras quando existir; é ela que
# `momento_atual` usa se estiver definida). Aplicada ao movimento mais recente que não seja neutro:
#   (padrão, momento)   o movimento decide o momento
#   (padrão, "")        o movimento torna o momento incerto: para e devolve None
#   (padrão, None)      neutro: não muda o momento, olha o movimento anterior
# Movimento que nenhuma regra cobre e que não é de rotina (movimentos.json) também PARA: na dúvida, None.
_REGRAS_PROVISORIAS = [
    (r"^(Encerrada|Levantada) a suspens|^Desarquivad", ""),
    (r"^Tr[aâ]nsit(o|ado) em julgado", "TRÂNSITO EM JULGADO"),
    (r"^Arquivad", "PROCESSO ARQUIVADO"),
    (r"^Homologad[oa] (o )?acordo", "ACORDO HOMOLOGADO"),
    (r"^Extint[oa] o processo sem resolu", "EXTINTO SEM RESOLUÇÃO DE MÉRITO"),
    (r"^(Processo )?[Ss]uspens", "SUSPENSO"),
    (r"^Conclusos para (julgamento|senten[cç]a)", "AGUARDANDO SENTENÇA"),
    (r"^Conclusos para decis", "CONCLUSOS PARA DECISÃO"),
    (r"^Remetidos os Autos \(em grau de recurso\)", "AGUARDANDO JULGAMENTO DO RECURSO"),
    (r"^Audi[eê]ncia .*(designada|marcada)", "AGUARDANDO AUDIÊNCIA"),
    (r"^Deferid[oa] o pedido de prova pericial", "AGUARDANDO PROVA PERICIAL"),
    (r"^Juntada de Peti[cç][aã]o de cumprimento de senten", "CUMPRIMENTO DE SENTENÇA"),
    (r"^Juntada de Peti[cç][aã]o de contesta", "AGUARDANDO RÉPLICA"),
    (r"^Distribu[ií]d", "AGUARDANDO CITAÇÃO"),
    # neutros: não dizem em que pé está o processo
    (r"^Publicad[oa]|^Decorrido|^Proferido despacho de mero expediente|^Juntada de Peti[cç][aã]o de peti[cç][aã]o inicial", None),
]


def _momento_por_regras_provisorio(movimentos):
    """(momento | None, evidência) pela tabela provisória. `movimentos`: formato de ResultadoColeta."""
    itens = sorted(({"data": _iso(m.get("data")), "texto": _texto_do_movimento(m.get("texto"))} for m in movimentos or []
                    if _iso(m.get("data")) and m.get("texto")), key=lambda i: i["data"])
    for pos in range(len(itens) - 1, -1, -1):
        texto = itens[pos]["texto"]
        regra = next(((rx, mom) for rx, mom in _REGRAS_PROVISORIAS if re.search(rx, texto, re.I)), None)
        if regra is None:
            if _eh_rotina_texto(texto):
                continue
            return None, ""
        momento = regra[1]
        if momento is None:
            continue
        if momento == "":
            return None, ""
        anteriores = [i["texto"] for i in itens[:pos]]
        if momento in ("CONCLUSOS PARA DECISÃO", "AGUARDANDO SENTENÇA") and any(
                re.search(r"cumprimento de senten", t, re.I) for t in anteriores):
            momento = "CUMPRIMENTO DE SENTENÇA"  # conclusos dentro da execução
        elif momento == "AGUARDANDO JULGAMENTO DO RECURSO" and any(re.search(r"apela[cç]", t, re.I) for t in anteriores[-4:]):
            momento = "AGUARDANDO JULGAMENTO DA APELAÇÃO"
        return momento, f"{_br(itens[pos]['data'])}: {texto}"
    return None, ""


def _regras():
    return getattr(taxonomia, "momento_por_regras", None) or _momento_por_regras_provisorio


def _evidencia_texto(evidencia):
    if isinstance(evidencia, dict):
        evidencia = evidencia.get("texto") or evidencia.get("trecho") or json.dumps(evidencia, ensure_ascii=False)
    return str(evidencia or "")


# --------------------------------------------------------------------------------------- momento atual

SISTEMA_MOMENTO = (
    "Você classifica em que momento está um processo judicial, para o quadro-resumo de um relatório ao cliente. "
    "Escolha EXATAMENTE um dos momentos da lista fechada que vier no pedido, escrito igual, ou null se as linhas "
    "não permitirem saber. Use só o que está escrito nas linhas do processo; nunca complete com suposição. "
    "Copie LITERALMENTE em trecho_origem a linha (ou parte dela) que sustenta a escolha. "
    "O qualificador (por exemplo HONORÁRIOS SUSPENSOS) só vale se constar das linhas; senão, null. "
    "Responda apenas com o JSON pedido."
)


def esquema_momento():
    """Esquema JSON da resposta da IA: `momento` só pode ser um valor do vocabulário (ou null)."""
    return {"type": "object",
            "properties": {"momento": {"enum": [*taxonomia.MOMENTO_ATUAL, None]},
                           "qualificador": {"type": ["string", "null"]},
                           "trecho_origem": {"type": "string"}},
            "required": ["momento", "qualificador", "trecho_origem"]}


def _linhas_para_ia(eventos, itens):
    """Linhas 'DD/MM/AAAA: texto', da mais recente para a mais antiga, com movimentos e documentos."""
    linhas = [(i["data"], 0, i["texto"]) for i in itens]
    for ev in eventos or []:
        if ev.get("tipo_evento") == "documento" and ev.get("status") != "descartado":
            rotulo = " – ".join(x for x in (ev.get("tipo"), ev.get("descricao")) if x) or str(ev.get("titulo") or "")
            texto = f"Documento: {rotulo}"
            if ev.get("conteudo") and ev.get("trecho_origem"):
                texto += f". Resumo: {ev.get('frase') or ''} {ev['conteudo']}".rstrip()
            if _data_do_evento(ev):
                linhas.append((_data_do_evento(ev), 1, texto))
    linhas.sort(key=lambda l: (l[0], l[1]), reverse=True)
    return [f"{_br(d)}: {t}" for d, _, t in linhas[:LIMITE_LINHAS_IA]]


def _trecho_confere(trecho, corpus):
    """O trecho (normalizado) está nas linhas enviadas à IA; ao menos 8 caracteres, para não casar palavra solta."""
    t = _norm(trecho)
    if len(t) < 8 or len(str(trecho)) > LIMITE_TRECHO:
        return False
    return t in _norm(corpus) or (len(t) >= 15 and resumir.trecho_confere(trecho, corpus))


def _pedir_momento_a_ia(ficha, eventos, itens, provedor, resultado):
    linhas = _linhas_para_ia(eventos, itens)
    if not linhas:
        resultado["alertas"].append("Não há movimentos nem documentos para indicar o momento atual.")
        return
    polo = resumir.POLO_LEGIVEL.get(fch.obter(ficha, "polo_cliente"), "posição no processo não informada")
    pedido = (f"Nosso cliente: {fch.obter(ficha, 'cliente') or 'não informado'}, que no processo é {polo}.\n\n"
              "Momentos permitidos (use um deles, escrito igual, ou null):\n"
              + "\n".join(f"- {m}" for m in taxonomia.MOMENTO_ATUAL)
              + "\n\nLinhas do processo, da mais recente para a mais antiga:\n<<<\n" + "\n".join(linhas) + "\n>>>\n\n"
              "Responda em JSON: momento (da lista ou null), qualificador (texto curto das linhas ou null), "
              "trecho_origem (cópia literal da linha que sustenta o momento).")
    try:
        resposta = provedor.gerar(SISTEMA_MOMENTO, pedido, esquema=esquema_momento(),
                                  cliente=fch.obter(ficha, "cliente") or "")
        dados = resposta.get("json")
        if dados is None:
            dados = json.loads(resposta.get("texto") or "")
        if not isinstance(dados, dict):
            raise ValueError("resposta fora do formato")
    except Exception as e:  # provedor fora do ar, JSON ruim: o processo segue sem momento da IA
        resultado["alertas"].append(f"A IA não respondeu de forma utilizável ({type(e).__name__}): indicar o momento atual manualmente.")
        return
    motor = resposta.get("motor") or ""
    if dados.get("momento") in (None, ""):
        resultado["alertas"].append("A IA não encontrou nas linhas o momento atual do processo: indicar manualmente.")
        return
    momento = _momento_do_vocabulario(str(dados["momento"]))
    if momento is None:
        resultado["alertas"].append(f"A IA indicou um momento fora do vocabulário ({dados['momento']!r}): descartado.")
        return
    corpus = "\n".join(linhas)
    trecho = str(dados.get("trecho_origem") or "").strip()
    if not _trecho_confere(trecho, corpus):
        resultado["alertas"].append("A IA não apresentou trecho de origem que conste do processo: momento descartado, indicar manualmente.")
        return
    qualificador = str(dados.get("qualificador") or "").strip().upper() or None
    if qualificador and _norm(qualificador) not in _norm(corpus):
        resultado["alertas"].append(f"Qualificador '{qualificador}' indicado pela IA não consta do processo: descartado.")
        qualificador = None
    resultado.update(momento=momento, qualificador=qualificador, evidencia=trecho, origem="ia", motor=motor)
    resultado["alertas"].append("Momento atual sugerido pela IA (não por regra): conferir na revisão.")


def momento_atual(ficha, eventos, movimentos, provedor=None):
    """Momento atual do processo, sempre do vocabulário fechado (ver o cabeçalho do módulo).

    Volta {"momento", "qualificador", "evidencia", "origem", "origem_ficha", "alertas"[, "motor"]}; sem resposta
    segura, momento None, origem None e o motivo em `alertas`. Nada é gravado na ficha."""
    resultado = {"momento": None, "qualificador": None, "evidencia": "", "origem": None, "origem_ficha": None,
                 "alertas": []}
    itens = _movimentos_do_processo(eventos, movimentos)
    por_regra, evidencia = _regras()([{"data": i["data"], "texto": i["texto"]} for i in itens])
    if por_regra:
        base, qualificador = separar_qualificador(por_regra)
        momento = _momento_do_vocabulario(base)
        if momento:
            resultado.update(momento=momento, qualificador=qualificador, evidencia=_evidencia_texto(evidencia),
                             origem="regra")
        else:
            resultado["alertas"].append(f"A regra devolveu um momento fora do vocabulário ({por_regra!r}): descartado.")
    if resultado["momento"] is None:
        if provedor is not None:
            _pedir_momento_a_ia(ficha, eventos, itens, provedor, resultado)
        else:
            resultado["alertas"].append("Nenhuma regra cobre os últimos movimentos e não há provedor de IA: "
                                        "indicar o momento atual manualmente.")
    resultado["origem_ficha"] = ORIGEM_FICHA.get(resultado["origem"])
    return resultado


# --------------------------------------------------------------------------------------- último andamento

def ultimo_andamento(eventos, movimentos, *, ignorar_rotina=True, eh_rotina=None):
    """Data ISO do último andamento: maior data entre movimentos e documentos (None se não há nenhuma).

    Com `ignorar_rotina` (padrão), movimento de rotina só vale se não houver nenhum item relevante; documento
    nunca é rotina. `eh_rotina(item)` substitui o critério padrão (movimentos.json, relevante=false)."""
    criterio = eh_rotina or (lambda item: item["tipo"] == "movimento" and _eh_rotina_texto(item["texto"]))
    itens = []
    for m in movimentos or []:
        itens.append({"data": _iso(m.get("data")), "texto": _texto_do_movimento(m.get("texto")), "tipo": "movimento"})
    for ev in eventos or []:
        if ev.get("tipo_evento") == "movimento":
            itens.append({"data": _data_do_evento(ev), "texto": _texto_do_movimento(ev.get("titulo")), "tipo": "movimento"})
        elif ev.get("tipo_evento") == "documento":
            itens.append({"data": _data_do_evento(ev), "texto": str(ev.get("titulo") or ""), "tipo": "documento"})
    itens = [i for i in itens if i["data"]]
    if not itens:
        return None
    if ignorar_rotina:
        relevantes = [i for i in itens if not criterio(i)]
        itens = relevantes or itens
    return max(i["data"] for i in itens)


# --------------------------------------------------------------------------------------- frases

CAMADA_ORDEM = {"capa": 0, "movimentos": 1, "documentos": 2}
APROVADO = ("aprovado", "relatado")
PALAVRAS_FRACAS = {"para", "pela", "pelo", "como", "entre", "sobre", "esta", "este", "esse", "essa", "foram",
                   "sido", "pelos", "pelas", "seus", "suas", "mais", "tambem", "apos", "ante", "processo", "autos",
                   "parte", "partes", "juiz", "juizo", "tribunal"}


def _documento_chave(ev):
    """Petição inicial, sentença, acórdão e decisão com efeito (despacho só se traz prazo ou audiência)."""
    alvo = f"{ev.get('tipo') or ''} {ev.get('descricao') or ''}"
    if re.search(r"inicial|senten[cç]a|ac[oó]rd[aã]o", alvo, re.I):
        return True
    if traduzir.categoria(ev.get("tipo") or "") == "decisao":
        if ev.get("prazo") or ev.get("audiencia"):
            return True
        return not re.search(r"despacho", alvo, re.I) and ev.get("efeito") != "neutro"
    return False


def _texto_do_documento(ev):
    """Texto extraído do documento (arquivo `texto_arquivo`), ou None se não está disponível."""
    for chave in ("texto", "texto_arquivo"):
        valor = ev.get(chave)
        if not valor:
            continue
        if chave == "texto":
            return str(valor)
        try:
            return Path(valor).read_text(encoding="utf-8")
        except OSError:
            return None
    return None


def _resumo_confiavel(ev, texto, alertas):
    """True se o `conteudo` do evento pode entrar na narrativa (ver o cabeçalho do módulo)."""
    if not (ev.get("conteudo") or "").strip():
        return False
    if ev.get("status") in APROVADO:
        return True
    trecho = (ev.get("trecho_origem") or "").strip()
    if not trecho:
        alertas.append(f"Resumo sem trecho de origem ({ev.get('titulo')}): só a frase de regra entrou na narrativa.")
        return False
    if texto is not None:
        confere = resumir.trecho_confere(trecho, texto)
    else:
        confere = not any("trecho citado" in a for a in ev.get("alertas") or [])
    if not confere:
        alertas.append(f"O trecho de origem não confere com o documento ({ev.get('titulo')}): "
                       "só a frase de regra entrou na narrativa.")
    return confere


def _resumir_documento(ficha, ev, texto, provedor, alertas):
    """Pede o resumo ao provedor e grava conteudo/trecho/prazo/audiencia/efeito/motor no evento (se confere)."""
    if provedor is None or texto is None or (ev.get("conteudo") or "").strip():
        return
    ctx = {"cliente": fch.obter(ficha, "cliente") or "", "polo": fch.obter(ficha, "polo_cliente") or "",
           "contraria": fch.obter(ficha, "parte_contraria") or ""}
    quem = ev.get("autoria") or traduzir.autoria(texto, ev.get("tipo") or "", ev.get("descricao") or "")
    frase = ev.get("frase") or traduzir.frase_documento(ev.get("tipo") or "", ev.get("descricao") or "", quem, ctx["contraria"])
    try:
        res, avisos, motor = resumir.resumir_com_provedor(provedor, texto, ev.get("tipo") or "", quem, frase, ctx,
                                                          ctx["cliente"])
    except Exception as e:
        alertas.append(f"Não foi possível resumir {ev.get('titulo')} ({type(e).__name__}): entrou só a frase de regra.")
        return
    if not resumir.trecho_confere(res["trecho_origem"], texto):
        alertas.append(f"O resumo de {ev.get('titulo')} veio sem trecho que confira com o documento: descartado.")
        return
    ev.update(conteudo=res["conteudo"], trecho_origem=res["trecho_origem"], prazo=res.get("prazo"),
              audiencia=res.get("audiencia"), efeito=res.get("efeito"), motor=motor or ev.get("motor"))
    ev.setdefault("autoria", quem)
    ev.setdefault("alertas", []).extend(avisos)
    ev["alertas"].append("Resumo gerado pela IA na síntese: conferir na revisão.")


def _visao_do_evento(ficha, ev, provedor, alertas):
    """(visão do evento no formato da Fase 1, incluindo `data` DD/MM/AAAA e `frase`), ou None se não gera frase."""
    iso = _data_do_evento(ev)
    if not iso:
        alertas.append(f"Evento sem data ({ev.get('titulo')}): não entrou na narrativa.")
        return None
    if ev.get("tipo_evento") == "movimento":
        frase = ev.get("frase") or traduzir.traduzir_movimento(ev.get("titulo") or "")[0]
        if not frase:
            alertas.append(f"Movimentação sem tradução cadastrada ({_texto_do_movimento(ev.get('titulo'))}): "
                           "não entrou na narrativa (cadastrar em movimentos.json).")
            return None
        return dict(ev, data=_br(iso), frase=frase, conteudo="", prazo=None, audiencia=None)
    texto = _texto_do_documento(ev)
    _resumir_documento(ficha, ev, texto, provedor, alertas)  # antes da cópia: o resumo novo vai para a visão
    visao = dict(ev, data=_br(iso))
    contraria = fch.obter(ficha, "parte_contraria") or ""
    quem = ev.get("autoria") or traduzir.autoria(texto or "", ev.get("tipo") or "", ev.get("descricao") or "")
    frase = ev.get("frase") or traduzir.frase_documento(ev.get("tipo") or "", ev.get("descricao") or "", quem, contraria)
    if not ev.get("tipo") and not ev.get("frase"):
        alertas.append(f"Documento sem tipo ({ev.get('titulo')}): não entrou na narrativa.")
        return None
    visao["frase"] = frase
    if not _resumo_confiavel(ev, texto, alertas):
        visao.update(conteudo="", prazo=None, audiencia=None)
    return visao


def _nucleo(texto):
    """Radicais (5 letras) das palavras do texto, sem datas, números nem palavras fracas: o 'núcleo' usado
    para reconhecer que duas frases dizem a mesma coisa."""
    sem_data = re.sub(r"\d{1,2}/\d{1,2}(/\d{2,4})?|\b\d+\b", " ", _sem_acento(texto))
    return {p[:5] for p in re.findall(r"[a-z]{4,}", sem_data) if p not in PALAVRAS_FRACAS}


FECHOS = (re.compile(r"\s*Em\s+\d{2}/\d{2}/\d{4},?\s+sem\s+(atualiza[cç][oõ]es|atualiza[cç][aã]o|andamentos?)\.?", re.I),
          planilha.FECHO)


def _sem_fecho(texto):
    for padrao in FECHOS:
        texto = padrao.sub(" ", texto)
    return texto


_DATA_NUM = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b")
_DATA_EXTENSO = re.compile(r"\b(\d{1,2}) de ([a-z]+) de (\d{4})\b")


def _datas_no_texto(texto):
    """[(posição, ISO)] das datas do texto, em 'DD/MM/AAAA' e por extenso ('6 de outubro de 2026')."""
    base, achadas = _sem_acento(texto), []
    for m in _DATA_NUM.finditer(base):
        d = _iso(f"{m[1]}/{m[2]}/{m[3]}")
        if d:
            achadas.append((m.start(), m.end(), d))
    for m in _DATA_EXTENSO.finditer(base):
        mes = resumir.MESES_NUM.get(m[2])
        d = _iso(f"{m[1]}/{mes}/{m[3]}") if mes else None
        if d:
            achadas.append((m.start(), m.end(), d))
    return sorted(achadas)


class _TextoExistente:
    """O que já está gravado (linha de base e último texto gravado), pronto para perguntar 'isto já consta?'."""

    def __init__(self, *textos):
        self.texto = " ".join(_sem_fecho(t) for t in textos if t).strip()
        self.base = _sem_acento(self.texto)
        self.datas = _datas_no_texto(self.texto)
        self.ultima = max((d for _, _, d in self.datas), default=None)

    def ja_consta(self, iso, frase):
        """True se a data aparece no texto com o núcleo da frase por perto (da data anterior à seguinte)."""
        alvo = _nucleo(frase)
        for i, (ini, fim, d) in enumerate(self.datas):
            if d != iso:
                continue
            limite_ini = max(self.datas[i - 1][1] if i else 0, ini - 120)
            limite_fim = self.datas[i + 1][0] if i + 1 < len(self.datas) else len(self.base)
            janela = _nucleo(self.base[limite_ini:limite_fim])
            if alvo and len(alvo & janela) / len(alvo) >= LIMIAR_NUCLEO:
                return True
            if not alvo:
                return True  # frase sem palavras úteis na mesma data: tratada como repetida
        return False


def _frases_dos_eventos(ficha, eventos, profundidade, provedor, alertas, capa_diz_distribuicao=False):
    """Frases (uma por evento aproveitável) das camadas de movimentos e documentos.
    `profundidade` None = tudo (uso incremental: quem chama já escolheu os eventos)."""
    com_documentos = profundidade in (None, "padrao", "completo")
    candidatos = [e for e in eventos or [] if e.get("status") != "descartado"]
    docs_do_dia = {_data_do_evento(e) for e in candidatos if e.get("tipo_evento") == "documento"
                   and (profundidade in (None, "completo") or _documento_chave(e))} if com_documentos else set()
    frases, vistos = [], set()
    for idx, ev in enumerate(candidatos):
        tipo = ev.get("tipo_evento")
        if tipo == "movimento":
            titulo = ev.get("titulo") or ""
            if ev.get("status") not in ("rascunho", "aprovado", "relatado") and _eh_rotina_texto(_texto_do_movimento(titulo)):
                continue
            if _data_do_evento(ev) in docs_do_dia and resumir.ATO_JUDICIAL.search(titulo) \
                    and ev.get("status") not in APROVADO:
                continue  # o documento do mesmo dia já conta o ato (mesma regra de resumir.marcar_repetidos)
            if capa_diz_distribuicao and re.match(r"distribu[ií]d|juntada de peti[cç][aã]o de peti[cç][aã]o inicial", titulo, re.I):
                continue  # a capa já diz quando a ação foi distribuída
            camada = "movimentos"
        elif tipo == "documento":
            if not com_documentos or (profundidade == "padrao" and not _documento_chave(ev)):
                continue
            camada = "documentos"
        else:
            continue
        visao = _visao_do_evento(ficha, ev, provedor, alertas)
        if visao is None:
            continue
        if (capa_diz_distribuicao and tipo == "documento" and not visao["conteudo"]
                and re.search(r"inicial", ev.get("tipo") or "", re.I)):
            continue  # sem resumo, "foi juntada a inicial" só repete o que a capa já disse
        texto = planilha.frase_planilha(visao)
        iso = _iso(visao["data"])
        chave = (iso, frozenset(_nucleo(texto)) or texto)
        if chave in vistos:
            continue  # mesma informação no mesmo dia
        vistos.add(chave)
        frases.append({"data": iso, "texto": texto, "camada": camada, "origem": {"evento": ev.get("id") or ev.get("titulo")},
                       "ordem": (iso, relatorio.ordem(visao)[1], CAMADA_ORDEM[camada], idx), "_evento": ev})
    return frases


def _frases_da_capa(ficha):
    """Camada de capa: só campos da ficha que têm origem. Sem data de ajuizamento nem vara, nada."""
    frases = []

    def campo(nome):
        return fch.obter(ficha, nome) if fch.origem(ficha, nome) else None

    vara, municipio, uf = campo("vara"), campo("municipio"), campo("uf")
    onde = ", ".join(x for x in (municipio, uf) if x) if not (municipio and uf) else f"{municipio}/{uf}"
    local = (f" perante a {vara}" if vara else "") + (f", em {onde}" if onde and vara else (f" em {onde}" if onde else ""))
    ajuizamento, citacao = campo("data_ajuizamento"), campo("data_citacao")
    if ajuizamento and local:
        frases.append({"data": ajuizamento, "texto": f"Em {_br(ajuizamento)} foi distribuída a ação{local}.",
                       "camada": "capa", "origem": {"campo": "data_ajuizamento", "origem_do_campo": fch.origem(ficha, "data_ajuizamento")}})
    elif ajuizamento:
        frases.append({"data": ajuizamento, "texto": f"Em {_br(ajuizamento)} foi distribuída a ação.", "camada": "capa",
                       "origem": {"campo": "data_ajuizamento", "origem_do_campo": fch.origem(ficha, "data_ajuizamento")}})
    elif local:
        frases.append({"data": None, "texto": f"A ação tramita{local}.", "camada": "capa",
                       "origem": {"campo": "vara", "origem_do_campo": fch.origem(ficha, "vara")}})
    if citacao:
        frases.append({"data": citacao, "texto": f"Em {_br(citacao)} foi realizada a citação.", "camada": "capa",
                       "origem": {"campo": "data_citacao", "origem_do_campo": fch.origem(ficha, "data_citacao")}})
    for i, f in enumerate(frases):
        f["ordem"] = (f["data"] or "", "", CAMADA_ORDEM["capa"], -10 + i)
    return frases


def _montar(frases):
    """Texto corrido em ordem cronológica e as frases sem campos internos."""
    frases = sorted(frases, key=lambda f: f["ordem"])
    texto = " ".join(f["texto"] for f in frases)
    limpas = [{k: v for k, v in f.items() if k not in ("ordem", "_evento")} for f in frases]
    return texto, limpas


def _marcar_eventos(frases, profundidade):
    for f in frases:
        ev = f.get("_evento")
        if ev is None:
            continue
        ev.setdefault("motor", "regra")
        if profundidade:
            ev.setdefault("profundidade", profundidade)


def _texto_da_base(ficha):
    base = ficha.get("linha_de_base") or {}
    return (base.get("andamentos_texto") or "").strip()


def _filtrar_contra_existente(frases, existente):
    """(novas, ignoradas): tira o que já consta (data + núcleo) e o que é anterior ao último texto gravado."""
    novas, ignoradas = [], []
    for f in frases:
        ev = f.get("_evento") or {}
        ident = f["origem"].get("evento")
        if existente.ja_consta(f["data"], f["texto"]):
            ignoradas.append({"evento": ident, "numero": ev.get("numero"), "codigo": "andamento_ja_presente",
                              "motivo": f"Já consta do texto existente ({_br(f['data'])})."})
        elif existente.ultima and f["data"] and f["data"] < existente.ultima:
            ignoradas.append({"evento": ident, "numero": ev.get("numero"), "codigo": "andamento_anterior_ao_texto",
                              "motivo": f"Anterior ao último andamento do texto existente ({_br(existente.ultima)}): "
                                        "não foi acrescentado, conferir à mão."})
        else:
            novas.append(f)
    return novas, ignoradas


# --------------------------------------------------------------------------------------- narrativa

def detalhar_inicial(ficha, eventos, profundidade="padrao", provedor=None):
    """Como narrativa_inicial, mas devolve {"texto", "frases", "ignorados", "alertas"}."""
    if profundidade not in PROFUNDIDADES:
        raise ValueError(f"Profundidade desconhecida: {profundidade!r} (use {', '.join(PROFUNDIDADES)})")
    alertas, ignorados = [], []
    historico = _texto_da_base(ficha)
    capa = [] if historico else _frases_da_capa(ficha)
    frases = _frases_dos_eventos(ficha, eventos, profundidade, provedor, alertas,
                                 capa_diz_distribuicao=any(c["origem"]["campo"] == "data_ajuizamento" for c in capa))
    if historico:  # relatório migrado: o histórico fica como está; só entra o que veio depois
        frases, ignorados = _filtrar_contra_existente(frases, _TextoExistente(historico))
        texto, limpas = _montar(frases)
        _marcar_eventos(frases, profundidade)
        return {"texto": f"{historico} {texto}".strip(), "frases": limpas, "ignorados": ignorados, "alertas": alertas}
    if not capa and not frases:
        alertas.append("Não há dados de capa nem eventos com origem para montar a narrativa.")
    texto, limpas = _montar(capa + frases)
    _marcar_eventos(frases, profundidade)
    return {"texto": texto, "frases": limpas, "ignorados": ignorados, "alertas": alertas}


def narrativa_inicial(ficha, eventos, profundidade="padrao", provedor=None):
    """Texto de andamentos do relatório inicial (capa -> movimentos -> documentos-chave, cronológico).
    Ver o cabeçalho do módulo para o que cada profundidade inclui. Eventos usados recebem `motor`/`profundidade`."""
    return detalhar_inicial(ficha, eventos, profundidade, provedor)["texto"]


def detalhar_incremental(ficha, eventos_novos):
    """Como narrativa_incremental, mas devolve {"texto", "frases", "ignorados", "alertas"}."""
    alertas = []
    gravado = (ficha.get("ultimo_texto_gravado") or {}).get("texto") or ""
    existente = _TextoExistente(_texto_da_base(ficha), gravado)
    frases = _frases_dos_eventos(ficha, eventos_novos, None, None, alertas)
    novas, ignorados = _filtrar_contra_existente(frases, existente)
    texto, limpas = _montar(novas)
    _marcar_eventos(novas, None)
    return {"texto": texto, "frases": limpas, "ignorados": ignorados, "alertas": alertas}


def narrativa_incremental(ficha, eventos_novos):
    """Só o texto a ACRESCENTAR depois do último gravado (vazio se não há novidade: nesse caso quem grava o
    arquivo coloca o fecho). Nunca repete o que consta em ficha["ultimo_texto_gravado"] ou na linha de base."""
    return detalhar_incremental(ficha, eventos_novos)["texto"]
