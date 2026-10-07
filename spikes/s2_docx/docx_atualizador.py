"""SPIKE S2: protótipo do escritor DOCX do modelo A (futuro src/escritores/docx_a.py).

Ler, atualizar e gerar o relatório em texto (.docx exportado de um Google Doc):
título (cliente), "Data-Base: DD/MM/AAAA", quadro-resumo de 4 colunas e uma
tabela por processo, cuja linha "Andamentos:" tem um texto corrido com as datas
em negrito, terminando por "Em DD/MM/AAAA, sem atualizações.".

Princípios (PLANO.md 3.3 e CONTRATOS.md 5):
- EDIÇÃO CIRÚRGICA DO PACOTE, como o planilha.py: só word/document.xml é
  reescrito; todas as outras partes do .zip (estilos, tema, mídia, comentários,
  cabeçalhos...) são copiadas byte a byte. Sem python-docx na gravação (só lxml).
- SÓ ACRESCENTA: o texto de andamentos ganha frases no fim; o que o advogado
  escreveu não é reescrito. As únicas coisas que o sistema troca são campos
  mecânicos: Data-Base, "momento atual", "último andamento" (resumo e título) e
  a frase de fecho.
- O ORIGINAL NUNCA É SOBRESCRITO (destino != molde, destino não pode existir).
- IDEMPOTENTE: aplicar a mesma atualização duas vezes não duplica nada.
- Nada se perde em silêncio: tudo que não deu para fazer vira aviso.

API:
    ler_estrutura(docx) -> dict
    atualizar(origem, destino, atualizacoes, data_base, **opcoes) -> Resultado
    gerar(destino, relatorio) -> Resultado
    gravar(molde, estado, destino, **opcoes) -> Resultado     # contrato de CONTRATOS.md 5
    verificar_coerencia(docx) -> [str]                         # resumo x blocos x fecho x data-base

Datas: dentro do arquivo, DD/MM/AAAA; as funções aceitam também ISO e date.
Este protótipo só foi exercitado com python-docx, lxml e LibreOffice: NÃO foi
aberto no Word nem no Google Docs.
"""
import copy
import datetime
import json
import os
import re
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
PARTE_DOCUMENTO = "word/document.xml"
CNJ = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")
DATA = r"\d{2}/\d{2}/\d{4}"
# "Em 18/09/2026, sem atualizações." (e variantes), no FIM do texto; tolerante a espaços e maiúsculas
FECHO = re.compile(r"(?:Em|Até)\s+(" + DATA + r")\s*,?\s*sem\s+(?:novas\s+)?"
                   r"(?:atualiza(?:ções|coes|ção|cao)|andamentos?|movimenta(?:ções|coes))\s*\.?\s*$", re.I)
INICIO_ANDAMENTO = re.compile(r"\b(Em|Até)\s+(" + DATA + r")\s*,?\s*")   # case-sensitive: "em 10/10/2026" no meio da frase não conta
DATA_BASE_RE = re.compile(r"(Data[-\s]*Base\s*:\s*)(" + DATA + ")", re.I)
COLCHETE = re.compile(r"\[(\s*)([^\]]*?)(\s*)\]")
ROTULOS = {"assunto": "assunto", "autor(es)": "autores", "autores": "autores", "autor": "autores",
           "reu(s)": "reus", "reus": "reus", "reu": "reus", "ajuizamento": "ajuizamento",
           "valor da causa": "valor_causa", "data de citacao": "data_citacao", "juizo": "juizo",
           "area do direito": "area", "materia principal": "materia", "andamentos": "andamentos"}
CAMPOS_FICHA_DO_BLOCO = ("assunto", "autores", "reus", "ajuizamento", "valor_causa", "data_citacao",
                         "juizo", "area", "materia", "andamentos")
# formatações do "run vizinho" que NÃO devem ser herdadas pelo texto novo (anotação do advogado em destaque etc.)
RPR_NAO_HERDAR = ("i", "iCs", "strike", "dstrike", "highlight", "u", "shd", "vertAlign", "bdr", "vanish")
ORDEM_RPR = ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike", "outline",
             "shadow", "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing",
             "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect", "bdr", "shd", "fitText",
             "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout", "specVanish", "oMath"]
TAGS_REVISAO = ("ins", "del", "moveFrom", "moveTo", "commentRangeStart", "commentRangeEnd", "commentReference")
MOMENTO_PADRAO_FECHO = (("Em ", ", sem atualizações."))


def w(tag):
    return f"{{{W_NS}}}{tag}"


# ------------------------------------------------------------------ textos e datas

def _sem_acento(s):
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def _chave(texto):
    """Comparação tolerante: minúsculas, sem acento, só letras/números separados por espaço."""
    return re.sub(r"[^a-z0-9]+", " ", _sem_acento(str(texto or "")).lower()).strip()


def _plano(texto):
    """Mesmo comprimento do original (posições valem nos dois): espaço não separável vira espaço."""
    return texto.replace("\xa0", " ").replace("​", " ")


def _data_br(valor):
    """'18/09/2026' | '2026-09-18' | date | datetime -> 'DD/MM/AAAA' (ou None)."""
    if valor in (None, ""):
        return None
    if isinstance(valor, datetime.datetime):
        valor = valor.date()
    if isinstance(valor, datetime.date):
        return valor.strftime("%d/%m/%Y")
    s = str(valor).strip()
    m = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})(?:[T ].*)?", s)
    if m:
        s = f"{m[3]}/{m[2]}/{m[1]}"
    if re.fullmatch(DATA, s):
        try:
            datetime.datetime.strptime(s, "%d/%m/%Y")
            return s
        except ValueError:
            return None
    return None


def _ordem_data(br):
    try:
        return datetime.datetime.strptime(br, "%d/%m/%Y")
    except (TypeError, ValueError):
        return datetime.datetime.min


def _dinheiro_br(valor):
    """'1234567.80' -> 'R$ 1.234.567,80' (texto já formatado passa direto). Em produção: ficha.dinheiro_br."""
    if valor in (None, ""):
        return ""
    s = str(valor)
    if re.fullmatch(r"-?\d+(\.\d+)?", s):
        inteiro, _, frac = f"{float(s):.2f}".partition(".")
        grupos = []
        while inteiro:
            grupos.insert(0, inteiro[-3:])
            inteiro = inteiro[:-3]
        return f"R$ {'.'.join(grupos)},{frac}"
    return s


def _ajustar_inicio(texto):
    """'O juiz proferiu...' -> 'o juiz proferiu...' (cláusula depois de 'Em DATA, '), mantém siglas; garante ponto final."""
    t = (texto or "").strip()
    if not t:
        return t
    primeira = t.split()[0].rstrip(",.;:")
    if t[0].isupper() and not (len(primeira) > 1 and primeira.isupper()):
        t = t[0].lower() + t[1:]
    return t if t[-1] in ".!?" else t + "."


# ------------------------------------------------------------------ parágrafos, runs, formatação

def _filhos(el, tag):
    return [c for c in el if c.tag == w(tag)]


def _unidades(par):
    """Elementos w:t do parágrafo, em ordem (inclui runs dentro de hyperlink/ins; exclui parágrafos aninhados em caixas de texto)."""
    saida = []
    for t in par.iter(w("t")):
        anc = t.getparent()
        while anc is not None and anc.tag != w("p"):
            anc = anc.getparent()
        if anc is par:
            saida.append(t)
    return saida


def _texto_par(par):
    return _plano("".join(t.text or "" for t in _unidades(par)))


def _texto_celula(tc):
    return "\n".join(_texto_par(p) for p in _filhos(tc, "p"))


def _texto_linha(tr):
    return " ".join(_texto_celula(tc) for tc in _filhos(tr, "tc"))


def _tem_revisao(el):
    """Controle de alterações ou comentário ancorado dentro do elemento."""
    return any(True for tag in TAGS_REVISAO for _ in el.iter(w(tag)))


def _negrito(rpr):
    if rpr is None:
        return False
    b = rpr.find(w("b"))
    return b is not None and str(b.get(w("val"), "1")).lower() not in ("0", "false", "off")


def _rpr_de(t):
    run = t.getparent()
    return run.find(w("rPr")) if run is not None and run.tag == w("r") else None


def _inserir_em_rpr(rpr, el):
    ordem = ORDEM_RPR.index(etree.QName(el).localname) if etree.QName(el).localname in ORDEM_RPR else len(ORDEM_RPR)
    for i, filho in enumerate(rpr):
        nome = etree.QName(filho).localname
        if (ORDEM_RPR.index(nome) if nome in ORDEM_RPR else len(ORDEM_RPR)) > ordem:
            rpr.insert(i, el)
            return
    rpr.append(el)


def _rpr_modelo(rpr, negrito, herdar_destaques=False):
    """Cópia do rPr do run vizinho com negrito ligado/desligado (Google repete o rPr em todo run)."""
    rpr = copy.deepcopy(rpr) if rpr is not None else _rpr_padrao()
    if not herdar_destaques:
        for tag in RPR_NAO_HERDAR:
            for el in rpr.findall(w(tag)):
                rpr.remove(el)
    el = rpr.find(w("b"))
    if negrito:
        if el is None:
            el = etree.Element(w("b"))
            _inserir_em_rpr(rpr, el)
        el.set(w("val"), "1")
    elif el is not None:
        rpr.remove(el)
    cs = rpr.find(w("bCs"))                      # negrito de script complexo: só acompanha se o modelo já tinha
    if cs is not None:
        if negrito:
            cs.set(w("val"), "1")
        else:
            rpr.remove(cs)
    return rpr


def _rpr_padrao():
    return etree.fromstring(
        f'<w:rPr xmlns:w="{W_NS}"><w:rFonts w:ascii="Arial" w:cs="Arial" w:eastAsia="Arial" w:hAnsi="Arial"/>'
        f'<w:sz w:val="22"/><w:szCs w:val="22"/></w:rPr>')


def _novo_run(texto, rpr):
    r = etree.Element(w("r"))
    if rpr is not None:
        r.append(copy.deepcopy(rpr))
    t = etree.SubElement(r, w("t"))
    t.text = texto
    t.set(f"{{{XML_NS}}}space", "preserve")
    return r


def _substituir(par, ini, fim, novo):
    """Troca o trecho [ini, fim) do texto do parágrafo por `novo`, mesmo espalhado em vários runs.
    O texto novo fica no primeiro run tocado (herda a formatação dele); nos outros só some o trecho.
    Devolve os runs tocados já limpos dos que ficaram vazios."""
    pos, colocado, tocados = 0, False, []
    for t in _unidades(par):
        txt = t.text or ""
        a, b = pos, pos + len(txt)
        pos = b
        lo, hi = max(ini, a), min(fim, b)
        if lo >= hi:
            continue
        t.text = txt[:lo - a] + (novo if not colocado else "") + txt[hi - a:]
        colocado = True
        t.set(f"{{{XML_NS}}}space", "preserve")
        tocados.append(t.getparent())
    for run in tocados:
        filhos = [c for c in run if c.tag != w("rPr")]
        if run.getparent() is not None and all(c.tag == w("t") and not (c.text or "") for c in filhos):
            run.getparent().remove(run)
    return tocados


def _rpr_no_offset(par, offset):
    pos = 0
    for t in _unidades(par):
        n = len(t.text or "")
        if pos <= offset < pos + n:
            return _rpr_de(t)
        pos += n
    return None


def _formato_no_trecho(par, ini, fim):
    """True se TODO o trecho está em negrito."""
    pos, achou = 0, False
    for t in _unidades(par):
        n = len(t.text or "")
        if min(fim, pos + n) > max(ini, pos):
            achou = True
            if not _negrito(_rpr_de(t)):
                return False
        pos += n
    return achou


def _definir_texto_celula(tc, texto, rpr_modelo=None, unico=False):
    """Põe `texto` na célula mantendo a formatação do primeiro run. unico=True descarta parágrafos extras (clones)."""
    pars = _filhos(tc, "p")
    if not pars:
        pars = [etree.SubElement(tc, w("p"))]
    alvo = next((p for p in pars if _texto_par(p).strip()), pars[0])
    if unico:
        for p in pars:
            if p is not alvo:
                tc.remove(p)
    atual = _texto_par(alvo)
    if atual:
        _substituir(alvo, 0, len(atual), texto)
    elif texto:
        alvo.append(_novo_run(texto, rpr_modelo if rpr_modelo is not None else _rpr_padrao()))
    return alvo


def _definir_paragrafos_celula(tc, linhas, rpr_modelo=None):
    """Um parágrafo por linha (clona o primeiro para herdar pPr/rPr)."""
    pars = _filhos(tc, "p")
    base = next((p for p in pars if _texto_par(p).strip()), pars[0] if pars else None)
    if base is None:
        base = etree.SubElement(tc, w("p"))
    modelo = copy.deepcopy(base)
    for p in pars:
        if p is not base:
            tc.remove(p)
    _definir_texto_celula(tc, linhas[0], rpr_modelo, unico=True)
    anterior = base
    for linha in linhas[1:]:
        novo = copy.deepcopy(modelo)
        tmp = etree.Element(w("tc"))
        tmp.append(novo)
        _definir_texto_celula(tmp, linha, rpr_modelo, unico=True)
        anterior.addnext(novo)
        anterior = novo


def _pedacos_andamento(data, texto):
    """[(texto, negrito)]: 'Em ' + data em negrito + ', ' + cláusula."""
    return [("Em ", False), (data, True), (", " + _ajustar_inicio(texto), False)]


def _juntar_pedacos(pedacos):
    saida = []
    for texto, neg in pedacos:
        if saida and saida[-1][1] == neg:
            saida[-1] = (saida[-1][0] + texto, neg)
        else:
            saida.append((texto, neg))
    return saida


# ------------------------------------------------------------------ andamentos: análise do texto

def _parse_andamentos(texto):
    """[{'data', 'texto', 'inicio', 'fecho'}]; o que vem antes da primeira data fica fora."""
    marcas = list(INICIO_ANDAMENTO.finditer(texto))
    saida = []
    for i, m in enumerate(marcas):
        fim = marcas[i + 1].start() if i + 1 < len(marcas) else len(texto)
        resto = texto[m.end():fim].strip()
        segmento = texto[m.start():fim].strip()
        saida.append({"data": m.group(2), "texto": resto, "inicio": m.start(),
                      "fecho": bool(FECHO.fullmatch(segmento))})
    return saida


_PALAVRAS_FRACAS = set("a o e de da do das dos em para que os as um uma foi no na ao".split())


def _tokens(texto):
    return {t for t in _chave(texto).split() if t not in _PALAVRAS_FRACAS}


def _similaridade(a, b):
    ta, tb = _tokens(a), _tokens(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    return max(inter / len(ta | tb), inter / min(len(ta), len(tb)) * 0.9)


# ------------------------------------------------------------------ o documento

class _Bloco:
    """Tabela de um processo: título + campos rotulados + andamentos."""

    def __init__(self, tbl):
        self.tbl = tbl
        self.linhas = _filhos(tbl, "tr")
        self.titulo = _texto_linha(self.linhas[0])
        self.numeros = list(dict.fromkeys(CNJ.findall(self.titulo)))
        self.campos, self.rotulos = {}, {}
        for ri, tr in enumerate(self.linhas[1:], start=1):
            cels = _filhos(tr, "tc")
            for ci, tc in enumerate(cels):
                campo = ROTULOS.get(_chave(_texto_celula(tc)).replace("  ", " ")) or ROTULOS.get(
                    re.sub(r"\s*:\s*$", "", _sem_acento(_texto_celula(tc)).lower().strip()))
                if campo is None or campo in self.campos:
                    continue
                if ci + 1 < len(cels):
                    valor = cels[ci + 1]
                elif campo == "andamentos" and ri + 1 < len(self.linhas):   # variante: texto na linha de baixo
                    abaixo = _filhos(self.linhas[ri + 1], "tc")
                    valor = abaixo[0] if abaixo else None
                else:
                    valor = None
                if valor is not None:
                    self.campos[campo], self.rotulos[campo] = valor, tc

    @property
    def momento(self):
        m = COLCHETE.search(self.titulo)
        return m.group(2).strip() if m else None

    def nao_mapeadas(self):
        """Células com texto que não são título, rótulo nem valor mapeado (ficariam com texto velho num clone)."""
        mapeadas = {id(c) for c in self.campos.values()} | {id(c) for c in self.rotulos.values()}
        return [tc for tr in self.linhas[1:] for tc in _filhos(tr, "tc")
                if id(tc) not in mapeadas and _texto_celula(tc).strip()]

    def tem_vmerge(self):
        return any(True for _ in self.tbl.iter(w("vMerge")))

    def tem_imagem(self):
        return any(True for tag in ("drawing", "pict", "object") for _ in self.tbl.iter(w(tag)))

    def andamentos_par(self):
        """Parágrafo que recebe o texto novo: o último com texto da célula de andamentos."""
        cel = self.campos.get("andamentos")
        if cel is None:
            return None
        pars = _filhos(cel, "p")
        return next((p for p in reversed(pars) if _texto_par(p).strip()), pars[0] if pars else None)

    def andamentos_texto(self):
        cel = self.campos.get("andamentos")
        return " ".join(_texto_par(p).strip() for p in _filhos(cel, "p") if _texto_par(p).strip()) if cel is not None else ""


class _Resumo:
    def __init__(self, tbl):
        self.tbl = tbl
        self.linhas = _filhos(tbl, "tr")
        self.cabecalho = next(i for i, tr in enumerate(self.linhas) if self._eh_cabecalho(tr))
        cab = [_chave(_texto_celula(tc)) for tc in _filhos(self.linhas[self.cabecalho], "tc")]
        achar = lambda *ts: next((i for i, c in enumerate(cab) if any(t in c for t in ts)), None)
        self.col = {"numero": achar("processo", "n do"), "assunto": achar("assunto"),
                    "momento": achar("momento"), "ultimo": achar("ultimo")}

    @staticmethod
    def _eh_cabecalho(tr):
        c = _chave(_texto_linha(tr))
        return "momento atual" in c and "ultimo andamento" in c

    def dados(self):
        """[(tr, numeros, {assunto, momento, ultimo})]"""
        saida = []
        for tr in self.linhas[self.cabecalho + 1:]:
            cels = _filhos(tr, "tc")
            numeros = list(dict.fromkeys(CNJ.findall(_texto_celula(cels[self.col["numero"] or 0]) if cels else "")))
            if numeros:
                get = lambda k: _texto_celula(cels[self.col[k]]).strip() if self.col[k] is not None and self.col[k] < len(cels) else ""
                saida.append((tr, numeros, {"assunto": get("assunto"), "momento": get("momento"), "ultimo": get("ultimo")}))
        return saida

    def celula(self, tr, chave):
        cels = _filhos(tr, "tc")
        i = self.col[chave]
        return cels[i] if i is not None and i < len(cels) else None


class _Documento:
    def __init__(self, xml_bytes):
        parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False)
        self.root = etree.fromstring(xml_bytes, parser)
        self.body = self.root.find(w("body"))
        self.mudou = False

    def serializar(self):
        return b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + etree.tostring(self.root, encoding="UTF-8")

    def tabelas(self):
        return _filhos(self.body, "tbl")

    def resumo(self):
        for tbl in self.tabelas():
            if any(_Resumo._eh_cabecalho(tr) for tr in _filhos(tbl, "tr")):
                return _Resumo(tbl)
        return None

    def blocos(self):
        saida = []
        for tbl in self.tabelas():
            linhas = _filhos(tbl, "tr")
            if not linhas or any(_Resumo._eh_cabecalho(tr) for tr in linhas[:2]):
                continue
            if CNJ.search(_texto_linha(linhas[0])) and re.search(r"PROCESSO|AGRAVO|APENSO|RECURSO", _sem_acento(_texto_linha(linhas[0])).upper()):
                saida.append(_Bloco(tbl))
        return saida

    def paragrafos_topo(self):
        return _filhos(self.body, "p")

    def par_data_base(self):
        for p in self.paragrafos_topo():
            m = DATA_BASE_RE.search(_texto_par(p))
            if m:
                return p, m
        return None, None

    def cliente(self):
        for p in self.paragrafos_topo():
            t = _texto_par(p).strip()
            if t and not DATA_BASE_RE.search(t):
                return t
        return None


# ------------------------------------------------------------------ avisos e relatório

def _novo_resultado(destino):
    return {"destino": Path(destino), "processos_atualizados": [], "processos_novos": [], "mudancas": [],
            "avisos": [], "ignorados": [], "nao_encontrados": [], "andamentos_texto_depois": {}}


def _aviso(res, nivel, onde, codigo, mensagem, candidatos=None):
    res["avisos"].append({"nivel": nivel, "onde": onde, "codigo": codigo, "mensagem": mensagem,
                          "candidatos": candidatos or []})


def _mudanca(res, numero, campo, antes, depois):
    res["mudancas"].append({"numero": numero, "campo": campo, "antes": antes, "depois": depois})
    if numero and numero not in res["processos_atualizados"] and numero not in res["processos_novos"] and campo != "data_base":
        res["processos_atualizados"].append(numero)


# ------------------------------------------------------------------ leitura

def _abrir(docx):
    with zipfile.ZipFile(docx) as z:
        return _Documento(z.read(PARTE_DOCUMENTO))


def ler_estrutura(docx):
    """{'cliente', 'data_base', 'resumo': [...], 'processos': [...], 'avisos': [...]} do .docx (nada é gravado)."""
    doc = _abrir(docx)
    _, m = doc.par_data_base()
    est = {"arquivo": Path(docx).name, "cliente": doc.cliente(), "data_base": m.group(2) if m else None,
           "resumo": [], "processos": [], "avisos": []}
    resumo = doc.resumo()
    if resumo is None:
        est["avisos"].append("quadro-resumo não encontrado")
    else:
        for _tr, numeros, d in resumo.dados():
            est["resumo"].append({"numeros": numeros, "assunto": d["assunto"],
                                  "momento_atual": d["momento"], "ultimo_andamento": d["ultimo"]})
    for b in doc.blocos():
        item = {"numeros": b.numeros, "titulo": b.titulo.strip(), "momento_atual": b.momento}
        for campo in CAMPOS_FICHA_DO_BLOCO[:-1]:
            item[campo] = _texto_celula(b.campos[campo]).strip() if campo in b.campos else None
        texto = b.andamentos_texto()
        item["andamentos_texto"] = texto
        andamentos, fecho = [], None
        pars = [p for p in _filhos(b.campos["andamentos"], "p") if _texto_par(p).strip()] if "andamentos" in b.campos else []
        for p in pars:
            tp = _texto_par(p)
            for a in _parse_andamentos(tp):
                ini = a["inicio"]
                m_data = INICIO_ANDAMENTO.match(tp, ini)
                negr = _formato_no_trecho(p, m_data.start(2), m_data.end(2))
                if a["fecho"]:
                    fecho = {"data": a["data"], "data_em_negrito": negr}
                else:
                    andamentos.append({"data": a["data"], "texto": a["texto"], "data_em_negrito": negr})
        item["andamentos"], item["fecho"] = andamentos, fecho
        if "andamentos" not in b.campos:
            est["avisos"].append(f"{b.numeros[0]}: linha 'Andamentos:' não encontrada")
        est["processos"].append(item)
    return est


# ------------------------------------------------------------------ andamentos: atualização

def _achar_fecho(texto):
    return FECHO.search(texto)


def _atualizar_andamentos(bloco, upd, data_base, opc, res):
    numero = bloco.numeros[0]
    par = bloco.andamentos_par()
    if par is None:
        _aviso(res, "atencao", numero, "sem_andamentos", "bloco sem a linha 'Andamentos:': nada acrescentado")
        return
    texto = _texto_par(par)
    revisao = _tem_revisao(par)
    fecho = _achar_fecho(texto)
    fecho_longe = None        # (parágrafo, casamento): fecho que ficou num parágrafo ANTERIOR (o advogado escreveu depois dele)
    if not fecho:
        pars = [p for p in _filhos(bloco.campos["andamentos"], "p") if _texto_par(p).strip()]
        for p in reversed(pars[:-1]):
            m = _achar_fecho(_texto_par(p))
            if m:
                fecho_longe = (p, m)
                break
    corpo_celula = bloco.andamentos_texto()
    if fecho:
        corpo_celula = _plano(corpo_celula)
        cf = _achar_fecho(corpo_celula)
        corpo_celula = corpo_celula[:cf.start()] if cf else corpo_celula
    existentes = [a for a in _parse_andamentos(corpo_celula) if not a["fecho"]]
    if not fecho and any(a["fecho"] for a in _parse_andamentos(texto)):
        _aviso(res, "atencao", numero, "fecho_no_meio",
               "há uma frase 'sem atualizações' que não é a última do texto (texto acrescentado depois dela): mantida")
    if fecho_longe:
        _aviso(res, "atencao", numero, "fecho_fora_do_fim",
               "a frase de fecho está num parágrafo anterior ao último (texto do advogado depois dela): "
               "nunca é apagada; sem novidade só a data é renovada ali; com novidade o texto novo vai no último parágrafo")

    # 1) o que de fato é novo (dedupe: mesma data + mesmo núcleo)
    aceitos, repetidos = [], 0
    conhecido = upd.get("texto_conhecido")
    for a in upd.get("andamentos") or []:
        data = _data_br(a.get("data"))
        clausula = _ajustar_inicio(a.get("texto", ""))
        if not data or not clausula:
            _aviso(res, "erro", numero, "andamento_invalido", f"andamento sem data válida ou sem texto: {a!r}")
            continue
        mesma_data = [e for e in existentes if e["data"] == data]
        sim = max([_similaridade(clausula, e["texto"]) for e in mesma_data] or [0.0])
        if sim >= 0.7 or any(_chave(clausula) == _chave(e["texto"]) for e in mesma_data):
            repetidos += 1
            res["ignorados"].append({"numero": numero, "data": data, "motivo": "andamento já presente"})
            continue
        if any(x["data"] == data and _similaridade(clausula, x["texto"]) >= 0.7 for x in aceitos):
            repetidos += 1
            res["ignorados"].append({"numero": numero, "data": data, "motivo": "repetido na própria atualização"})
            continue
        if mesma_data:
            if sim >= 0.4:
                _aviso(res, "atencao", numero, "possivel_duplicata_manual",
                       f"já há texto parecido em {data} (provável edição à mão): não acrescentado; conferir",
                       [e["texto"][:120] for e in mesma_data])
                res["ignorados"].append({"numero": numero, "data": data, "motivo": "parecido com texto existente"})
                repetidos += 1
                continue
            _aviso(res, "info", numero, "mesma_data", f"já existe outro andamento em {data}; o novo foi acrescentado")
        aceitos.append({"data": data, "texto": clausula})
    aceitos.sort(key=lambda a: _ordem_data(a["data"]))

    # 2) edição manual recente? (final do texto diverge do último estado conhecido)
    if conhecido is not None and aceitos and not repetidos:
        cf2 = _achar_fecho(_plano(conhecido))
        cauda = _chave(_plano(conhecido)[:cf2.start()] if cf2 else conhecido)[-120:]
        if cauda and not _chave(corpo_celula).endswith(cauda):
            _aviso(res, "atencao", numero, "edicao_manual",
                   "o final do texto de andamentos foi alterado à mão desde o último ciclo: só foi acrescentado, "
                   "nada reescrito; conferir o resultado")

    # 3) formatos: do próprio parágrafo, fora do fecho
    unidades = [t for t in _unidades(par)]
    limite = fecho.start() if fecho else len(texto)
    pos, normal, negrito = 0, None, None
    for t in unidades:
        n = len(t.text or "")
        if pos < limite and (t.text or "").strip():
            if _negrito(_rpr_de(t)):
                negrito = _rpr_de(t)
            else:
                normal = _rpr_de(t)
        pos += n
    ref = _rpr_no_offset(par, fecho.start()) if fecho else None
    rpr_fecho_data = _rpr_no_offset(par, fecho.start(1)) if fecho else None
    rpr_fecho_txt = _rpr_no_offset(par, fecho.end(1)) if fecho else None
    prefixo = texto[fecho.start():fecho.start(1)] if fecho else MOMENTO_PADRAO_FECHO[0]
    sufixo = texto[fecho.end(1):fecho.end()].rstrip() if fecho else MOMENTO_PADRAO_FECHO[1]
    if normal is None and negrito is None and ref is None:
        rotulo = bloco.rotulos.get("andamentos")
        normal = _rpr_de(_unidades(rotulo.find(w("p")))[0]) if rotulo is not None and _unidades(rotulo.find(w("p"))) else None
    modelo_normal = _rpr_modelo(normal if normal is not None else (ref if ref is not None else negrito), False)
    modelo_negrito = _rpr_modelo(negrito if negrito is not None else modelo_normal, True, herdar_destaques=negrito is not None)
    fecho_normal = _rpr_modelo(rpr_fecho_txt if rpr_fecho_txt is not None else modelo_normal, False, herdar_destaques=False)
    fecho_negrito = _rpr_modelo(rpr_fecho_data if rpr_fecho_data is not None else modelo_negrito, True)
    antes_fecho = fecho.group(0).strip() if fecho else None

    def anexar(pedacos):
        for t, neg in _juntar_pedacos(pedacos):
            par.append(_novo_run(t, modelo_negrito if neg else modelo_normal))

    def anexar_fecho():
        par.append(_novo_run(prefixo, fecho_normal))
        par.append(_novo_run(data_base, fecho_negrito))
        par.append(_novo_run(sufixo, fecho_normal))

    if not aceitos:
        if fecho_longe:
            p_longe, m_longe = fecho_longe
            if m_longe.group(1) != data_base and not _tem_revisao(p_longe):
                _substituir(p_longe, m_longe.start(1), m_longe.end(1), data_base)
                _mudanca(res, numero, "andamentos_fecho", m_longe.group(0).strip(),
                         m_longe.group(0).strip().replace(m_longe.group(1), data_base))
        elif fecho:
            if fecho.group(1) != data_base:
                if revisao:
                    _aviso(res, "atencao", numero, "revisao_no_trecho",
                           "controle de alterações/comentário no trecho final: fecho antigo mantido e novo acrescentado")
                    par.append(_novo_run(" ", modelo_normal))
                    anexar_fecho()
                else:
                    _substituir(par, fecho.start(1), fecho.end(1), data_base)
                _mudanca(res, numero, "andamentos_fecho", antes_fecho, f"{prefixo}{data_base}{sufixo}".strip())
        else:
            if texto.strip() and not texto.endswith((" ", "\n")):
                par.append(_novo_run(" ", modelo_normal))
            anexar_fecho()
            _mudanca(res, numero, "andamentos_fecho", None, f"{prefixo}{data_base}{sufixo}".strip())
            _aviso(res, "info", numero, "fecho_acrescentado", "o texto não tinha frase de fecho: acrescentada")
    else:
        if fecho and not revisao:
            _substituir(par, fecho.start(), fecho.end(), "")
            sobra = _texto_par(par)
            if sobra != sobra.rstrip():          # tira o espaço que separava o fecho
                _substituir(par, len(sobra.rstrip()), len(sobra), "")
        elif fecho and revisao:
            _aviso(res, "atencao", numero, "revisao_no_trecho",
                   "controle de alterações/comentário no trecho final: fecho antigo mantido; texto novo acrescentado depois")
        pedacos = []
        sobra = _texto_par(par)
        if sobra.strip() and not sobra.endswith((" ", "\n")):
            pedacos.append((" ", False))
        for i, a in enumerate(aceitos):
            if i:
                pedacos.append((" ", False))
            pedacos += _pedacos_andamento(a["data"], a["texto"])
        anexar(pedacos)
        if opc["fecho_apos_novidade"]:
            par.append(_novo_run(" ", modelo_normal))
            anexar_fecho()
        novo_txt = " ".join(f"Em {a['data']}, {a['texto']}" for a in aceitos)
        _mudanca(res, numero, "andamentos", None, novo_txt)
        if fecho and not revisao:
            _mudanca(res, numero, "andamentos_fecho", antes_fecho,
                     f"{prefixo}{data_base}{sufixo}".strip() if opc["fecho_apos_novidade"] else None)
    return aceitos


def _atualizar_resumo_e_titulo(doc, resumo, bloco, linha, upd, aceitos, data_base, res):
    numero = bloco.numeros[0]
    # momento atual: quadro-resumo e título do bloco andam juntos
    novo = (upd.get("momento_atual") or "").strip().upper()
    if novo:
        titulo = _filhos(_filhos(bloco.linhas[0], "tc")[0], "p")
        par_t = next((p for p in titulo if COLCHETE.search(_texto_par(p))), None)
        antes_t = bloco.momento
        celula = resumo.celula(linha, "momento") if linha is not None else None
        antes_r = _texto_celula(celula).strip() if celula is not None else None
        if antes_t is not None and antes_r is not None and _chave(antes_t) != _chave(antes_r):
            _aviso(res, "atencao", numero, "momento_divergente",
                   f"antes da atualização o momento era diferente no título ('{antes_t}') e no resumo ('{antes_r}')")
        if par_t is not None and (antes_t is None or _chave(antes_t) != _chave(novo)):
            m = COLCHETE.search(_texto_par(par_t))
            if m.group(2):
                _substituir(par_t, m.start(2), m.end(2), novo)
            else:                                   # '[ ]' vazio: insere dentro do colchete
                par_t.append(_novo_run(novo, _rpr_modelo(_rpr_no_offset(par_t, m.start()), True)))
            _mudanca(res, numero, "momento_atual", antes_t, novo)
        elif par_t is None:
            _aviso(res, "atencao", numero, "titulo_sem_momento", "título do bloco sem '[ MOMENTO ]': não alterado")
        if celula is not None and (antes_r is None or _chave(antes_r) != _chave(novo)):
            _definir_texto_celula(celula, novo)
            if par_t is None or _chave(antes_t or "") == _chave(novo):
                _mudanca(res, numero, "momento_atual", antes_r, novo)
    # último andamento
    celula = resumo.celula(linha, "ultimo") if linha is not None else None
    if celula is not None:
        atual = _texto_celula(celula).strip()
        explicito = _data_br(upd.get("ultimo_andamento"))
        candidatos = [_data_br(a.get("data")) for a in upd.get("andamentos") or []] + [atual if _data_br(atual) else None]
        candidatos = [c for c in candidatos if c]
        novo_u = explicito or (max(candidatos, key=_ordem_data) if candidatos else None)
        if novo_u and novo_u != atual:
            _definir_texto_celula(celula, novo_u)
            _mudanca(res, numero, "ultimo_andamento", atual, novo_u)


def _atualizar_data_base(doc, data_base, res):
    par, m = doc.par_data_base()
    if par is None:
        _aviso(res, "atencao", "documento", "sem_data_base", "parágrafo 'Data-Base: DD/MM/AAAA' não encontrado")
        return
    if m.group(2) != data_base:
        _substituir(par, m.start(2), m.end(2), data_base)
        _mudanca(res, None, "data_base", m.group(2), data_base)


# ------------------------------------------------------------------ processo novo (clona bloco-modelo e linha do resumo)

def _titulo_processo(proc):
    numeros = proc.get("numeros") or [proc.get("numero")]
    tipos = proc.get("tipos") or []
    rotulo = {"agravo": "AGRAVO Nº", "apenso": "APENSO Nº", "recurso": "RECURSO Nº",
              "reajuizamento": "REAJUIZAMENTO Nº", "mesma_acao": "PROCESSO VINCULADO Nº"}
    partes = [f"PROCESSO Nº {numeros[0]}"]
    for i, n in enumerate(numeros[1:]):
        partes.append(f"{rotulo.get(tipos[i] if i < len(tipos) else '', 'PROCESSO VINCULADO Nº')} {n}")
    momento = (proc.get("momento_atual") or "").strip().upper()
    return " / ".join(partes) + (f" [ {momento} ]" if momento else "")


def _linhas_numero_resumo(proc):
    numeros = proc.get("numeros") or [proc.get("numero")]
    tipos = proc.get("tipos") or []
    return [numeros[0]] + [f"{(tipos[i] if i < len(tipos) else 'vinculado').capitalize()}: {n}" for i, n in enumerate(numeros[1:])]


def _texto_campos(proc, data_base):
    return {"assunto": proc.get("assunto") or "-", "autores": proc.get("autores") or "-",
            "reus": proc.get("reus") or "-", "ajuizamento": _data_br(proc.get("ajuizamento")) or proc.get("ajuizamento") or "-",
            "valor_causa": _dinheiro_br(proc.get("valor_causa")) or "-",
            "data_citacao": _data_br(proc.get("data_citacao")) or proc.get("data_citacao") or "-",
            "juizo": proc.get("juizo") or "-", "area": proc.get("area") or "-", "materia": proc.get("materia") or "-"}


def _preencher_andamentos_novo(bloco, proc, data_base, opc):
    """Andamentos de um processo novo: frases com data em negrito + fecho, com os formatos do modelo clonado."""
    cel = bloco.campos["andamentos"]
    par = bloco.andamentos_par()
    texto = _texto_par(par)
    fecho = _achar_fecho(texto)
    normal = negrito = None
    for t in _unidades(par):
        if (t.text or "").strip():
            if _negrito(_rpr_de(t)):
                negrito = negrito if negrito is not None else _rpr_de(t)
            elif normal is None:
                normal = _rpr_de(t)
    normal = _rpr_modelo(normal, False)
    negrito = _rpr_modelo(negrito if negrito is not None else normal, True)
    prefixo = texto[fecho.start():fecho.start(1)] if fecho else MOMENTO_PADRAO_FECHO[0]
    sufixo = texto[fecho.end(1):fecho.end()].rstrip() if fecho else MOMENTO_PADRAO_FECHO[1]
    for p in _filhos(cel, "p"):
        if p is not par:
            cel.remove(p)
    for filho in list(par):
        if filho.tag != w("pPr"):
            par.remove(filho)
    andamentos = sorted([{"data": _data_br(a["data"]), "texto": a["texto"]} for a in proc.get("andamentos") or []],
                        key=lambda a: _ordem_data(a["data"]))
    pedacos = []
    for i, a in enumerate(andamentos):
        if i:
            pedacos.append((" ", False))
        pedacos += _pedacos_andamento(a["data"], a["texto"])
    if not andamentos or opc["fecho_apos_novidade"]:
        if pedacos:
            pedacos.append((" ", False))
        pedacos += [(prefixo, False), (data_base, True), (sufixo, False)]
    for t, neg in _juntar_pedacos(pedacos):
        par.append(_novo_run(t, negrito if neg else normal))
    return " ".join(f"Em {a['data']}, {_ajustar_inicio(a['texto'])}" for a in andamentos)


def _escolher_modelo(blocos):
    """Último bloco 'limpo': todos os campos mapeados, sem mesclagem vertical, imagem, revisão ou texto solto."""
    def limpo(b):
        return (all(c in b.campos for c in CAMPOS_FICHA_DO_BLOCO) and not b.tem_vmerge() and not b.tem_imagem()
                and not _tem_revisao(b.tbl) and not b.nao_mapeadas())
    bons = [b for b in blocos if limpo(b)]
    return (bons[-1], True) if bons else ((blocos[-1], False) if blocos else (None, False))


def _clonar_bloco(modelo, proc, data_base, opc, res):
    tbl = copy.deepcopy(modelo.tbl)
    for tag in ("bookmarkStart", "bookmarkEnd", "commentRangeStart", "commentRangeEnd", "commentReference"):
        for el in list(tbl.iter(w(tag))):
            el.getparent().remove(el)
    b = _Bloco(tbl)
    titulo_cel = _filhos(b.linhas[0], "tc")[0]
    _definir_texto_celula(titulo_cel, _titulo_processo(proc), unico=True)
    textos = _texto_campos(proc, data_base)
    for campo, texto in textos.items():
        if campo in b.campos:
            rpr = None
            rot = b.rotulos[campo]
            if rot is not None and _unidades(_filhos(rot, "p")[0]):
                rpr = _rpr_modelo(_rpr_de(_unidades(_filhos(rot, "p")[0])[0]), False)
            _definir_texto_celula(b.campos[campo], texto, rpr, unico=True)
        else:
            _aviso(res, "atencao", proc["numeros"][0], "campo_sem_celula", f"o bloco-modelo não tem a linha '{campo}'")
    for tc in b.nao_mapeadas():                   # texto solto do modelo não pode virar dado do processo novo
        _definir_texto_celula(tc, "", unico=False)
        _aviso(res, "atencao", proc["numeros"][0], "celula_limpa", "célula do modelo fora do padrão foi esvaziada no clone")
    if "andamentos" in b.campos:
        _preencher_andamentos_novo(b, proc, data_base, opc)
    return tbl


def _inserir_processo_novo(doc, proc, data_base, opc, res):
    numeros = proc.get("numeros") or [proc.get("numero")]
    proc = dict(proc, numeros=numeros)
    blocos, resumo = doc.blocos(), doc.resumo()
    existentes = {n for b in blocos for n in b.numeros}
    repetidos = [n for n in numeros if n in existentes]
    if repetidos:
        _aviso(res, "info", numeros[0], "ja_existe", "processo já está no documento: não duplicado", repetidos)
        res["ignorados"].append({"numero": numeros[0], "data": None, "motivo": "processo já existe"})
        return
    modelo, limpo = _escolher_modelo(blocos)
    if modelo is None:
        tbl = _el(_bloco_xml(proc, data_base, opc))
        if _filhos(tbl, "tr"):
            _aviso(res, "info", numeros[0], "sem_modelo", "documento sem bloco de processo: bloco construído do zero")
    else:
        if not limpo:
            _aviso(res, "atencao", numeros[0], "modelo_imperfeito",
                   "nenhum bloco 'limpo' para clonar (mesclagem vertical, imagem ou revisão): usado o último; conferir")
        tbl = _clonar_bloco(modelo, proc, data_base, opc, res)
    ultimo = blocos[-1].tbl if blocos else None
    if ultimo is None:
        ancora = resumo.tbl if resumo is not None else (doc.body[-2] if len(doc.body) > 1 else None)
        pos = list(doc.body).index(ancora) + 1 if ancora is not None else max(len(doc.body) - 1, 0)
        doc.body.insert(pos, _el(_par_vazio_xml()))
        doc.body.insert(pos + 1, tbl)
        doc.body.insert(pos + 2, _el(_par_vazio_xml()))
    else:
        seguinte = ultimo.getnext()
        if seguinte is not None and seguinte.tag == w("p") and not _texto_par(seguinte).strip():
            seguinte.addnext(tbl)
            tbl.addnext(copy.deepcopy(seguinte))
        else:
            ultimo.addnext(tbl)
            ultimo.addnext(_el(_par_vazio_xml()))
    # linha do quadro-resumo
    if resumo is not None:
        dados = resumo.dados()
        if dados:
            nova = copy.deepcopy(dados[-1][0])
            ref = dados[-1][0]
        else:
            nova = copy.deepcopy(resumo.linhas[resumo.cabecalho])
            ref = resumo.linhas[resumo.cabecalho]
            for el in nova.iter(w("tblHeader")):
                el.getparent().remove(el)
            _aviso(res, "atencao", numeros[0], "resumo_sem_modelo", "quadro-resumo sem linha de dados: linha criada a partir do cabeçalho")
        for tag in ("bookmarkStart", "bookmarkEnd", "commentRangeStart", "commentRangeEnd", "commentReference"):
            for el in list(nova.iter(w(tag))):
                el.getparent().remove(el)
        cels = _filhos(nova, "tc")
        datas_novo = [_data_br(a["data"]) for a in proc.get("andamentos") or []] or [_data_br(proc.get("ultimo_andamento"))]
        ultimo_dt = max([d for d in datas_novo if d], key=_ordem_data, default=None)
        valores = {"assunto": proc.get("assunto") or "-", "momento": (proc.get("momento_atual") or "").upper(),
                   "ultimo": ultimo_dt or "-"}
        if resumo.col["numero"] is not None:
            _definir_paragrafos_celula(cels[resumo.col["numero"]], _linhas_numero_resumo(proc))
        for chave, texto in valores.items():
            i = resumo.col[chave]
            if i is not None and i < len(cels):
                _definir_texto_celula(cels[i], texto, unico=True)
        ref.addnext(nova)
    res["processos_novos"].append(numeros[0])
    _mudanca(res, numeros[0], "processo", None, "novo")


# ------------------------------------------------------------------ construção do zero (gerar) e blocos de reserva

LARG_PROC = [1900, 2600, 1900, 2626]
LARG_RESUMO = [2300, 2400, 2600, 1726]
BORDA = ''.join(f'<w:{l} w:val="single" w:sz="4" w:space="0" w:color="000000"/>' for l in ("top", "left", "bottom", "right"))


def _el(xml):
    raiz = etree.fromstring(f'<w:raiz xmlns:w="{W_NS}">{xml}</w:raiz>')
    filho = raiz[0]
    raiz.remove(filho)
    return filho


def _rpr_xml(negrito=False, tam=22):
    b = '<w:b w:val="1"/>' if negrito else ""
    return (f'<w:rPr><w:rFonts w:ascii="Arial" w:cs="Arial" w:eastAsia="Arial" w:hAnsi="Arial"/>{b}'
            f'<w:sz w:val="{tam}"/><w:szCs w:val="{tam}"/></w:rPr>')


def _run_xml(texto, negrito=False, tam=22):
    return f'<w:r>{_rpr_xml(negrito, tam)}<w:t xml:space="preserve">{escape(texto)}</w:t></w:r>'


def _par_xml(runs="", jc="left"):
    return (f'<w:p><w:pPr><w:spacing w:after="0" w:before="0" w:line="240" w:lineRule="auto"/><w:jc w:val="{jc}"/></w:pPr>{runs}</w:p>')


def _par_vazio_xml():
    return f'<w:p><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr><w:r>{_rpr_xml()}</w:r></w:p>'


def _tc_xml(larg, pars, span=1, fill=None):
    return (f'<w:tc><w:tcPr><w:tcW w:w="{larg}" w:type="dxa"/>' + (f'<w:gridSpan w:val="{span}"/>' if span > 1 else "")
            + f'<w:tcBorders>{BORDA}</w:tcBorders>' + (f'<w:shd w:fill="{fill}" w:val="clear"/>' if fill else "")
            + '<w:tcMar><w:top w:w="60" w:type="dxa"/><w:left w:w="100" w:type="dxa"/><w:bottom w:w="60" w:type="dxa"/>'
              '<w:right w:w="100" w:type="dxa"/></w:tcMar><w:vAlign w:val="top"/></w:tcPr>' + pars + '</w:tc>')


def _tbl_xml(grade, linhas):
    return (f'<w:tbl><w:tblPr><w:tblW w:w="{sum(grade)}" w:type="dxa"/><w:jc w:val="left"/><w:tblInd w:w="0" w:type="dxa"/>'
            f'<w:tblBorders>{BORDA}<w:insideH w:val="single" w:sz="4" w:space="0" w:color="000000"/>'
            f'<w:insideV w:val="single" w:sz="4" w:space="0" w:color="000000"/></w:tblBorders><w:tblLayout w:type="fixed"/></w:tblPr>'
            f'<w:tblGrid>{"".join(f"<w:gridCol w:w=\"{g}\"/>" for g in grade)}</w:tblGrid>{"".join(linhas)}</w:tbl>')


def _tr_xml(tcs, cabecalho=False):
    pr = '<w:trPr><w:cantSplit w:val="0"/>' + ('<w:tblHeader w:val="1"/>' if cabecalho else '') + '</w:trPr>'
    return f'<w:tr>{pr}{"".join(tcs)}</w:tr>'


def _runs_andamentos(andamentos, data_base, fecho):
    pedacos = []
    for i, a in enumerate(sorted(andamentos, key=lambda a: _ordem_data(_data_br(a["data"])))):
        if i:
            pedacos.append((" ", False))
        pedacos += _pedacos_andamento(_data_br(a["data"]), a["texto"])
    if fecho:
        if pedacos:
            pedacos.append((" ", False))
        pedacos += [("Em ", False), (data_base, True), (", sem atualizações.", False)]
    return "".join(_run_xml(t, n) for t, n in _juntar_pedacos(pedacos))


def _bloco_xml(proc, data_base, opc):
    L, g = LARG_PROC, LARG_PROC
    t = _texto_campos(proc, data_base)
    rot = lambda s: _tc_xml(L[0], _par_xml(_run_xml(s, True)), fill="F3F3F3")
    val = lambda i, s, span=1: _tc_xml(sum(L[i:i + span]), _par_xml(_run_xml(s) if s else ""), span)
    fecho = (not proc.get("andamentos")) or opc["fecho_apos_novidade"]
    linhas = [
        _tr_xml([_tc_xml(sum(L), _par_xml(_run_xml(_titulo_processo(proc), True)), 4, fill="D9D9D9")]),
        _tr_xml([rot("Assunto"), val(1, t["assunto"], 3)]),
        _tr_xml([rot("Autor(es)"), val(1, t["autores"], 3)]),
        _tr_xml([rot("Réu(s)"), val(1, t["reus"], 3)]),
        _tr_xml([rot("Ajuizamento"), val(1, t["ajuizamento"]), _tc_xml(L[2], _par_xml(_run_xml("Valor da Causa", True)), fill="F3F3F3"), val(3, t["valor_causa"])]),
        _tr_xml([rot("Data de citação"), val(1, t["data_citacao"]), _tc_xml(L[2], _par_xml(_run_xml("Juízo", True)), fill="F3F3F3"), val(3, t["juizo"])]),
        _tr_xml([rot("Área do Direito"), val(1, t["area"]), _tc_xml(L[2], _par_xml(_run_xml("Matéria Principal", True)), fill="F3F3F3"), val(3, t["materia"])]),
        _tr_xml([rot("Andamentos:"), _tc_xml(sum(L[1:]), _par_xml(_runs_andamentos(proc.get("andamentos") or [], data_base, fecho), "both"), 3)]),
    ]
    return _tbl_xml(g, linhas)


def _resumo_xml(processos):
    L = LARG_RESUMO
    cab = _tr_xml([_tc_xml(L[i], _par_xml(_run_xml(s, True, 18)), fill="D9D9D9") for i, s in
                   enumerate(["Nº DO PROCESSO", "ASSUNTO", "MOMENTO ATUAL DO PROCESSO", "ÚLTIMO ANDAMENTO"])], cabecalho=True)
    linhas = [cab]
    for p in processos:
        datas = [_data_br(a["data"]) for a in p.get("andamentos") or []] or [_data_br(p.get("ultimo_andamento"))]
        ultimo = max([d for d in datas if d], key=_ordem_data, default="-")
        numeros = "".join(_par_xml(_run_xml(n, False, 18)) for n in _linhas_numero_resumo(p))
        linhas.append(_tr_xml([_tc_xml(L[0], numeros), _tc_xml(L[1], _par_xml(_run_xml(p.get("assunto") or "-", False, 18))),
                               _tc_xml(L[2], _par_xml(_run_xml((p.get("momento_atual") or "").upper(), True, 18))),
                               _tc_xml(L[3], _par_xml(_run_xml(ultimo, False, 18)))]))
    return _tbl_xml(L, linhas)


def gerar(destino, relatorio, fecho_apos_novidade=True, sobrescrever_destino=False):
    """Cria o .docx do zero. relatorio = {'cliente', 'data_base', 'processos': [proc, ...]}, com
    proc = {'numeros': [principal, vinculados...], 'tipos': [tipo de cada vinculado], 'assunto', 'autores',
            'reus', 'ajuizamento', 'valor_causa', 'data_citacao', 'juizo', 'area', 'materia',
            'momento_atual', 'ultimo_andamento', 'andamentos': [{'data', 'texto'}]}."""
    import docx   # python-docx só entra para o esqueleto do pacote (estilos, tema, rels); não é usado na atualização
    destino = Path(destino)
    if destino.exists() and not sobrescrever_destino:
        raise FileExistsError(f"{destino} já existe")
    opc = {"fecho_apos_novidade": fecho_apos_novidade}
    data_base = _data_br(relatorio["data_base"])
    res = _novo_resultado(destino)
    d = docx.Document()
    corpo = d.element.body
    sect = corpo.find(w("sectPr"))
    for filho in list(corpo):
        if filho is not sect:
            corpo.remove(filho)
    pg = sect.find(w("pgSz"))
    pg.set(w("w"), "11906"), pg.set(w("h"), "16838")
    mar = sect.find(w("pgMar"))
    mar.set(w("left"), "1440"), mar.set(w("right"), "1440")
    elementos = [_el(_par_xml(_run_xml(relatorio["cliente"], True, 28))),
                 _el(_par_xml(_run_xml("Data-Base: ", True) + _run_xml(data_base))),
                 _el(_par_vazio_xml()), _el(_resumo_xml(relatorio["processos"])), _el(_par_vazio_xml())]
    for p in relatorio["processos"]:
        p = dict(p, numeros=p.get("numeros") or [p.get("numero")])
        elementos += [_el(_bloco_xml(p, data_base, opc)), _el(_par_vazio_xml())]
        res["processos_novos"].append(p["numeros"][0])
        res["andamentos_texto_depois"][p["numeros"][0]] = " ".join(
            f"Em {_data_br(a['data'])}, {_ajustar_inicio(a['texto'])}" for a in p.get("andamentos") or [])
    for el in elementos:
        sect.addprevious(el)
    destino.parent.mkdir(parents=True, exist_ok=True)
    d.save(str(destino))
    res["mudancas"].append({"numero": None, "campo": "documento", "antes": None, "depois": "gerado do zero"})
    return res


# ------------------------------------------------------------------ atualização do arquivo existente

def atualizar(origem, destino, atualizacoes, data_base, *, fecho_apos_novidade=True,
              renovar_fecho_dos_demais=False, sobrescrever_destino=False):
    """Copia `origem` para `destino` aplicando as atualizações. Devolve o Resultado (CONTRATOS.md 5) com extras:
    'ignorados', 'nao_encontrados' e 'andamentos_texto_depois' ({numero principal: texto de andamentos}).

    atualizacoes: lista de dicts
      {'numero' | 'numeros': ..., 'momento_atual': 'AGUARDANDO SENTENÇA'|None, 'ultimo_andamento': data|None,
       'andamentos': [{'data': 'DD/MM/AAAA', 'texto': 'o juiz proferiu ...'}],
       'texto_conhecido': texto de andamentos como o sistema o deixou no último ciclo (opcional)}
      {'novo': proc}  -> processo novo (mesmo formato de gerar)
    Processos do arquivo que não aparecem na lista ficam INTACTOS (salvo renovar_fecho_dos_demais=True)."""
    origem, destino = Path(origem), Path(destino)
    if destino.resolve() == origem.resolve() or (destino.exists() and origem.exists() and os.path.samefile(destino, origem)):
        raise ValueError("o arquivo original nunca é sobrescrito: informe outro destino")
    if destino.exists() and not sobrescrever_destino:
        raise FileExistsError(f"{destino} já existe")
    data_base = _data_br(data_base)
    if not data_base:
        raise ValueError("data_base inválida")
    opc = {"fecho_apos_novidade": fecho_apos_novidade}
    res = _novo_resultado(destino)
    with zipfile.ZipFile(origem) as z:
        original = z.read(PARTE_DOCUMENTO)
        extras = {n: z.read(n) for n in z.namelist() if n in ("word/settings.xml", "word/comments.xml")}
    doc = _Documento(original)
    if b"<w:trackRevisions" in extras.get("word/settings.xml", b""):
        _aviso(res, "atencao", "documento", "controle_alteracoes_ligado",
               "o documento está com controle de alterações ligado: as edições do sistema NÃO ficam marcadas como revisão")
    if "word/comments.xml" in extras:
        _aviso(res, "info", "documento", "tem_comentarios", "o documento tem comentários: partes de comentários preservadas")

    _atualizar_data_base(doc, data_base, res)
    resumo = doc.resumo()
    if resumo is None:
        _aviso(res, "atencao", "documento", "sem_resumo", "quadro-resumo não encontrado: só os blocos serão atualizados")
    tocados = []          # tabelas (elementos) atualizadas; comparar por identidade, nunca por id()
    novos = []
    todos_blocos = doc.blocos()                                   # índices feitos UMA vez (200 processos: O(n), não O(n²))
    linhas_resumo = resumo.dados() if resumo is not None else []
    for upd in atualizacoes:
        if upd.get("novo"):
            novos.append(upd["novo"])
            continue
        numeros = list(upd.get("numeros") or ([upd["numero"]] if upd.get("numero") else []))
        blocos = [b for b in todos_blocos if set(b.numeros) & set(numeros)]
        if not blocos:
            res["nao_encontrados"].append(numeros[0] if numeros else None)
            _aviso(res, "atencao", numeros[0] if numeros else "documento", "processo_nao_encontrado",
                   "número não encontrado em nenhum título de bloco", numeros)
            continue
        if len(blocos) > 1:
            _aviso(res, "atencao", numeros[0], "numero_em_varios_blocos",
                   "número aparece em mais de um bloco: atualizado só o primeiro", [b.numeros[0] for b in blocos])
        bloco = blocos[0]
        tocados.append(bloco.tbl)
        if set(numeros) - set(bloco.numeros):
            _aviso(res, "info", bloco.numeros[0], "numero_vinculado_novo",
                   "a atualização traz número que não está no título do bloco (não acrescentado ao título)",
                   sorted(set(numeros) - set(bloco.numeros)))
        linha = None
        if resumo is not None:
            linha = next((tr for tr, ns, _ in linhas_resumo if set(ns) & set(bloco.numeros)), None)
            if linha is None:
                _aviso(res, "atencao", bloco.numeros[0], "sem_linha_no_resumo", "bloco sem linha correspondente no quadro-resumo")
        aceitos = _atualizar_andamentos(bloco, upd, data_base, opc, res) or []
        if resumo is not None:
            _atualizar_resumo_e_titulo(doc, resumo, bloco, linha, upd, aceitos, data_base, res)
    for proc in novos:
        _inserir_processo_novo(doc, proc, data_base, opc, res)
    if renovar_fecho_dos_demais:
        for bloco in doc.blocos():
            if not any(t is bloco.tbl for t in tocados) and bloco.numeros[0] not in res["processos_novos"]:
                _atualizar_andamentos(bloco, {"andamentos": []}, data_base, opc, res)
    else:
        sem = [b.numeros[0] for b in doc.blocos()
               if not any(t is b.tbl for t in tocados) and b.numeros[0] not in res["processos_novos"]]
        if sem:
            _aviso(res, "info", "documento", "processos_sem_atualizacao",
                   f"{len(sem)} processo(s) do arquivo ficaram intactos (sem atualização informada)", sem)

    # texto de andamentos de cada processo depois da atualização (a ficha guarda como 'último estado conhecido')
    for b in doc.blocos():
        res["andamentos_texto_depois"][b.numeros[0]] = b.andamentos_texto()
    destino.parent.mkdir(parents=True, exist_ok=True)
    mudou = bool(res["mudancas"])
    novo_xml = doc.serializar() if mudou else original
    fd, tmp = tempfile.mkstemp(dir=destino.parent, suffix=".tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(origem) as zin, zipfile.ZipFile(tmp, "w") as zout:
            for info in zin.infolist():
                dados = novo_xml if info.filename == PARTE_DOCUMENTO else zin.read(info.filename)
                zout.writestr(info, dados)        # mesmo ZipInfo: nome, data e compressão originais
        os.replace(tmp, destino)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return res


# ------------------------------------------------------------------ conferência de coerência

def verificar_coerencia(docx, fechos=True):
    """Lista de problemas entre quadro-resumo, blocos, fecho e data-base (lista vazia = coerente).
    fechos=False ignora fecho com data diferente da data-base (esperado quando só parte dos processos foi atualizada)."""
    doc = _abrir(docx)
    problemas = []
    _, m = doc.par_data_base()
    data_base = m.group(2) if m else None
    if not data_base:
        problemas.append("sem 'Data-Base'")
    resumo = doc.resumo()
    blocos = doc.blocos()
    linhas = resumo.dados() if resumo is not None else []
    vistos = {}
    for b in blocos:
        for n in b.numeros:
            if n in vistos:
                problemas.append(f"{n}: número em dois blocos")
            vistos[n] = b
    for b in blocos:
        par = next(((ns, d) for _tr, ns, d in linhas if set(ns) & set(b.numeros)), None)
        rotulo = b.numeros[0]
        if par is None:
            problemas.append(f"{rotulo}: bloco sem linha no resumo")
            continue
        ns, d = par
        if set(ns) != set(b.numeros):
            problemas.append(f"{rotulo}: números do resumo {ns} diferem dos do título {b.numeros}")
        if b.momento is not None and _chave(b.momento) != _chave(d["momento"]):
            problemas.append(f"{rotulo}: momento atual difere (título '{b.momento}' x resumo '{d['momento']}')")
        texto = b.andamentos_texto()
        itens = [a for a in _parse_andamentos(_plano(texto)) if not a["fecho"]]
        if itens:
            ult = max((a["data"] for a in itens), key=_ordem_data)
            if d["ultimo"] != ult:
                problemas.append(f"{rotulo}: último andamento do resumo ({d['ultimo']}) difere do último do texto ({ult})")
        fe = _achar_fecho(_plano(texto))
        if fechos and fe and data_base and fe.group(1) != data_base:
            problemas.append(f"{rotulo}: fecho com {fe.group(1)} difere da data-base {data_base}")
    for _tr, ns, _d in linhas:
        if not any(set(ns) & set(b.numeros) for b in blocos):
            problemas.append(f"{ns[0]}: linha do resumo sem bloco")
    return problemas


# ------------------------------------------------------------------ contrato CONTRATOS.md 5: gravar(molde, estado, destino)

def _valor(ficha, nome, padrao=None):
    campo = (ficha.get("campos") or {}).get(nome)
    if isinstance(campo, dict):
        return campo.get("valor", padrao)
    return ficha.get(nome, padrao)


def texto_do_evento(ev):
    """Cláusula do andamento a partir de um evento aprovado (mesmas regras de relatorio.linha/planilha.frase_planilha).
    Em produção: importar relatorio.linha em vez de repetir aqui."""
    frase = (ev.get("frase") or "").strip()
    conteudo = (ev.get("conteudo") or "").strip()
    if conteudo:
        conteudo = conteudo[0].lower() + conteudo[1:]
        juncao = " " if conteudo.split()[0].endswith("ndo") else ", "
        frase = f"{frase.rstrip('.')}{juncao}{conteudo.rstrip('.')}."
    if ev.get("grau") and ev["grau"] != "1º grau":
        frase = f"no {ev['grau']}, {frase[:1].lower() + frase[1:]}"
    for chave, rotulo in (("audiencia", "Audiência"), ("prazo", "Prazo")):
        if ev.get(chave):
            frase += f" {rotulo}: {ev[chave].rstrip('.')}."
    return frase


def _proc_da_ficha(ficha, eventos):
    numeros = [ficha["numero"]] + [v["numero"] for v in ficha.get("vinculados") or []]
    tipos = [v.get("tipo", "") for v in ficha.get("vinculados") or []]
    andamentos = []
    for ev in eventos:
        if ev.get("numero") in numeros and ev.get("status", "aprovado") in ("aprovado", "relatado"):
            data = _data_br(ev.get("data")) or _data_br(str(ev.get("detectado_em", ""))[:10])
            if data:
                andamentos.append({"data": data, "texto": texto_do_evento(ev)})
    return {"numeros": numeros, "tipos": tipos, "assunto": _valor(ficha, "assunto"), "autores": _valor(ficha, "autores"),
            "reus": _valor(ficha, "reus"), "ajuizamento": _data_br(_valor(ficha, "data_ajuizamento")),
            "valor_causa": _valor(ficha, "valor_causa"), "data_citacao": _data_br(_valor(ficha, "data_citacao")),
            "juizo": _valor(ficha, "vara"), "area": _valor(ficha, "area"), "materia": _valor(ficha, "materia_principal"),
            "momento_atual": _valor(ficha, "momento_atual"), "ultimo_andamento": _data_br(_valor(ficha, "ultimo_andamento")),
            "andamentos": andamentos}


def gravar(molde, estado, destino, **opcoes):
    """Contrato docx_a.gravar(molde, estado, destino) -> Resultado.
    molde=None cria do zero; senão atualiza uma cópia do molde. Opções: fecho_apos_novidade, renovar_fecho_dos_demais,
    textos_conhecidos={numero: texto de andamentos do último ciclo}, sobrescrever_destino."""
    data_base = _data_br(estado["data_base"])
    eventos = estado.get("eventos") or []
    procs = [_proc_da_ficha(f, eventos) for f in estado.get("fichas") or []]
    if molde is None:
        return gerar(destino, {"cliente": estado["cliente"], "data_base": data_base, "processos": procs},
                     fecho_apos_novidade=opcoes.get("fecho_apos_novidade", True),
                     sobrescrever_destino=opcoes.get("sobrescrever_destino", False))
    existentes = {n for b in _abrir(molde).blocos() for n in b.numeros}
    conhecidos = opcoes.get("textos_conhecidos") or {}
    atualizacoes = []
    for p in procs:
        if set(p["numeros"]) & existentes:
            atualizacoes.append({"numeros": p["numeros"], "momento_atual": p["momento_atual"],
                                 "ultimo_andamento": p["ultimo_andamento"], "andamentos": p["andamentos"],
                                 "texto_conhecido": next((conhecidos[n] for n in p["numeros"] if n in conhecidos), None)})
        else:
            atualizacoes.append({"novo": p})
    return atualizar(molde, destino, atualizacoes, data_base,
                     fecho_apos_novidade=opcoes.get("fecho_apos_novidade", True),
                     renovar_fecho_dos_demais=opcoes.get("renovar_fecho_dos_demais", False),
                     sobrescrever_destino=opcoes.get("sobrescrever_destino", False))


def _cli(argv):
    if len(argv) >= 3 and argv[1] == "ler":
        print(json.dumps(ler_estrutura(argv[2]), ensure_ascii=False, indent=2))
    elif len(argv) >= 6 and argv[1] == "atualizar":
        r = atualizar(argv[2], argv[3], json.loads(Path(argv[4]).read_text(encoding="utf-8")), argv[5])
        r["destino"] = str(r["destino"])
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print("uso: docx_atualizador.py ler ARQ.docx | atualizar ORIGEM.docx DESTINO.docx ATUALIZACOES.json DD/MM/AAAA")


if __name__ == "__main__":
    _cli(sys.argv)
