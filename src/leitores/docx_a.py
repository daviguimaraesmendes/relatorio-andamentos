"""Leitor do modelo A (relatório em texto, `.docx` exportado do Google Docs) -- WS-2.

O que o modelo A tem e o que este leitor extrai (CONTRATOS §4):

    título do documento (cliente)                      -> RelatorioLido["cliente"] (e campo `cliente` de cada processo)
    "Data-Base: DD/MM/AAAA"                            -> RelatorioLido["data_base"]
    quadro-resumo de 4 colunas (Nº DO PROCESSO | ASSUNTO | MOMENTO ATUAL DO PROCESSO | ÚLTIMO ANDAMENTO)
    uma tabela por processo: título "PROCESSO Nº ... [ MOMENTO ATUAL ]" (vários números = principal + vinculados),
        Assunto, Autor(es), Réu(s), Ajuizamento, Valor da Causa, Data de citação, Juízo, Área do Direito,
        Matéria Principal e "Andamentos:" (texto corrido com as datas em negrito)

Decisões (leia antes de mudar):

- Os números do título: o primeiro é o principal; os demais são vinculados e o tipo sai do rótulo antes do número
  ("AGRAVO DE INSTRUMENTO Nº", "APENSO Nº") ou, na falta dele, do rótulo no quadro-resumo ("Agravo: ..."). Sem rótulo
  em lugar nenhum: tipo 'apenso' e aviso `vinculo_tipo_indefinido`. Dígito verificador errado no principal recusa o
  processo (aviso `numero_dv_invalido`); o mesmo número em dois blocos é mantido nos dois, com aviso `numero_repetido`.
- Momento atual: vem do colchete do título; se faltar, do quadro-resumo. Qualificador entre parênteses
  ("CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)") sai do campo e vai em `momento_qualificador` (chave aditiva do
  ProcessoLido). Rótulo que não está no vocabulário NÃO é gravado (aviso `momento_fora_do_vocabulario` com candidatos).
  Título e quadro-resumo divergindo: vale o título, com aviso `momento_divergente`.
- `andamentos_texto`: os parágrafos da célula "Andamentos" unidos por espaço, SEM a frase final de fecho
  ("Em DD/MM/AAAA, sem atualizações."); a data do fecho vai em `fecho` (chave aditiva), porque o fecho é recalculado a
  cada ciclo (CONTRATOS §5, exceções mecânicas) e não faz parte do histórico.
- `ultimo_andamento`: a maior data dos andamentos ("Em DD/MM/AAAA ..." no começo de frase). O fecho e as datas no meio
  da frase (audiências e prazos futuros) não contam. Se o quadro-resumo traz outra data: aviso
  `ultimo_andamento_divergente` (vale a do texto; sem texto datado, vale a do quadro-resumo).
- `andamentos` (chave aditiva): [{"data", "texto", "data_em_negrito"}] de cada frase datada.
- Linha de rótulo desconhecido dentro de um bloco ("Valor Provisionado | ...") vai para `colunas_sem_destino`.
- Linha do quadro-resumo sem bloco correspondente vira processo só com os dados do quadro (aviso `resumo_sem_bloco`).

Tolerância à exportação do Google Docs: texto fragmentado em vários runs (até no meio da data), espaço não separável,
parágrafos vazios, tabelas dentro de células ou de controles de conteúdo (`w:sdt`), células mescladas (`gridSpan`,
`vMerge`: a linha de continuação de "Réu(s)" soma o valor ao campo), "Andamentos:" com o texto na linha de baixo,
rótulos com ou sem dois-pontos. Revisões do documento: texto inserido (`w:ins`) conta, texto apagado (`w:del`) não, e
um aviso `revisoes_no_documento` diz que há controle de alterações.

Limites: negrito só é reconhecido quando está direto no run (como o Google exporta), não por estilo nomeado; dois
processos num mesmo bloco, caixas de texto e números sem pontuação CNJ parcial não são tratados.
"""
import re
import zipfile
from pathlib import Path

from lxml import etree

import ficha

from . import base, grade

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
LIMITE_PARTE = 200 * 1024 * 1024
DATA_BASE = re.compile(r"Data[\s\-–]*Base\s*:?\s*(.*)", re.I)
COLCHETE = re.compile(r"\[\s*([^\[\]]*?)\s*\]")
CAMPOS_BLOCO_IGNORADOS = {"numero", "tribunal", "ativo"}


def w(tag):
    return f"{{{W_NS}}}{tag}"


def _nome(el):
    return etree.QName(el).localname if isinstance(el.tag, str) else None


# ---------------------------------------------------------------- texto e formatação

def _negrito(rpr):
    if rpr is None:
        return False
    b = rpr.find(w("b"))
    return b is not None and str(b.get(w("val"), "1")).lower() not in ("0", "false", "off")


def _pedacos(par):
    """[(texto, negrito)] do parágrafo, na ordem. Conta runs diretos e os de hyperlink, inserção e controle de conteúdo;
    ignora texto apagado (w:delText), instruções de campo e caixas de texto."""
    saida = []

    def percorrer(no):
        for filho in no:
            n = _nome(filho)
            if n == "r":
                neg = _negrito(filho.find(w("rPr")))
                for x in filho:
                    nx = _nome(x)
                    if nx == "t":
                        saida.append((x.text or "", neg))
                    elif nx == "tab":
                        saida.append((" ", neg))
                    elif nx in ("br", "cr"):
                        saida.append(("\n", neg))
                    elif nx == "noBreakHyphen":
                        saida.append(("-", neg))
            elif n in ("hyperlink", "ins", "smartTag", "sdt", "sdtContent", "fldSimple", "customXml", "moveTo"):
                percorrer(filho)

    percorrer(par)
    return saida


def _limpo(texto):
    return re.sub(r"[​‌‍﻿­]", "", texto.replace("\xa0", " "))


def _texto_par(par):
    return _limpo("".join(t for t, _ in _pedacos(par)))


def _paragrafos(el):
    """Parágrafos do elemento em ordem de documento, descendo em tabelas, linhas, células e controles de conteúdo."""
    for filho in el:
        n = _nome(filho)
        if n == "p":
            yield filho
        elif n in ("tbl", "tr", "tc", "sdt", "sdtContent", "customXml"):
            yield from _paragrafos(filho)


def _linhas(tbl):
    return [r for r in tbl if _nome(r) == "tr"]


def _celulas(tr):
    return [c for c in tr if _nome(c) == "tc"]


def _texto_celula(tc, sep="\n"):
    return sep.join(t for t in (_texto_par(p).strip() for p in _paragrafos(tc)) if t)


def _texto_linha(tr):
    return " ".join(_texto_celula(tc, " ") for tc in _celulas(tr))


def _vmerge_continuacao(tc):
    tcpr = tc.find(w("tcPr"))
    vm = tcpr.find(w("vMerge")) if tcpr is not None else None
    return vm is not None and str(vm.get(w("val"), "continue")).lower() == "continue"


# ---------------------------------------------------------------- estrutura do documento

def _eh_cab_resumo(tr):
    k = base.chave(_texto_linha(tr))
    return "momento atual" in k and "ultimo andamento" in k


def _rotulos_conhecidos(linhas):
    achados = set()
    for tr in linhas:
        for tc in _celulas(tr):
            d = grade.destino_exato(_texto_celula(tc, " "))
            if d and d not in CAMPOS_BLOCO_IGNORADOS:
                achados.add(d)
    return achados


def _classificar(tbl):
    linhas = _linhas(tbl)
    if not linhas:
        return None
    if any(_eh_cab_resumo(tr) for tr in linhas[:3]):
        return "resumo"
    primeira = next((tr for tr in linhas if _texto_linha(tr).strip()), None)
    if primeira is not None and base.achar_numeros(_texto_linha(primeira)):
        rotulos = _rotulos_conhecidos(linhas)
        if "andamentos" in rotulos or len(rotulos) >= 2:
            return "bloco"
    return None


class _Estrutura:
    """Tabelas do documento já classificadas (resumo, blocos) e os parágrafos soltos (título, data-base)."""

    def __init__(self, raiz):
        self.body = raiz.find(w("body"))
        self.itens = []            # (ordem, tbl, "resumo" | "bloco")
        self.soltos = []           # parágrafos fora do resumo e dos blocos
        self.ordem = 0
        self.revisoes = any(True for tag in ("ins", "del", "moveFrom", "moveTo") for _ in raiz.iter(w(tag)))
        if self.body is not None:
            self._varrer(self.body)

    def _varrer(self, container):
        for filho in container:
            n = _nome(filho)
            if n == "p":
                self.soltos.append(filho)
            elif n == "sdt":
                conteudo = filho.find(w("sdtContent"))
                if conteudo is not None:
                    self._varrer(conteudo)
            elif n == "tbl":
                self.ordem += 1
                tipo = _classificar(filho)
                if tipo:
                    self.itens.append((self.ordem, filho, tipo))
                else:
                    for tr in _linhas(filho):
                        for tc in _celulas(tr):
                            self._varrer(tc)

    def resumo(self):
        return next(((o, t) for o, t, tipo in self.itens if tipo == "resumo"), None)

    def blocos(self):
        return [(o, t) for o, t, tipo in self.itens if tipo == "bloco"]

    def data_base(self):
        for p in self.soltos:
            m = DATA_BASE.search(_texto_par(p))
            if m:
                datas = base.datas_no_texto(m.group(1))
                return datas[0][0].isoformat() if datas else None
        return None

    def cliente(self):
        for p in self.soltos:
            t = base.limpar_texto(_texto_par(p))
            if t and not DATA_BASE.search(t):
                return re.sub(r"\s+", " ", t)
        return None


def _carregar(caminho):
    """-> (raiz | None, aviso | None)"""
    nome = Path(caminho).name
    try:
        with zipfile.ZipFile(str(caminho)) as z:
            info = z.getinfo("word/document.xml")
            if info.file_size > LIMITE_PARTE:
                return None, base.aviso("erro", "arquivo_muito_grande", nome, "O documento é grande demais para ser lido.")
            dados = z.read("word/document.xml")
        parser = etree.XMLParser(resolve_entities=False, no_network=True, huge_tree=False)
        raiz = etree.fromstring(dados, parser)
    except Exception as e:      # noqa: BLE001 -- zip inválido, parte ausente, XML quebrado: tudo é "arquivo ilegível"
        return None, base.aviso("erro", "arquivo_ilegivel", nome,
                                f"Não foi possível abrir o .docx (arquivo corrompido ou não é um documento Word): {type(e).__name__}.")
    if raiz.find(w("body")) is None:
        return None, base.aviso("erro", "arquivo_ilegivel", nome, "O documento não tem corpo de texto.")
    return raiz, None


def reconhecer(caminho):
    """Para o detector: -> (eh_modelo_a, aviso | None). Modelo A = ao menos um bloco de processo com a linha de
    andamentos e (data-base, quadro-resumo ou título)."""
    raiz, erro = _carregar(caminho)
    if raiz is None:
        return False, erro
    est = _Estrutura(raiz)
    if not est.blocos():
        return False, None
    return bool(est.resumo() or est.data_base() or est.cliente()), None


def texto_simples(caminho):
    """Texto de todo o documento (parágrafos e células), para o leitor de lista. -> (texto | None, aviso | None)"""
    raiz, erro = _carregar(caminho)
    if raiz is None:
        return None, erro
    return "\n".join(_texto_par(p) for p in _paragrafos(raiz.find(w("body")))), None


# ---------------------------------------------------------------- bloco de processo

def _campo_do_bloco(texto_rotulo):
    d = grade.destino_exato(texto_rotulo)
    return None if d in CAMPOS_BLOCO_IGNORADOS else d


def _ler_bloco(tbl):
    """-> {"titulo", "valores": {campo: [texto]}, "andamentos": [parágrafos de runs], "desconhecidos": {rotulo: [texto]}}"""
    linhas = _linhas(tbl)
    primeira = next(i for i, tr in enumerate(linhas) if _texto_linha(tr).strip())
    saida = {"titulo": _texto_linha(linhas[primeira]), "valores": {}, "andamentos": [], "desconhecidos": {}}
    anterior, pular_proxima, esperando_texto = None, False, False
    for ri in range(primeira + 1, len(linhas)):
        if pular_proxima:
            pular_proxima = False
            continue
        cels = _celulas(linhas[ri])
        textos = [_texto_celula(tc, "; ") for tc in cels]
        if esperando_texto and cels:
            saida["andamentos"] = list(_paragrafos(cels[0]))
            esperando_texto = False
            continue
        if cels and _vmerge_continuacao(cels[0]) and not textos[0].strip() and anterior and len(cels) >= 2:
            extra = " ".join(t for t in textos[1:] if t.strip())
            if extra and anterior != "andamentos":
                saida["valores"].setdefault(anterior, []).append(extra)
            continue
        i = 0
        while i < len(cels):
            t = textos[i].strip()
            campo = _campo_do_bloco(t) if t else None
            if campo:
                anterior = campo
                if campo == "andamentos":
                    if i + 1 < len(cels):
                        saida["andamentos"] = list(_paragrafos(cels[i + 1]))
                    else:
                        esperando_texto = True       # variante: "Andamentos:" numa linha e o texto na de baixo
                elif i + 1 < len(cels):
                    valor = textos[i + 1].strip()
                    if valor:
                        saida["valores"].setdefault(campo, []).append(valor)
                i += 2
            elif t and i + 1 < len(cels) and textos[i + 1].strip() and len(t) <= 60:
                saida["desconhecidos"].setdefault(t.rstrip(":"), []).append(textos[i + 1].strip()[:80])
                anterior = None
                i += 2
            else:
                i += 1
    return saida


def _texto_e_negrito(paragrafos):
    """Une os parágrafos (espaço entre eles), colapsa espaços e devolve (texto, [negrito por caractere])."""
    chars = []
    for p in paragrafos:
        piece = [(c, neg) for t, neg in _pedacos(p) for c in _limpo(t)]
        if not any(c.strip() for c, _ in piece):
            continue
        if chars:
            chars.append((" ", False))
        chars.extend(piece)
    saida = []
    for c, neg in chars:
        if c.isspace():
            if saida and saida[-1][0] != " ":
                saida.append((" ", False))
        else:
            saida.append((c, neg))
    while saida and saida[-1][0] == " ":
        saida.pop()
    texto = "".join(c for c, _ in saida)
    return texto, [n for _, n in saida]


# ---------------------------------------------------------------- quadro-resumo

def _ler_resumo(tbl):
    linhas = _linhas(tbl)
    cab = next(i for i, tr in enumerate(linhas) if _eh_cab_resumo(tr))
    chaves = [base.chave(_texto_celula(tc, " ")) for tc in _celulas(linhas[cab])]

    def achar(*termos):
        return next((i for i, k in enumerate(chaves) if any(t in k for t in termos)), None)

    col = {"numero": achar("processo", "numero"), "assunto": achar("assunto"), "momento": achar("momento"),
           "ultimo": achar("ultimo")}
    if col["numero"] is None:
        col["numero"] = 0
    itens = []
    for ri in range(cab + 1, len(linhas)):
        cels = _celulas(linhas[ri])
        if not cels:
            continue

        def get(k):
            j = col[k]
            return _texto_celula(cels[j]) if j is not None and j < len(cels) else ""

        texto_numeros = get("numero")
        if not base.achar_numeros(texto_numeros):
            continue
        itens.append({"numeros": texto_numeros, "assunto": get("assunto"), "momento": get("momento"),
                      "ultimo": get("ultimo"), "linha": ri + 1})
    return itens


# ---------------------------------------------------------------- leitura

def _momento(bruto_titulo, bruto_resumo, onde, avisos):
    """Escolhe o momento atual entre o colchete do título e o quadro-resumo. -> (valor | None, qualificador | None)"""
    ct = base.converter_campo("momento_atual", bruto_titulo) if bruto_titulo else None
    cr = base.converter_campo("momento_atual", bruto_resumo) if bruto_resumo else None
    escolhido = ct if ct and ct["valor"] else cr
    mesmo_texto = bruto_titulo and bruto_resumo and base.chave(bruto_titulo) == base.chave(bruto_resumo)
    for c in (ct, cr if not mesmo_texto else None):
        if c:
            avisos.extend(base.aviso(n, cod, onde, m, cand) for n, cod, m, cand in c["avisos"])
    if ct and cr and ct["valor"] and cr["valor"] and (
            ct["valor"] != cr["valor"] or ct["extras"].get("momento_qualificador") != cr["extras"].get("momento_qualificador")):
        avisos.append(base.aviso("atencao", "momento_divergente", onde,
                                 f"O momento atual do título ({bruto_titulo.strip()!r}) difere do quadro-resumo "
                                 f"({bruto_resumo.strip()!r}); foi usado o do título.", [bruto_titulo.strip(), bruto_resumo.strip()]))
    if escolhido is None or escolhido["valor"] is None:
        return None, None
    return escolhido["valor"], escolhido["extras"].get("momento_qualificador")


def _numeros_do_bloco(titulo, resumo_item, onde, avisos):
    """Principal e vinculados de um bloco: título primeiro, quadro-resumo para os tipos que o título não diz."""
    principal, vinculados, av = base.interpretar_numeros(titulo, onde, avisar_indefinido=False)
    avisos.extend(av)
    if principal is None:
        return None, []
    tipos_resumo = {}
    if resumo_item:
        _, v_resumo, _ = base.interpretar_numeros(resumo_item["numeros"], onde, avisar_indefinido=False)
        tipos_resumo = {v["numero"]: v["tipo"] for v in v_resumo}
        so_resumo = [v for v in v_resumo if v["numero"] not in {x["numero"] for x in vinculados} and v["numero"] != principal]
        if so_resumo:
            avisos.append(base.aviso("info", "numeros_divergentes", onde,
                                     "O quadro-resumo lista número(s) que não estão no título do bloco; foram acrescentados como vinculados.",
                                     [v["numero"] for v in so_resumo]))
            vinculados = vinculados + so_resumo
    finais = []
    for v in vinculados:
        tipo = v["tipo"] or tipos_resumo.get(v["numero"])
        if tipo is None:
            avisos.append(base.aviso("atencao", "vinculo_tipo_indefinido", onde,
                                     f"Não ficou claro se {v['numero']} é agravo, apenso ou recurso do principal; "
                                     "marcado como 'apenso'. Confira.", [v["numero"]]))
            tipo = "apenso"
        finais.append({"numero": v["numero"], "tipo": tipo})
    return principal, finais


def _datas_em_negrito(texto, negrito, analise):
    saida = []
    for a in analise["andamentos"]:
        trecho = texto[a["inicio"]:a["data_fim"]]
        m = re.search(base._DATA + r"$", trecho)
        if m:
            ini = a["inicio"] + m.start()
            fim = a["inicio"] + m.end()
            marcado = all(n for c, n in zip(texto[ini:fim], negrito[ini:fim]) if c.strip())
        else:
            marcado = False
        saida.append({"data": a["data"], "texto": a["texto"], "data_em_negrito": marcado})
    return saida


def ler(caminho, mapeamento=None):
    """RelatorioLido do modelo A. Nunca levanta exceção para arquivo ruim (aviso `arquivo_ilegivel`)."""
    caminho = Path(caminho)
    rel = base.novo_relatorio("docx_a", caminho.name)
    raiz, erro = _carregar(caminho)
    if raiz is None:
        rel["avisos"].append(erro)
        return rel
    est = _Estrutura(raiz)
    avisos = rel["avisos"]
    rel["cliente"] = est.cliente()
    rel["data_base"] = est.data_base()
    if rel["data_base"] is None:
        avisos.append(base.aviso("info", "data_base_ausente", caminho.name,
                                 "Não foi encontrada a linha 'Data-Base: DD/MM/AAAA'; a data-base ficou em branco."))
    if est.revisoes:
        avisos.append(base.aviso("info", "revisoes_no_documento", caminho.name,
                                 "O documento tem alterações controladas (inserções/exclusões): o texto inserido foi lido, o apagado foi ignorado."))
    resumo_itens = []
    resumo = est.resumo()
    if resumo is None:
        avisos.append(base.aviso("atencao", "quadro_resumo_ausente", caminho.name,
                                 "O quadro-resumo (Nº do processo / Assunto / Momento atual / Último andamento) não foi encontrado; "
                                 "só os blocos por processo foram lidos."))
    else:
        resumo_itens = _ler_resumo(resumo[1])
    por_numero = {}
    for item in resumo_itens:
        for o in base.achar_numeros(item["numeros"]):
            por_numero.setdefault(o["numero"], item)
    usados = set()
    desconhecidos = {}
    cliente = rel["cliente"]
    for ordem, tbl in est.blocos():
        onde = f"tabela {ordem}"
        bloco = _ler_bloco(tbl)
        item = next((por_numero[o["numero"]] for o in base.achar_numeros(bloco["titulo"]) if o["numero"] in por_numero), None)
        av_bloco = []
        principal, vinculados = _numeros_do_bloco(bloco["titulo"], item, onde, av_bloco)
        # dedupe: o mesmo número com dígito errado pode aparecer no título e no quadro-resumo
        for a in av_bloco:
            if a["codigo"] == "numero_dv_invalido" and any(
                    b["codigo"] == a["codigo"] and b["candidatos"][:1] == a["candidatos"][:1] for b in avisos):
                continue
            avisos.append(a)
        if item is not None:
            usados.add(id(item))
        if principal is None:
            continue
        campos = {}
        if cliente:
            campos["cliente"] = base.montar_campo("cliente", cliente, "migrado")
        for campo, textos in bloco["valores"].items():
            conv = base.converter_campo(campo, "; ".join(textos))
            avisos.extend(base.aviso(n, c, f"{onde}, {ficha.CAMPOS[campo][0] if campo in ficha.CAMPOS else campo}", m, cand)
                          for n, c, m, cand in conv["avisos"])
            if conv["valor"] is not None:
                campos[campo] = base.montar_campo(campo, conv["valor"], base.origem_do_campo(campo))
        if item and "assunto" not in campos and item["assunto"].strip():
            conv = base.converter_campo("assunto", item["assunto"])
            if conv["valor"]:
                campos["assunto"] = base.montar_campo("assunto", conv["valor"], "migrado")
        m = COLCHETE.findall(bloco["titulo"])
        momento, qualificador = _momento(m[-1] if m else "", item["momento"] if item else "", onde, avisos)
        if momento:
            campos["momento_atual"] = base.montar_campo("momento_atual", momento, "migrado")
        # andamentos
        if bloco["andamentos"]:
            texto, negrito = _texto_e_negrito(bloco["andamentos"])
            analise = base.analisar_andamentos(texto)
            avisos.extend(base.aviso(n, c, onde, msg) for n, c, msg in analise["avisos"])
            andamentos_texto, ultimo, fecho = analise["texto"], analise["ultimo"], analise["fecho"]
            lista = _datas_em_negrito(texto, negrito, analise)
        else:
            avisos.append(base.aviso("atencao", "bloco_sem_andamentos", onde,
                                     f"O bloco do processo {principal} não tem a linha 'Andamentos:' ou ela está vazia."))
            andamentos_texto, ultimo, fecho, lista = "", None, None, []
        ultimo_resumo = None
        if item and item["ultimo"].strip():
            ultimo_resumo, problema = base.converter_data(item["ultimo"])
            if problema:
                avisos.append(base.aviso("atencao", "data_invalida", f"{onde}, último andamento do quadro-resumo",
                                         f"Último andamento {item['ultimo'].strip()!r} no quadro-resumo não é uma data válida."))
        if ultimo and ultimo_resumo and ultimo != ultimo_resumo:
            avisos.append(base.aviso("atencao", "ultimo_andamento_divergente", onde,
                                     f"O último andamento do texto ({ficha.data_br(ultimo)}) difere do quadro-resumo "
                                     f"({ficha.data_br(ultimo_resumo)}); foi usado o do texto.", [ultimo, ultimo_resumo]))
        ultimo = ultimo or ultimo_resumo
        for rotulo, valores in bloco["desconhecidos"].items():
            desconhecidos.setdefault(rotulo, []).extend(valores)
        rel["processos"].append(base.processo_lido(principal, campos, vinculados, andamentos_texto, ultimo, onde,
                                                   fecho=fecho, andamentos=lista, momento_qualificador=qualificador))
    # linhas do quadro-resumo sem bloco
    for item in resumo_itens:
        if id(item) in usados:
            continue
        onde = f"tabela {resumo[0]}, linha {item['linha']}"
        av = []
        principal, vinculados = _numeros_do_bloco(item["numeros"], item, onde, av)
        for a in av:
            if a["codigo"] == "numero_dv_invalido" and any(
                    b["codigo"] == a["codigo"] and b["candidatos"][:1] == a["candidatos"][:1] for b in avisos):
                continue
            avisos.append(a)
        if principal is None:
            continue
        campos = {}
        if cliente:
            campos["cliente"] = base.montar_campo("cliente", cliente, "migrado")
        conv = base.converter_campo("assunto", item["assunto"])
        if conv["valor"]:
            campos["assunto"] = base.montar_campo("assunto", conv["valor"], "migrado")
        momento, qualificador = _momento("", item["momento"], onde, avisos)
        if momento:
            campos["momento_atual"] = base.montar_campo("momento_atual", momento, "migrado")
        ultimo, problema = base.converter_data(item["ultimo"])
        avisos.append(base.aviso("atencao", "resumo_sem_bloco", onde,
                                 f"O processo {principal} só consta no quadro-resumo (não há bloco com andamentos); "
                                 "foram lidos apenas os dados do quadro.", [principal]))
        rel["processos"].append(base.processo_lido(principal, campos, vinculados, "", ultimo, onde,
                                                   momento_qualificador=qualificador))
    rel["colunas_sem_destino"] = [{"coluna": r, "amostra": v[:3]} for r, v in desconhecidos.items()]
    if not rel["processos"] and not any(a["nivel"] == "erro" for a in avisos):
        avisos.append(base.aviso("erro", "formato_nao_reconhecido", caminho.name,
                                 "O documento não tem blocos de processo no modelo A (tabelas com título 'PROCESSO Nº ...')."))
    return base.finalizar(rel)
