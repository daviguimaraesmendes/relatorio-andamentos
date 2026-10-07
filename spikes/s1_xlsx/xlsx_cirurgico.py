"""SPIKE S1: gravação cirúrgica em .xlsx que tem Tabela do Excel (ListObject), formatação
condicional, validação de dados, intervalos nomeados, fórmulas, gráficos e tabela dinâmica.

Protótipo da API do futuro `src/escritores/xlsx_b.py` (WS-7). Só biblioteca padrão: o pacote
.xlsx (zip) é lido inteiro, só as partes que precisam mudar são reescritas (por edição de
TEXTO do XML, sem reserializar) e todas as outras são copiadas com o mesmo conteúdo, byte a
byte. Nada de openpyxl na gravação (ele apaga gráficos e tabelas dinâmicas ao salvar).

API (cada função lê `origem`, grava `destino`, nunca altera a origem, e devolve `Resultado`):

    inserir_linhas(origem, destino, aba, linhas, colunas=None, ...)
    escrever_celulas(origem, destino, aba, {(linha, coluna): valor}, humanos=..., preservar_humanos=True)
    acrescentar_coluna(origem, destino, aba, cabecalho, valores=None, formula=None, ...)
    Edicao(...)   várias operações num só arquivo, com um único salvar()
    validar(caminho) -> [problemas]    verificador de coerência do pacote (use antes de entregar)
    gravar(molde, estado, destino)     adaptador ao contrato (CONTRATOS.md, seção 5)

O que cada edição mantém coerente (ver docs/fase2/spikes/S1-xlsx.md):
  - linhas novas entram ao FIM da tabela, com o estilo (s=) da última linha de dados;
  - colunas calculadas (calculatedColumnFormula ou fórmula na última linha) propagam;
  - `ref` da tabela, autoFilter, <dimension>, formatação condicional e validação de dados que
    terminam na última linha, intervalos nomeados, séries de gráfico, fórmulas A1 em outras
    abas que cobrem a coluna inteira da tabela e a origem (por intervalo) de tabelas dinâmicas;
  - calcChain.xml é removido e `fullCalcOnLoad` é ligado (o cache de fórmulas fica velho);
  - textos entram como strings inline (não mexe em sharedStrings: parte idêntica byte a byte);
  - células "humanas" com valor nunca são sobrescritas.

Limites conhecidos (viram erro explícito, nunca dado silencioso): tabela com linha de totais,
conteúdo logo abaixo da tabela, célula mesclada na faixa nova, célula com mais de 32.767
caracteres, tabela dinâmica com cache salvo ao acrescentar coluna.
"""
import datetime
import html
import os
import posixpath
import re
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
      "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
      "rel": "http://schemas.openxmlformats.org/package/2006/relationships"}
LIMITE_CELULA = 32767
LIMPAR = object()   # valor especial de escrever_celulas: esvazia a célula


# ------------------------------------------------------------------ erros e tipos

class ErroXlsx(Exception):
    """Erro esperado de gravação (arquivo fora do que o protótipo sabe editar com segurança)."""


class NaoSuportado(ErroXlsx):
    pass


class ColunaDesconhecida(ErroXlsx):
    pass


class ConflitoDeConteudo(ErroXlsx):
    pass


class Formula(str):
    """Marca um texto como fórmula (sem o '='): Formula('SUM(A1:A3)')."""


@dataclass
class Resultado:
    destino: Path | None = None
    linhas_inseridas: int = 0
    primeira_linha: int | None = None
    ultima_linha: int | None = None
    celulas_escritas: int = 0
    ignoradas: list = field(default_factory=list)       # [(ref, motivo)]
    avisos: list = field(default_factory=list)
    partes_alteradas: list = field(default_factory=list)
    partes_removidas: list = field(default_factory=list)


# ------------------------------------------------------------------ referências A1

_RE_CEL = re.compile(r"^(\$?)([A-Z]{1,3})(\$?)(\d+)$")


def col_letra(n):
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def col_indice(letras):
    n = 0
    for ch in letras:
        n = n * 26 + ord(ch) - 64
    return n


def _celula_ref(ref):
    m = _RE_CEL.match(ref)
    if not m:
        raise ErroXlsx(f"referência inválida: {ref!r}")
    return col_indice(m.group(2)), int(m.group(4))


def _intervalo_ref(ref):
    """'A1:C5' ou 'A1' -> (c1, r1, c2, r2)."""
    a, _, b = ref.replace("$", "").partition(":")
    c1, r1 = _celula_ref(a)
    c2, r2 = _celula_ref(b or a)
    return c1, r1, c2, r2


def _norm(texto):
    t = unicodedata.normalize("NFKD", str(texto))
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold()
    return re.sub(r"\s+", " ", t).strip().rstrip("?.:").strip()


# tokens de fórmula: texto entre aspas, referência estruturada [..], ou referência A1 (com aba)
_TOKEN = re.compile(
    r"""(?P<txt>"(?:[^"]|"")*")
      | (?P<est>\[(?:[^\[\]]|\[[^\]]*\])*\])
      | (?P<ref>(?<![\w.$!'])(?:(?P<aba>'(?:[^']|'')+'|[^\W\d][\w.]*)!)?
           (?P<a>\$?[A-Z]{1,3}\$?\d+)(?::(?P<b>\$?[A-Z]{1,3}\$?\d+))?(?![\w(!]))""", re.X)


def _nome_aba(token):
    return token[1:-1].replace("''", "'") if token.startswith("'") else token


def _deslocar_ref(ref, dl, dc):
    m = _RE_CEL.match(ref)
    cd, c, ld, l = m.groups()
    ci = col_indice(c) + (0 if cd else dc)
    li = int(l) + (0 if ld else dl)
    if ci < 1 or li < 1:
        raise ErroXlsx(f"fórmula deslocada para fora da planilha: {ref}")
    return f"{cd}{col_letra(ci)}{ld}{li}"


def deslocar_formula(formula, dl, dc=0):
    """Copia a fórmula como o Excel faz ao arrastar: refs relativas deslocam; $ fixa."""
    def sub(m):
        if not m.group("ref"):
            return m.group(0)
        aba = m.group("aba")
        a = _deslocar_ref(m.group("a"), dl, dc)
        b = f":{_deslocar_ref(m.group('b'), dl, dc)}" if m.group("b") else ""
        return (aba + "!" if aba else "") + a + b
    return _TOKEN.sub(sub, formula)


def _tem_ref_a1(formula):
    return any(m.group("ref") for m in _TOKEN.finditer(formula))


# ------------------------------------------------------------------ pacote (zip)

class Pacote:
    def __init__(self, caminho):
        self.caminho = Path(caminho)
        try:
            with zipfile.ZipFile(self.caminho) as z:
                self._infos = z.infolist()
                self._dados = {i.filename: z.read(i.filename) for i in self._infos}
        except zipfile.BadZipFile as e:
            raise ErroXlsx(f"{caminho}: não é um .xlsx válido ({e})") from e
        self._originais = dict(self._dados)

    def nomes(self):
        return list(self._dados)

    def existe(self, nome):
        return nome in self._dados

    def texto(self, nome):
        try:
            return self._dados[nome].decode("utf-8")
        except UnicodeDecodeError as e:
            raise NaoSuportado(f"{nome}: codificação diferente de UTF-8") from e

    def definir(self, nome, texto):
        dados = texto.encode("utf-8")
        if nome not in self._dados:
            self._infos.append(zipfile.ZipInfo(nome, (2026, 1, 1, 0, 0, 0)))
            self._infos[-1].compress_type = zipfile.ZIP_DEFLATED
        self._dados[nome] = dados

    def remover(self, nome):
        if nome in self._dados:
            del self._dados[nome]
            self._infos = [i for i in self._infos if i.filename != nome]

    def alteradas(self):
        return sorted(n for n, d in self._dados.items() if self._originais.get(n) != d)

    def removidas(self):
        return sorted(set(self._originais) - set(self._dados))

    def gravar(self, destino):
        destino = Path(destino)
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_name(destino.name + ".tmp")
        with zipfile.ZipFile(tmp, "w") as out:
            for info in self._infos:
                out.writestr(info, self._dados[info.filename], compress_type=info.compress_type)
        os.replace(tmp, destino)

    # relacionamentos -----------------------------------------------------
    @staticmethod
    def _rels_de(parte):
        pasta, nome = posixpath.split(parte)
        return posixpath.join(pasta, "_rels", nome + ".rels")

    def rels(self, parte):
        """[(Id, Type, alvo_resolvido)] da parte (alvo interno, com caminho completo no pacote)."""
        rp = self._rels_de(parte)
        if rp not in self._dados:
            return []
        saida = []
        for r in ET.fromstring(self._dados[rp]):
            if r.get("TargetMode") == "External":
                continue
            alvo = r.get("Target")
            alvo = alvo.lstrip("/") if alvo.startswith("/") else posixpath.normpath(
                posixpath.join(posixpath.dirname(parte), alvo))
            saida.append((r.get("Id"), r.get("Type"), alvo))
        return saida

    def parte_da_aba(self, nome):
        wb = ET.fromstring(self._dados["xl/workbook.xml"])
        for s in wb.find("m:sheets", NS):
            if s.get("name", "").casefold() == nome.casefold():
                rid = s.get(f"{{{NS['r']}}}id")
                for i, _t, alvo in self.rels("xl/workbook.xml"):
                    if i == rid:
                        return alvo
        nomes = [s.get("name") for s in wb.find("m:sheets", NS)]
        raise ErroXlsx(f"aba {nome!r} não existe; abas: {nomes}")

    def nome_da_aba(self, parte):
        wb = ET.fromstring(self._dados["xl/workbook.xml"])
        ids = {i: alvo for i, _t, alvo in self.rels("xl/workbook.xml")}
        for s in wb.find("m:sheets", NS):
            if ids.get(s.get(f"{{{NS['r']}}}id")) == parte:
                return s.get("name")


# ------------------------------------------------------------------ folha (sheetData em texto)

_RE_LINHA = re.compile(r"<row\b([^>]*?)(?:/>|>(.*?)</row>)", re.S)
_RE_CELULA = re.compile(r"<c\b([^>]*?)(?:/>|>(.*?)</c>)", re.S)
_RE_ATTR = re.compile(r'([\w:.-]+)="([^"]*)"')


class Cel:
    def __init__(self, attrs, inner):
        self.attrs = dict(_RE_ATTR.findall(attrs))
        self.ref = self.attrs.pop("r", None) if "r" in self.attrs else None
        self.inner = inner or ""
        self.col = _celula_ref(self.ref)[0] if self.ref else 0

    @property
    def estilo(self):
        return self.attrs.get("s")

    @property
    def tem_formula(self):
        return "<f" in self.inner

    @property
    def tem_valor(self):
        return bool(re.search(r"<v>[^<]+</v>", self.inner) or re.search(r"<t(?:\s[^>]*)?>[^<]+</t>", self.inner))

    @property
    def vazia(self):
        return not (self.tem_valor or self.tem_formula)

    def xml(self):
        a = "".join(f' {k}="{v}"' for k, v in self.attrs.items())
        corpo = f"<c r=\"{self.ref}\"{a}"
        return corpo + (f">{self.inner}</c>" if self.inner else "/>")


class Lin:
    def __init__(self, n, attrs, inner):
        self.n = n
        self.attrs = {k: v for k, v in _RE_ATTR.findall(attrs) if k != "r"}
        self.celulas = [Cel(m.group(1), m.group(2)) for m in _RE_CELULA.finditer(inner or "")]
        self.modificada = False

    def celula(self, col):
        for c in self.celulas:
            if c.col == col:
                return c
        return None

    def definir(self, cel):
        self.modificada = True
        for i, c in enumerate(self.celulas):
            if c.col == cel.col:
                self.celulas[i] = cel
                return
            if c.col > cel.col:
                self.celulas.insert(i, cel)
                return
        self.celulas.append(cel)

    def xml(self):
        a = "".join(f' {k}="{v}"' for k, v in self.attrs.items())
        if not self.celulas:
            return f'<row r="{self.n}"{a}/>'
        return f'<row r="{self.n}"{a}>' + "".join(c.xml() for c in self.celulas) + "</row>"


class Folha:
    """sheetData de uma aba: linhas não tocadas voltam com o texto original, idêntico."""

    def __init__(self, xml):
        i = xml.find("<sheetData")
        if i < 0:
            raise NaoSuportado("aba sem <sheetData> (prefixo de namespace diferente?)")
        fim_tag = xml.index(">", i)
        if xml[fim_tag - 1] == "/":
            self.pre, self.pos, interno = xml[:i], xml[fim_tag + 1:], ""
            self._abertura = xml[i:fim_tag + 1]
        else:
            j = xml.index("</sheetData>", fim_tag)
            self.pre, self.pos = xml[:i], xml[j + len("</sheetData>"):]
            self._abertura = xml[i:fim_tag + 1]
            interno = xml[fim_tag + 1:j]
        self._bruto = {}      # n -> (separador, texto original)
        self._lin = {}        # n -> Lin (parseada)
        ultimo, fim = 0, 0
        for m in _RE_LINHA.finditer(interno):
            attrs = m.group(1)
            r = re.search(r'\sr="(\d+)"', attrs)
            if not r:
                raise NaoSuportado("linha sem atributo r")
            n = int(r.group(1))
            if n <= ultimo:
                raise NaoSuportado(f"linhas fora de ordem ou repetidas (linha {n})")
            self._bruto[n] = (interno[fim:m.start()], m.group(0))
            ultimo, fim = n, m.end()
        self._cauda = interno[fim:]

    def numeros(self):
        return sorted(set(self._bruto) | set(self._lin))

    def linha(self, n, criar=False):
        if n in self._lin:
            return self._lin[n]
        if n in self._bruto:
            m = _RE_LINHA.match(self._bruto[n][1])
            self._lin[n] = Lin(n, m.group(1), m.group(2))
            return self._lin[n]
        if not criar:
            return None
        self._lin[n] = Lin(n, "", "")
        self._lin[n].modificada = True
        return self._lin[n]

    def texto_bruto(self, n):
        return self._bruto[n][1] if n in self._bruto and n not in self._lin else None

    def ultima_linha(self):
        ns = self.numeros()
        return ns[-1] if ns else 0

    def renderizar(self):
        partes, sep_padrao = [], ""
        for n in self.numeros():
            sep, bruto = self._bruto.get(n, (sep_padrao, None))
            sep_padrao = sep or sep_padrao
            lin = self._lin.get(n)
            partes.append(sep + (lin.xml() if (lin and lin.modificada) or bruto is None else bruto))
        corpo = "".join(partes) + self._cauda
        if not corpo and self._abertura.endswith("/>"):
            return self.pre + self._abertura + self.pos
        abertura = self._abertura[:-2] + ">" if self._abertura.endswith("/>") else self._abertura
        return self.pre + abertura + corpo + "</sheetData>" + self.pos


# ------------------------------------------------------------------ valores -> XML

_ILEGAIS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")


def _serial(v, base1904):
    base = datetime.datetime(1904, 1, 1) if base1904 else datetime.datetime(1899, 12, 30)
    if not isinstance(v, datetime.datetime):
        v = datetime.datetime(v.year, v.month, v.day)
    d = v - base
    s = d.days + d.seconds / 86400
    return int(s) if s == int(s) else s


def _inner_valor(v, base1904=False):
    """(t, inner) da célula para o valor Python v."""
    if v is None:
        return None, ""
    if isinstance(v, Formula):
        return None, f"<f>{html.escape(str(v), quote=False)}</f>"
    if isinstance(v, bool):
        return "b", f"<v>{int(v)}</v>"
    if isinstance(v, (datetime.date, datetime.datetime)):
        return None, f"<v>{_serial(v, base1904)}</v>"
    if isinstance(v, int):
        return None, f"<v>{v}</v>"
    if isinstance(v, (float, Decimal)):
        if v != v or v in (float("inf"), float("-inf")):
            raise ErroXlsx("NaN/infinito não cabe em célula")
        return None, f"<v>{format(v, 'f') if isinstance(v, Decimal) else repr(v)}</v>"
    if isinstance(v, str):
        if len(v) > LIMITE_CELULA:
            raise ErroXlsx(f"texto com {len(v)} caracteres: o Excel aceita no máximo {LIMITE_CELULA} por célula")
        t = _ILEGAIS.sub("", v).replace("\r\n", "\n").replace("\r", "\n")
        return "inlineStr", f'<is><t xml:space="preserve">{html.escape(t, quote=False)}</t></is>'
    raise ErroXlsx(f"tipo sem suporte para célula: {type(v).__name__}")


# ------------------------------------------------------------------ extensão de intervalos

class Extensor:
    """Reescreve referências que cobrem a tabela inteira (ou uma coluna dela até a última linha)
    para cobrir também as linhas/colunas acrescentadas. Referência para uma célula só, ou que
    termina antes da última linha, nunca muda."""

    def __init__(self, aba, col1, col2, lin_cab, lin1, lin2, nova_lin2, nova_col2):
        self.aba, self.col1, self.col2 = aba, col1, col2
        self.lin_cab, self.lin1, self.lin2 = lin_cab, lin1, lin2
        self.nova_lin2, self.nova_col2 = nova_lin2, nova_col2

    @property
    def mudou(self):
        return self.nova_lin2 != self.lin2 or self.nova_col2 != self.col2

    def intervalo(self, c1, r1, c2, r2):
        if c1 == c2 and r1 == r2 and not (self.lin1 == self.lin2 and r1 == self.lin1):
            return c1, r1, c2, r2     # uma célula só
        dentro = self.col1 <= c1 and c2 <= self.col2 and self.lin_cab <= r1 <= self.lin2
        if not dentro:
            return c1, r1, c2, r2
        nr2 = self.nova_lin2 if (r2 == self.lin2 and (r1 < r2 or r1 == self.lin1)) else r2
        nc2 = c2
        if (c1 == self.col1 and c2 == self.col2 and r2 == self.lin2 and r1 in (self.lin_cab, self.lin1)):
            nc2 = self.nova_col2
        return c1, r1, nc2, nr2

    @staticmethod
    def _ref_com_dolar(original, c2, r2):
        """Refaz 'b' preservando os $ do original."""
        m = _RE_CEL.match(original)
        return f"{m.group(1)}{col_letra(c2)}{m.group(3)}{r2}"

    def formula(self, texto, na_aba):
        """Texto de fórmula -> texto de fórmula. na_aba: as refs sem aba são da aba da tabela."""
        def sub(m):
            if not m.group("ref") or not m.group("b"):
                return m.group(0)
            aba = m.group("aba")
            if aba:
                if _nome_aba(aba).casefold() != self.aba.casefold():
                    return m.group(0)
            elif not na_aba:
                return m.group(0)
            a, b = m.group("a"), m.group("b")
            c1, r1, c2, r2 = _intervalo_ref(f"{a}:{b}")
            n1, nr1, n2, nr2 = self.intervalo(c1, r1, c2, r2)
            if (n2, nr2) == (c2, r2):
                return m.group(0)
            return (aba + "!" if aba else "") + a + ":" + self._ref_com_dolar(b, n2, nr2)
        return _TOKEN.sub(sub, texto)

    def sqref(self, texto):
        saida = []
        for tok in texto.split():
            if ":" not in tok and not (self.lin1 == self.lin2):
                saida.append(tok)
                continue
            c1, r1, c2, r2 = _intervalo_ref(tok)
            n1, nr1, n2, nr2 = self.intervalo(c1, r1, c2, r2)
            if (n2, nr2) == (c2, r2):
                saida.append(tok)
            else:
                saida.append(f"{col_letra(c1)}{r1}:{col_letra(n2)}{nr2}")
        return " ".join(saida)

    def ref(self, texto):
        """ref='A1:AC11' (autoFilter, dimension...)."""
        return self.sqref(texto)


def _sub_f(xml, extensor, na_aba, tags=r"(?:\w+:)?f|formula[12]?|definedName|(?:\w+:)?formula[12]?"):
    """Aplica extensor.formula ao conteúdo de <f>, <c:f>, <xm:f>, <formula*>, <definedName>."""
    def sub(m):
        bruto = m.group(2)
        if not bruto or "!" not in bruto and not na_aba:
            return m.group(0)
        txt = html.unescape(bruto)
        novo = extensor.formula(txt, na_aba)
        if novo == txt:
            return m.group(0)
        return m.group(1) + html.escape(novo, quote=False) + m.group(3)
    return re.sub(rf"(<(?:{tags})\b[^>]*(?<!/)>)(.*?)(</(?:{tags})>)", sub, xml, flags=re.S)


# ------------------------------------------------------------------ edição

_EST_DATA_BUILTIN = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))


class Edicao:
    """Uma ou mais operações sobre UMA aba de um .xlsx; `salvar(destino)` grava tudo de uma vez."""

    def __init__(self, origem, aba, tabela=None, linha_cabecalho=1, humanos=None, preservar_humanos=True,
                 invalidar_cache=True):
        self.invalidar_cache = invalidar_cache
        self.origem = Path(origem)
        self.pac = Pacote(origem)
        self.aba = self.pac.nome_da_aba(self.pac.parte_da_aba(aba)) or aba
        self.parte = self.pac.parte_da_aba(aba)
        self.folha = Folha(self.pac.texto(self.parte))
        self.preservar_humanos = preservar_humanos
        self.avisos, self.ignoradas = [], []
        self._ss = None
        self._xfs_data = None
        self._base1904 = 'date1904="1"' in self.pac.texto("xl/workbook.xml")
        self._carregar_regiao(tabela, linha_cabecalho)
        self.colunas_humanas = self._resolver_humanos(humanos)
        self.lin2_orig, self.col2_orig = self.lin2, self.col2
        self.escritas = 0
        self.inseridas = 0
        self._primeira = None
        self._avisou_data = set()

    # ---- região -------------------------------------------------------------
    def _carregar_regiao(self, nome_tabela, linha_cabecalho):
        tabelas = []
        for _i, tipo, alvo in self.pac.rels(self.parte):
            if tipo.endswith("/table"):
                tx = self.pac.texto(alvo)
                raiz = re.search(r"<table\b[^>]*>", tx).group(0)
                tabelas.append((alvo, html.unescape(re.search(r'\sdisplayName="([^"]*)"', raiz).group(1)),
                                re.search(r'\sref="([^"]+)"', raiz).group(1), raiz))
        if nome_tabela:
            tabelas = [t for t in tabelas if t[1].casefold() == nome_tabela.casefold()]
            if not tabelas:
                raise ErroXlsx(f"tabela {nome_tabela!r} não existe na aba {self.aba!r}")
        if len(tabelas) > 1:
            raise ErroXlsx(f"a aba {self.aba!r} tem várias tabelas {[t[1] for t in tabelas]}: informe `tabela=`")
        self.tabela_parte = self.tabela_nome = None
        if tabelas:
            parte, nome, ref, raiz = tabelas[0]
            if re.search(r'\stotalsRowCount="[1-9]', raiz):
                raise NaoSuportado("tabela com linha de totais (totalsRowCount): linhas novas precisam entrar "
                                   "antes dos totais; não suportado no protótipo")
            if re.search(r'\sheaderRowCount="0"', raiz):
                raise NaoSuportado("tabela sem linha de cabeçalho")
            self.tabela_parte, self.tabela_nome = parte, nome
            self.col1, self.lin_cab, self.col2, self.lin2 = _intervalo_ref(ref)
            self.lin1 = self.lin_cab + 1
            self.col1, self.lin_cab, self.col2, self.lin2 = self.col1, self.lin_cab, self.col2, self.lin2
        else:   # sem tabela: região deduzida do cabeçalho
            self.lin_cab = linha_cabecalho
            cab = self.folha.linha(linha_cabecalho)
            cols = [c.col for c in (cab.celulas if cab else []) if not c.vazia]
            if not cols:
                raise ErroXlsx(f"aba {self.aba!r} sem tabela e sem cabeçalho na linha {linha_cabecalho}")
            self.col1, self.col2 = min(cols), max(cols)
            self.lin1 = self.lin_cab + 1
            self.lin2 = self.lin_cab
            for n in self.folha.numeros():
                if n <= self.lin_cab:
                    continue
                lin = self.folha.linha(n)
                if any(not c.vazia for c in lin.celulas if self.col1 <= c.col <= self.col2):
                    self.lin2 = n
            self.avisos.append("aba sem Tabela do Excel: região deduzida do cabeçalho; nada de tabela a estender")
        cab = self.folha.linha(self.lin_cab)
        if cab is None:
            raise ErroXlsx(f"linha de cabeçalho {self.lin_cab} não existe na aba {self.aba!r}")
        self.cabecalhos = {}   # índice de coluna -> texto
        for c in range(self.col1, self.col2 + 1):
            cel = cab.celula(c) if cab else None
            self.cabecalhos[c] = self._texto(cel) if cel else ""

    def _texto(self, cel):
        if cel is None:
            return ""
        t = cel.attrs.get("t")
        if t == "s":
            m = re.search(r"<v>(\d+)</v>", cel.inner)
            return self._compartilhadas()[int(m.group(1))] if m else ""
        if t == "inlineStr":
            return html.unescape("".join(re.findall(r"<t(?:\s[^>]*)?>(.*?)</t>", cel.inner, re.S)))
        m = re.search(r"<v>(.*?)</v>", cel.inner, re.S)
        return html.unescape(m.group(1)) if m else ""

    def _compartilhadas(self):
        if self._ss is None:
            self._ss = []
            if self.pac.existe("xl/sharedStrings.xml"):
                txt = self.pac.texto("xl/sharedStrings.xml")
                for m in re.finditer(r"<si\b[^>]*?(?:/>|>(.*?)</si>)", txt, re.S):
                    corpo = re.sub(r"<rPh\b.*?</rPh>", "", m.group(1) or "", flags=re.S)
                    self._ss.append(html.unescape("".join(re.findall(r"<t(?:\s[^>]*)?>(.*?)</t>", corpo, re.S))))
        return self._ss

    def coluna(self, spec):
        """Índice de coluna a partir de int, cabeçalho (tolerante a acento/caixa) ou letra."""
        if isinstance(spec, int):
            return spec
        achados = [c for c, t in self.cabecalhos.items() if _norm(t) == _norm(spec) and t != ""]
        if len(achados) > 1:
            raise ColunaDesconhecida(f"cabeçalho ambíguo {spec!r}: colunas {[col_letra(c) for c in achados]}")
        if achados:
            return achados[0]
        if re.fullmatch(r"[A-Za-z]{1,3}", str(spec)):
            return col_indice(str(spec).upper())
        raise ColunaDesconhecida(f"coluna {spec!r} não existe na aba {self.aba!r}; cabeçalhos: "
                                 f"{[t for t in self.cabecalhos.values()]}")

    def _resolver_humanos(self, humanos):
        cols = set()
        for h in humanos or ():
            try:
                cols.add(self.coluna(h))
            except ColunaDesconhecida:
                self.avisos.append(f"coluna humana {h!r} não existe nesta planilha (ignorada)")
        return cols

    # ---- estilos ---------------------------------------------------------------
    def _estilo_eh_data(self, s):
        if self._xfs_data is None:
            self._xfs_data = set()
            if self.pac.existe("xl/styles.xml"):
                st = self.pac.texto("xl/styles.xml")
                custom = {}
                for m in re.finditer(r'<numFmt\b[^>]*?numFmtId="(\d+)"[^>]*?formatCode="([^"]*)"', st):
                    custom[int(m.group(1))] = html.unescape(m.group(2))
                bloco = re.search(r"<cellXfs\b[^>]*>(.*?)</cellXfs>", st, re.S)
                for i, m in enumerate(re.finditer(r"<xf\b([^>]*?)(?:/>|>)", bloco.group(1) if bloco else "")):
                    nid = re.search(r'numFmtId="(\d+)"', m.group(1))
                    nid = int(nid.group(1)) if nid else 0
                    cod = re.sub(r'"[^"]*"|\[[^\]]*\]|\\.', "", custom.get(nid, ""))
                    if nid in _EST_DATA_BUILTIN or (nid in custom and re.search(r"[dmyhs]", cod, re.I)):
                        self._xfs_data.add(i)
        return int(s) in self._xfs_data if s is not None else False

    # ---- modelo da linha ---------------------------------------------------------
    def _linha_modelo(self):
        n = self.lin2 if self.lin2 >= self.lin1 else None
        return self.folha.linha(n) if n else None

    def _formulas_compartilhadas(self):
        """si -> (ref_mestre, texto) das fórmulas compartilhadas da aba."""
        mestres = {}
        for m in re.finditer(r'<c r="([A-Z]+\d+)"[^>]*>(?:(?!</c>).)*?<f\b([^>]*)>(.*?)</f>',
                             "".join(b for _s, b in self.folha._bruto.values()), re.S):
            if 't="shared"' in m.group(2) and m.group(3):
                si = re.search(r'si="(\d+)"', m.group(2)).group(1)
                mestres[si] = (m.group(1), html.unescape(m.group(3)))
        return mestres

    def _colunas_calculadas(self):
        """índice de coluna -> texto da calculatedColumnFormula (da Tabela)."""
        if not self.tabela_parte:
            return {}
        tx = self.pac.texto(self.tabela_parte)
        saida = {}
        for i, m in enumerate(re.finditer(r"<tableColumn\b([^>]*?)(?:/>|>(.*?)</tableColumn>)", tx, re.S)):
            f = re.search(r"<calculatedColumnFormula\b[^>]*>(.*?)</calculatedColumnFormula>", m.group(2) or "", re.S)
            if f:
                saida[self.col1 + i] = html.unescape(f.group(1))
        return saida

    def _formula_da_coluna(self, col, r, modelo, calc, mestres):
        """Texto da fórmula da coluna col na linha r, ou None se a coluna não é calculada."""
        if col in calc:
            return calc[col]
        cel = modelo.celula(col) if modelo else None
        if cel is None or not cel.tem_formula:
            return None
        m = re.search(r"<f\b([^>]*?)(?:/>|>(.*?)</f>)", cel.inner, re.S)
        attrs, texto = m.group(1), html.unescape(m.group(2) or "")
        if 't="array"' in attrs:
            return None
        if 't="shared"' in attrs:
            si = re.search(r'si="(\d+)"', attrs).group(1)
            if si not in mestres:
                raise NaoSuportado(f"fórmula compartilhada si={si} sem mestre")
            ref_m, texto_m = mestres[si]
            cm, lm = _celula_ref(ref_m)
            return deslocar_formula(texto_m, r - lm, col - cm)
        return deslocar_formula(texto, r - modelo.n, 0)

    # ---- operações ------------------------------------------------------------------
    def _criar_celula(self, ref, estilo, valor):
        t, inner = _inner_valor(valor, self._base1904)
        cel = Cel(f'r="{ref}"', inner)
        if estilo is not None:
            cel.attrs["s"] = estilo
        if t:
            cel.attrs["t"] = t
        return cel

    def _avisar_data(self, col, valor, estilo):
        if isinstance(valor, (datetime.date, datetime.datetime)) and col not in self._avisou_data \
                and not self._estilo_eh_data(estilo):
            self._avisou_data.add(col)
            self.avisos.append(f"coluna {col_letra(col)} ({self.cabecalhos.get(col, '')}): data gravada em célula "
                               "sem formato de data (aparecerá como número)")

    def inserir_linhas(self, linhas, colunas=None, sobrescrever_formulas=False):
        if not linhas:
            return
        mapa = colunas or {}
        indices = []   # por linha: {col: valor}
        for k, linha in enumerate(linhas):
            d = {}
            for chave, valor in linha.items():
                col = self.coluna(mapa.get(chave, chave))
                if not (self.col1 <= col <= self.col2):
                    raise ColunaDesconhecida(f"coluna {chave!r} fora da tabela")
                d[col] = valor
            indices.append(d)
        n = len(linhas)
        ini = self.lin2 + 1
        self._checar_faixa(ini, ini + n - 1)
        modelo = self._linha_modelo()
        calc = self._colunas_calculadas()
        mestres = self._formulas_compartilhadas()
        attrs_modelo = {k: v for k, v in (modelo.attrs if modelo else {}).items()
                        if k not in ("hidden", "collapsed")}
        for k, valores in enumerate(indices):
            r = ini + k
            lin = self.folha.linha(r, criar=True)
            if not lin.celulas and not lin.attrs:
                lin.attrs = dict(attrs_modelo)
            for col in range(self.col1, self.col2 + 1):
                cel_m = modelo.celula(col) if modelo else None
                estilo = cel_m.estilo if cel_m is not None else None
                antiga = lin.celula(col)
                if estilo is None and antiga is not None:
                    estilo = antiga.estilo
                formula = self._formula_da_coluna(col, r, modelo, calc, mestres)
                if formula is not None:
                    if col in valores and not sobrescrever_formulas:
                        self.avisos.append(f"linha {r}: coluna calculada {self.cabecalhos[col]!r} mantém a "
                                           "fórmula (valor informado ignorado)")
                    if col in valores and sobrescrever_formulas:
                        valor = valores[col]
                    else:
                        valor = Formula(formula)
                else:
                    valor = valores.get(col)
                if valor is None:
                    if estilo is not None or antiga is not None:
                        lin.definir(self._criar_celula(f"{col_letra(col)}{r}", estilo, None))
                    continue
                self._avisar_data(col, valor, estilo)
                lin.definir(self._criar_celula(f"{col_letra(col)}{r}", estilo, valor))
                self.escritas += 1
            lin.modificada = True
        self._primeira = self._primeira or ini
        self.lin2 = ini + n - 1
        self.inseridas += n

    def _checar_faixa(self, a, b):
        for r in range(a, b + 1):
            lin = self.folha.linha(r)
            if lin is None:
                continue
            for c in lin.celulas:
                if self.col1 <= c.col <= self.col2 and not c.vazia:
                    raise ConflitoDeConteudo(
                        f"{c.ref} já tem conteúdo logo abaixo da tabela; inserir linhas ali sobrescreveria dados "
                        "(o protótipo não desloca o que está abaixo da tabela)")
        xml = self.folha.pos
        for m in re.finditer(r'<mergeCell\b[^>]*?\sref="([^"]+)"', xml):
            c1, r1, c2, r2 = _intervalo_ref(m.group(1))
            if r2 >= a and r1 <= b and c2 >= self.col1 and c1 <= self.col2:
                raise ConflitoDeConteudo(f"célula mesclada {m.group(1)} na faixa onde entrariam as linhas novas")

    def escrever_celulas(self, celulas, sobrescrever_formulas=False):
        modelo = self._linha_modelo()
        for (linha, coluna), valor in celulas.items():
            col = self.coluna(coluna)
            ref = f"{col_letra(col)}{linha}"
            if valor is None:
                continue
            lin = self.folha.linha(linha, criar=True)
            antiga = lin.celula(col)
            if antiga is not None and not antiga.vazia:
                if antiga.tem_formula and not sobrescrever_formulas:
                    self.ignoradas.append((ref, "tem fórmula"))
                    continue
                if col in self.colunas_humanas and self.preservar_humanos:
                    self.ignoradas.append((ref, "campo humano já preenchido"))
                    continue
            if antiga is not None and antiga.estilo is not None:
                estilo = antiga.estilo
            else:
                cel_m = modelo.celula(col) if (modelo and self.lin1 <= linha <= self.lin2) else None
                estilo = cel_m.estilo if cel_m is not None else None
            if valor is LIMPAR:
                nova = self._criar_celula(ref, estilo, None)
            else:
                self._avisar_data(col, valor, estilo)
                nova = self._criar_celula(ref, estilo, valor)
            lin.definir(nova)
            self.escritas += 1

    def acrescentar_coluna(self, cabecalho, valores=None, formula=None, estilo_de=None):
        if not self.tabela_parte:
            raise NaoSuportado("acrescentar_coluna exige Tabela do Excel na aba")
        if self.inseridas:
            raise NaoSuportado("acrescentar_coluna deve vir antes de inserir_linhas na mesma Edicao")
        if "\n" in cabecalho or "\r" in cabecalho or not cabecalho.strip():
            raise ErroXlsx("cabeçalho inválido (vazio ou com quebra de linha)")
        existente = [c for c, t in self.cabecalhos.items() if _norm(t) == _norm(cabecalho)]
        if existente:     # idempotente: só preenche o que estiver vazio
            col = existente[0]
            self.avisos.append(f"coluna {cabecalho!r} já existe; só células vazias foram preenchidas")
            preencher_so_vazias = True
        else:
            col = self.col2 + 1
            preencher_so_vazias = False
            for r in range(self.lin_cab, self.lin2 + 1):
                lin = self.folha.linha(r)
                c = lin.celula(col) if lin else None
                if c is not None and not c.vazia:
                    raise ConflitoDeConteudo(f"{c.ref} já tem conteúdo: a coluna nova não cabe ao lado da tabela")
        modelo_cab = self.folha.linha(self.lin_cab)
        col_estilo = self.coluna(estilo_de) if estilo_de else self.col2
        if isinstance(valores, (list, tuple)):
            if len(valores) != self.lin2 - self.lin1 + 1:
                raise ErroXlsx(f"valores tem {len(valores)} itens e a tabela tem {self.lin2 - self.lin1 + 1} linhas")
            valores = {self.lin1 + i: v for i, v in enumerate(valores)}
        valores = valores or {}
        if not preencher_so_vazias:
            # cabeçalho
            est = modelo_cab.celula(col_estilo)
            modelo_cab.definir(self._criar_celula(f"{col_letra(col)}{self.lin_cab}", est.estilo if est else None, cabecalho))
            self.cabecalhos[col] = cabecalho
            self.col2 = col
            self._tabela_nova_coluna(cabecalho, formula)
        for r in range(self.lin1, self.lin2 + 1):
            lin = self.folha.linha(r, criar=True)
            antiga = lin.celula(col)
            if antiga is not None and not antiga.vazia:
                continue
            ref_est = lin.celula(col_estilo)
            estilo = antiga.estilo if (antiga is not None and antiga.estilo) else (ref_est.estilo if ref_est else None)
            if formula and not preencher_so_vazias:
                valor = Formula(deslocar_formula(formula, r - self.lin1))
            else:
                valor = valores.get(r)
            if valor is None:
                if estilo is not None:
                    lin.definir(self._criar_celula(f"{col_letra(col)}{r}", estilo, None))
                continue
            self._avisar_data(col, valor, estilo)
            lin.definir(self._criar_celula(f"{col_letra(col)}{r}", estilo, valor))
            self.escritas += 1
        if not preencher_so_vazias:
            for r in range(self.lin_cab, self.lin2 + 1):   # spans
                lin = self.folha.linha(r)
                if lin and "spans" in lin.attrs:
                    a, _, b = lin.attrs["spans"].partition(":")
                    lin.attrs["spans"] = f"{a}:{max(int(b), col)}"
                    lin.modificada = True
            self._largura_da_coluna(col)

    def _tabela_nova_coluna(self, nome, formula):
        tx = self.pac.texto(self.tabela_parte)
        nomes = [html.unescape(n) for n in re.findall(r"<tableColumn\b[^>]*?\sname=\"([^\"]*)\"", tx)]
        if _norm(nome) in {_norm(n) for n in nomes}:
            raise ErroXlsx(f"coluna {nome!r} já existe na tabela")
        ids = [int(i) for i in re.findall(r"<tableColumn\b[^>]*?\sid=\"(\d+)\"", tx)]
        novo_id = max(ids) + 1
        corpo = ""
        if formula and not _tem_ref_a1(formula):     # só referência estruturada é "coluna calculada"
            corpo = f"<calculatedColumnFormula>{html.escape(formula, quote=False)}</calculatedColumnFormula>"
        elif formula:
            self.avisos.append("fórmula com referência A1: gravada nas células, mas a Tabela não a declara como "
                               "coluna calculada (linhas novas digitadas no Excel não herdam a fórmula)")
        col = (f'<tableColumn id="{novo_id}" name="{html.escape(nome, quote=True)}">{corpo}</tableColumn>'
               if corpo else f'<tableColumn id="{novo_id}" name="{html.escape(nome, quote=True)}"/>')
        tx = tx.replace("</tableColumns>", col + "</tableColumns>", 1)
        tx = re.sub(r'(<tableColumns\b[^>]*?\scount=")\d+', lambda m: m.group(1) + str(len(ids) + 1), tx, count=1)
        self.pac.definir(self.tabela_parte, tx)

    def _largura_da_coluna(self, col):
        xml = self.folha.pre
        cols = re.search(r"<cols>(.*?)</cols>", xml, re.S)
        novo = f'<col min="{col}" max="{col}" width="18" customWidth="1"/>'
        if cols:
            for m in re.finditer(r'<col\b[^>]*?>', cols.group(1)):
                mn = int(re.search(r'min="(\d+)"', m.group(0)).group(1))
                mx = int(re.search(r'max="(\d+)"', m.group(0)).group(1))
                if mn <= col <= mx:
                    return
            self.folha.pre = xml.replace("</cols>", novo + "</cols>", 1)
        else:
            self.folha.pre = xml + f"<cols>{novo}</cols>"

    # ---- salvar -------------------------------------------------------------------
    def salvar(self, destino):
        destino = Path(destino)
        if destino.resolve() == self.origem.resolve():
            raise ErroXlsx("destino igual à origem: o original nunca é sobrescrito")
        ext = Extensor(self.aba, self.col1, self.col2_orig, self.lin_cab, self.lin1, self.lin2_orig,
                       self.lin2, self.col2)
        mudou_estrutura = ext.mudou
        # 1. aba da tabela
        self._fechar_aba(ext)
        # 2. tabela
        if self.tabela_parte and mudou_estrutura:
            tx = self.pac.texto(self.tabela_parte)
            nova_ref = f"{col_letra(self.col1)}{self.lin_cab}:{col_letra(self.col2)}{self.lin2}"
            tx = re.sub(r'(<table\b[^>]*?\sref=")[^"]+(")', lambda m: m.group(1) + nova_ref + m.group(2), tx, count=1)
            tx = re.sub(r'(<autoFilter\b[^>]*?\sref=")([^"]+)(")',
                        lambda m: m.group(1) + (nova_ref if _intervalo_ref(m.group(2))[1] == self.lin_cab
                                                else m.group(2)) + m.group(3), tx, count=1)
            tx = re.sub(r'(<sortState\b[^>]*?\sref=")([^"]+)(")',
                        lambda m: m.group(1) + ext.ref(m.group(2)) + m.group(3), tx, count=1)
            self.pac.definir(self.tabela_parte, tx)
        if mudou_estrutura:
            self._propagar(ext)
        if self.escritas or mudou_estrutura:
            self._recalculo_ao_abrir()
            if self.invalidar_cache:
                self._invalidar_cache()
        self.pac.gravar(destino)
        r = Resultado(destino=destino, linhas_inseridas=self.inseridas, celulas_escritas=self.escritas,
                      ignoradas=list(self.ignoradas), avisos=list(self.avisos),
                      partes_alteradas=self.pac.alteradas(), partes_removidas=self.pac.removidas())
        if self.inseridas:
            r.primeira_linha, r.ultima_linha = self._primeira, self.lin2
        return r

    def _fechar_aba(self, ext):
        # fórmulas fora do corpo da tabela (nas linhas do corpo elas são relativas à linha)
        if ext.mudou:
            for n in self.folha.numeros():
                if ext.lin1 <= n <= self.lin2:
                    continue
                bruto = self.folha.texto_bruto(n)
                if bruto is not None and "<f" not in bruto:
                    continue
                lin = self.folha.linha(n)
                for c in lin.celulas:
                    if c.tem_formula:
                        novo = _sub_f(c.inner, ext, True)
                        if novo != c.inner:
                            c.inner, lin.modificada = novo, True
        xml = self.folha.renderizar()
        if ext.mudou:
            xml = re.sub(r'(<(?:conditionalFormatting|dataValidation|ignoredError)\b[^>]*?\ssqref=")([^"]*)(")',
                         lambda m: m.group(1) + ext.sqref(m.group(2)) + m.group(3), xml)
            xml = re.sub(r"(<xm:sqref>)(.*?)(</xm:sqref>)",
                         lambda m: m.group(1) + ext.sqref(m.group(2)) + m.group(3), xml)
            # fórmulas de regras (CF/DV) e x14
            if "</sheetData>" in xml:
                cabeca, _, resto = xml.partition("</sheetData>")
                xml = cabeca + "</sheetData>" + _sub_f(resto, ext, True, tags=r"formula[12]?|xm:f")
            xml = re.sub(r'(<autoFilter\b[^>]*?\sref=")([^"]+)(")',
                         lambda m: m.group(1) + ext.ref(m.group(2)) + m.group(3), xml)
        xml = self._dimensao(xml)
        self.pac.definir(self.parte, xml)

    def _dimensao(self, xml):
        m = re.search(r'<dimension\s+ref="([^"]+)"\s*/>', xml)
        if not m:
            return xml
        c1, r1, c2, r2 = _intervalo_ref(m.group(1))
        maxl = max(self.folha.ultima_linha(), r2)
        maxc = max(c2, self.col2)
        if (maxc, maxl) == (c2, r2):
            return xml
        return xml.replace(m.group(0), f'<dimension ref="{col_letra(c1)}{r1}:{col_letra(maxc)}{maxl}"/>', 1)

    def _propagar(self, ext):
        pac = self.pac
        # nomes definidos
        wb = pac.texto("xl/workbook.xml")
        novo = _sub_f(wb, ext, False, tags="definedName")
        if novo != wb:
            pac.definir("xl/workbook.xml", novo)
        for nome in pac.nomes():
            if nome == self.parte:
                continue
            if re.fullmatch(r"xl/worksheets/[^/]+\.xml", nome):
                txt = pac.texto(nome)
                if "<f" in txt or "formula" in txt:
                    novo = _sub_f(txt, ext, False)
                    if novo != txt:
                        pac.definir(nome, novo)
            elif re.fullmatch(r"xl/charts/[^/]*chart[^/]*\.xml", nome):
                txt = pac.texto(nome)
                novo = _sub_f(txt, ext, False, tags=r"(?:\w+:)?f")
                if novo != txt:
                    pac.definir(nome, novo)
        self._dinamicas(ext)

    def _dinamicas(self, ext):
        pac = self.pac
        caches = [n for n in pac.nomes() if re.fullmatch(r"xl/pivotCache/pivotCacheDefinition\d*\.xml", n)]
        for nome in caches:
            txt = pac.texto(nome)
            fonte = re.search(r"<worksheetSource\b([^>]*?)/?>", txt)
            if not fonte:
                continue
            a = dict(_RE_ATTR.findall(fonte.group(1)))
            nossa = (a.get("name", "").casefold() == (self.tabela_nome or "\0").casefold()) or \
                    (a.get("sheet", "").casefold() == self.aba.casefold() and "ref" in a)
            if not nossa:
                continue
            if "ref" in a and a.get("sheet", "").casefold() == self.aba.casefold():
                novo_ref = ext.ref(a["ref"])
                txt = txt.replace(f'ref="{a["ref"]}"', f'ref="{novo_ref}"', 1)
            if ext.nova_col2 != ext.col2:
                txt = self._dinamica_nova_coluna(nome, txt)
            raiz = re.search(r"<pivotCacheDefinition\b[^>]*>", txt).group(0)
            if 'refreshOnLoad="' in raiz:
                nova_raiz = re.sub(r'refreshOnLoad="[^"]*"', 'refreshOnLoad="1"', raiz)
            else:
                nova_raiz = raiz[:-1] + ' refreshOnLoad="1">'
            txt = txt.replace(raiz, nova_raiz, 1)
            pac.definir(nome, txt)

    def _dinamica_nova_coluna(self, nome_cache, txt):
        pac = self.pac
        if re.search(r"<pivotCacheDefinition\b[^>]*\sr:id=", txt) or any(
                t.endswith("/pivotCacheRecords") for _i, t, _a in pac.rels(nome_cache)):
            raise NaoSuportado("tabela dinâmica com cache de registros salvo: acrescentar coluna exigiria "
                               "descartar o cache; não suportado no protótipo")
        novos = [self.cabecalhos[c] for c in range(self.col2_orig + 1, self.col2 + 1)]
        campos = "".join(f'<cacheField name="{html.escape(n, quote=True)}" numFmtId="0"><sharedItems/></cacheField>'
                         for n in novos)
        txt = txt.replace("</cacheFields>", campos + "</cacheFields>", 1)
        txt = re.sub(r'(<cacheFields\b[^>]*?\scount=")(\d+)',
                     lambda m: m.group(1) + str(int(m.group(2)) + len(novos)), txt, count=1)
        for pt in pac.nomes():
            if re.fullmatch(r"xl/pivotTables/pivotTable\d*\.xml", pt) and any(
                    a == nome_cache for _i, _t, a in pac.rels(pt)):
                p = pac.texto(pt)
                p = p.replace("</pivotFields>", '<pivotField showAll="0"/>' * len(novos) + "</pivotFields>", 1)
                p = re.sub(r'(<pivotFields\b[^>]*?\scount=")(\d+)',
                           lambda m: m.group(1) + str(int(m.group(2)) + len(novos)), p, count=1)
                pac.definir(pt, p)
        return txt

    def _invalidar_cache(self):
        """Tira o valor em cache (<v>) de TODAS as fórmulas do arquivo. O Excel recalcularia sozinho
        (fullCalcOnLoad), mas o LibreOffice e leitores como pandas/openpyxl(data_only) confiam no cache e
        mostrariam números velhos (ex.: indicadores sem as linhas novas). Sem cache, calculam na hora ou
        mostram vazio: nunca um número desatualizado."""
        def limpa(m):
            if "<f" not in (m.group(2) or ""):
                return m.group(0)
            attrs = re.sub(r'\st="(?:str|n|b|e)"', "", m.group(1))
            inner = re.sub(r"<v>.*?</v>|<v\s*/>", "", m.group(2), flags=re.S)
            return f"<c{attrs}>{inner}</c>"
        for nome in self.pac.nomes():
            if re.fullmatch(r"xl/worksheets/[^/]+\.xml", nome):
                txt = self.pac.texto(nome)
                if "<f" in txt:
                    novo = _RE_CELULA.sub(limpa, txt)
                    if novo != txt:
                        self.pac.definir(nome, novo)

    def _recalculo_ao_abrir(self):
        pac = self.pac
        wb = pac.texto("xl/workbook.xml")
        m = re.search(r"<calcPr\b[^>]*?/?>", wb)
        if m:
            tag = m.group(0)
            if 'fullCalcOnLoad="' in tag:
                nova = re.sub(r'fullCalcOnLoad="[^"]*"', 'fullCalcOnLoad="1"', tag)
            else:
                nova = tag.replace("calcPr", 'calcPr fullCalcOnLoad="1"', 1)
            wb = wb.replace(tag, nova, 1)
        else:
            tag = '<calcPr fullCalcOnLoad="1"/>'
            for fim in ("</definedNames>", "</externalReferences>", "</sheets>"):
                if fim in wb:
                    wb = wb.replace(fim, fim + tag, 1)
                    break
            else:
                raise NaoSuportado("workbook.xml sem <sheets>")
        pac.definir("xl/workbook.xml", wb)
        for i, tipo, alvo in pac.rels("xl/workbook.xml"):
            if tipo.endswith("/calcChain"):
                pac.remover(alvo)
                rels = pac.texto("xl/_rels/workbook.xml.rels")
                rels = re.sub(rf'<Relationship\b[^>]*?\sId="{re.escape(i)}"[^>]*?/>', "", rels)
                pac.definir("xl/_rels/workbook.xml.rels", rels)
                ct = pac.texto("[Content_Types].xml")
                ct = re.sub(rf'<Override\b[^>]*?PartName="/{re.escape(alvo)}"[^>]*?/>', "", ct)
                pac.definir("[Content_Types].xml", ct)


# ------------------------------------------------------------------ API de função

def inserir_linhas(origem, destino, aba, linhas, colunas=None, *, tabela=None, linha_cabecalho=1,
                   sobrescrever_formulas=False):
    """Acrescenta `linhas` (lista de dicts) ao fim da tabela de `aba`.
    `colunas`: {chave_do_dict: cabeçalho}; None = as chaves já são cabeçalhos (tolerante a acento/caixa).
    Chave que não existe na planilha é erro (ColunaDesconhecida), nunca descarte silencioso."""
    ed = Edicao(origem, aba, tabela, linha_cabecalho)
    ed.inserir_linhas(linhas, colunas, sobrescrever_formulas)
    return ed.salvar(destino)


def escrever_celulas(origem, destino, aba, celulas, *, humanos=None, preservar_humanos=True,
                     sobrescrever_formulas=False, tabela=None, linha_cabecalho=1):
    """Grava {(linha, coluna): valor}; coluna = letra, cabeçalho ou índice. Campo humano com valor
    não é sobrescrito (vai em Resultado.ignoradas). Valor None = não mexe; LIMPAR = esvazia."""
    ed = Edicao(origem, aba, tabela, linha_cabecalho, humanos, preservar_humanos)
    ed.escrever_celulas(celulas, sobrescrever_formulas)
    return ed.salvar(destino)


def acrescentar_coluna(origem, destino, aba, cabecalho, valores=None, *, formula=None, estilo_de=None,
                       tabela=None, linha_cabecalho=1):
    """Acrescenta uma coluna à direita da tabela. `valores`: lista (uma por linha de dados) ou
    {linha: valor}; `formula`: texto sem '=' escrito para a primeira linha de dados (A1 relativo
    desloca por linha; referência estruturada vira coluna calculada da Tabela)."""
    ed = Edicao(origem, aba, tabela, linha_cabecalho)
    ed.acrescentar_coluna(cabecalho, valores, formula, estilo_de)
    return ed.salvar(destino)


def ler_coluna(caminho, aba, cabecalho, tabela=None, linha_cabecalho=1):
    """{linha: texto} dos valores da coluna `cabecalho` (para casar processos já na planilha)."""
    ed = Edicao(caminho, aba, tabela, linha_cabecalho)
    col = ed.coluna(cabecalho)
    saida = {}
    for r in range(ed.lin1, ed.lin2 + 1):
        lin = ed.folha.linha(r)
        cel = lin.celula(col) if lin else None
        if cel is not None and not cel.vazia:
            saida[r] = ed._texto(cel)
    return saida


# ------------------------------------------------------------------ adaptador ao contrato

CAMPOS_B = {   # campo da ficha v2 -> cabeçalho do modelo B
    "numero": "Número do Processo", "autores": "Autor(es)", "reus": "Réu(s)", "vara": "Vara",
    "municipio": "Município", "tribunal": "Tribunal", "data_ajuizamento": "Data do Ajuizamento",
    "area": "Área do Direito", "materia_principal": "Matéria Principal", "objeto": "Objeto",
    "valor_causa": "Valor da Causa", "situacao": "Situação", "valor_arbitrado": "Valor Arbitrado em Juízo",
    "probabilidade": "Probabilidade", "valor_estimado": "Valor Estimado", "valor_execucao": "Valor da Execução",
    "custas": "Custas Processuais", "depositos_recursais": "Depósitos Recursais",
    "garantias": "Garantias Processuais", "resultado": "Resultado", "data_transito": "Data do trânsito em julgado",
    "houve_recurso": "Houve recurso da empresa?", "percentual_exito": "Percentual de êxito",
    "terceirizado": "Reclamante terceirizado?", "outras_partes": "Outra(s) Parte(s)",
}
HUMANOS_B = ("probabilidade", "valor_estimado", "valor_arbitrado", "valor_execucao", "depositos_recursais",
             "garantias", "custas", "percentual_exito", "terceirizado", "resultado", "data_transito")


def _valor_da_ficha(ficha, campo):
    bruto = ficha.get(campo)
    if bruto is None:
        bruto = (ficha.get("campos", {}).get(campo) or {}).get("valor")
    if bruto in (None, ""):
        return None
    if isinstance(bruto, str):
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", bruto):
            return datetime.date.fromisoformat(bruto)
        if re.fullmatch(r"-?\d+\.\d{2}", bruto):    # dinheiro em texto decimal (contrato da ficha)
            return Decimal(bruto)
    return bruto


def gravar(molde, estado, destino, *, aba="Processos", campos=None, humanos=None, **opcoes):
    """Esboço do `escritores.xlsx_b.gravar(molde, estado, destino)` do contrato (CONTRATOS.md, 5):
    processos que já estão na planilha só recebem campos em células VAZIAS (nunca sobrescreve);
    processos novos entram ao fim da tabela. Devolve o dict `Resultado` do contrato."""
    campos = campos or CAMPOS_B
    humanos = [campos[h] for h in (humanos or HUMANOS_B) if h in campos]
    if molde is None:
        raise NaoSuportado("criar do modelo padrão (molde=None) é trabalho do WS-7 (src/modelos/)")
    existentes = {t.strip(): r for r, t in ler_coluna(molde, aba, campos["numero"]).items()}
    ed = Edicao(molde, aba, humanos=humanos)
    atualizados, novos, mudancas, novas_linhas, chaves = [], [], [], [], {}
    for ficha in estado.get("fichas", []):
        numero = ficha["numero"]
        valores = {campos[c]: _valor_da_ficha(ficha, c) for c in campos}
        valores = {k: v for k, v in valores.items() if v is not None}
        if numero in existentes:
            r = existentes[numero]
            cel = {}
            for cab, v in valores.items():
                col = ed.coluna(cab)
                lin = ed.folha.linha(r)
                atual = lin.celula(col) if lin else None
                if atual is None or atual.vazia:
                    cel[(r, col)] = v
                    mudancas.append({"numero": numero, "campo": cab, "antes": None, "depois": v})
            if cel:
                ed.escrever_celulas(cel)
                atualizados.append(numero)
        else:
            novas_linhas.append(valores)
            novos.append(numero)
    if novas_linhas:
        ed.inserir_linhas(novas_linhas)
        mudancas += [{"numero": n, "campo": "(linha nova)", "antes": None, "depois": "inserida"} for n in novos]
    res = ed.salvar(destino)
    return {"destino": res.destino, "processos_atualizados": atualizados, "processos_novos": novos,
            "mudancas": mudancas, "avisos": res.avisos + [f"{r}: {m}" for r, m in res.ignoradas]}


# ------------------------------------------------------------------ verificador do pacote

def validar(caminho):
    """Verificação de coerência estrutural do pacote. Devolve a lista de problemas (vazia = ok).
    NÃO substitui abrir no Excel: pega o que dá para pegar sem ele (XML malformado, linhas/células
    fora de ordem, ref da Tabela incoerente com o cabeçalho, ids repetidos, partes órfãs etc.)."""
    probs = []
    try:
        pac = Pacote(caminho)
    except ErroXlsx as e:
        return [str(e)]
    xmls = {}
    for n in pac.nomes():
        if n.endswith((".xml", ".rels")):
            try:
                xmls[n] = ET.fromstring(pac._dados[n])
            except ET.ParseError as e:
                probs.append(f"{n}: XML malformado ({e})")
    if probs:
        return probs
    # tipos de conteúdo
    ct = xmls.get("[Content_Types].xml")
    if ct is None:
        return ["[Content_Types].xml ausente"]
    over = {o.get("PartName").lstrip("/") for o in ct if o.tag.endswith("Override")}
    padrao = {d.get("Extension").lower() for d in ct if d.tag.endswith("Default")}
    for o in sorted(over):
        if o not in pac.nomes():
            probs.append(f"[Content_Types]: Override para parte inexistente {o}")
    for n in pac.nomes():
        if n != "[Content_Types].xml" and n not in over and n.rsplit(".", 1)[-1].lower() not in padrao:
            probs.append(f"{n}: sem tipo de conteúdo")
    # relacionamentos
    for n in pac.nomes():
        if n.endswith(".rels"):
            base = posixpath.dirname(posixpath.dirname(n))
            ids = set()
            for r in xmls[n]:
                if r.get("Id") in ids:
                    probs.append(f"{n}: Id repetido {r.get('Id')}")
                ids.add(r.get("Id"))
                if r.get("TargetMode") == "External":
                    continue
                t = r.get("Target")
                alvo = t.lstrip("/") if t.startswith("/") else posixpath.normpath(posixpath.join(base, t))
                if alvo not in pac.nomes():
                    probs.append(f"{n}: alvo inexistente {alvo}")
    # estilos
    st = pac._dados.get("xl/styles.xml", b"").decode("utf-8")
    bloco = re.search(r"<cellXfs\b[^>]*>(.*?)</cellXfs>", st, re.S)
    n_xf = len(re.findall(r"<xf\b", bloco.group(1))) if bloco else 0
    n_ss = None
    if "xl/sharedStrings.xml" in xmls:
        raiz = xmls["xl/sharedStrings.xml"]
        n_ss = len([e for e in raiz if e.tag.endswith("}si")])
        uc = raiz.get("uniqueCount")
        if uc is not None and int(uc) != n_ss:
            probs.append(f"sharedStrings: uniqueCount={uc} mas há {n_ss} <si>")
    # abas
    wb = xmls["xl/workbook.xml"]
    abas = {}
    ids_aba = set()
    for s in wb.find("m:sheets", NS):
        if s.get("sheetId") in ids_aba:
            probs.append(f"workbook: sheetId repetido {s.get('sheetId')}")
        ids_aba.add(s.get("sheetId"))
        rid = s.get(f"{{{NS['r']}}}id")
        for i, _t, alvo in pac.rels("xl/workbook.xml"):
            if i == rid:
                abas[alvo] = s.get("name")
    formulas = {}
    for parte, nome in abas.items():
        raiz = xmls.get(parte)
        if raiz is None:
            probs.append(f"aba {nome}: parte {parte} ausente")
            continue
        ultimo_r, max_c, max_r, forms = 0, 0, 0, set()
        sd = raiz.find("m:sheetData", NS)
        for row in sd:
            r = int(row.get("r"))
            if r <= ultimo_r:
                probs.append(f"{nome}: linha {r} fora de ordem/repetida")
            ultimo_r, max_r = r, max(max_r, r)
            ult_c = 0
            for c in row:
                col, lin = _celula_ref(c.get("r"))
                if lin != r:
                    probs.append(f"{nome}: célula {c.get('r')} dentro da linha {r}")
                if col <= ult_c:
                    probs.append(f"{nome}: célula {c.get('r')} fora de ordem/repetida")
                ult_c = col
                max_c = max(max_c, col)
                if c.get("s") is not None and n_xf and int(c.get("s")) >= n_xf:
                    probs.append(f"{nome}: {c.get('r')} usa estilo inexistente s={c.get('s')}")
                if c.get("t") == "s" and n_ss is not None:
                    v = c.find("m:v", NS)
                    if v is None or int(v.text) >= n_ss:
                        probs.append(f"{nome}: {c.get('r')} aponta para sharedString inexistente")
                if c.find("m:f", NS) is not None:
                    forms.add(c.get("r"))
            sp = row.get("spans")
            if sp:
                a, b = (int(x) for x in sp.split(":"))
                if row and (_celula_ref(row[0].get("r"))[0] < a or _celula_ref(row[-1].get("r"))[0] > b):
                    probs.append(f"{nome}: linha {r} com spans={sp} que não cobre as células")
        formulas[nome] = forms
        dim = raiz.find("m:dimension", NS)
        if dim is not None and (max_c or max_r):
            c1, r1, c2, r2 = _intervalo_ref(dim.get("ref"))
            if c2 < max_c or r2 < max_r:
                probs.append(f"{nome}: <dimension {dim.get('ref')}> não cobre até {col_letra(max_c)}{max_r}")
        # tabelas da aba
        for _i, tipo, alvo in pac.rels(parte):
            if not tipo.endswith("/table"):
                continue
            t = xmls[alvo]
            c1, r1, c2, r2 = _intervalo_ref(t.get("ref"))
            cols = t.find("m:tableColumns", NS)
            nomes = [tc.get("name") for tc in cols]
            if int(cols.get("count")) != len(nomes) or len(nomes) != c2 - c1 + 1:
                probs.append(f"tabela {t.get('name')}: ref {t.get('ref')} incoerente com {len(nomes)} colunas")
            if len({n.casefold() for n in nomes}) != len(nomes):
                probs.append(f"tabela {t.get('name')}: nomes de coluna repetidos")
            tids = [tc.get("id") for tc in cols]
            if len(set(tids)) != len(tids):
                probs.append(f"tabela {t.get('name')}: ids de coluna repetidos")
            af = t.find("m:autoFilter", NS)
            if af is not None and _intervalo_ref(af.get("ref")) != (c1, r1, c2, r2):
                probs.append(f"tabela {t.get('name')}: autoFilter {af.get('ref')} difere da ref {t.get('ref')}")
            cab = {}
            for row in sd:
                if int(row.get("r")) == r1:
                    for c in row:
                        cab[_celula_ref(c.get("r"))[0]] = c
            ss = []
            if "xl/sharedStrings.xml" in xmls:
                for si in xmls["xl/sharedStrings.xml"]:
                    ss.append("".join(x.text or "" for x in si.iter(f"{{{NS['m']}}}t")))
            for k, nm in enumerate(nomes):
                c = cab.get(c1 + k)
                if c is None:
                    probs.append(f"tabela {t.get('name')}: célula de cabeçalho {col_letra(c1 + k)}{r1} ausente")
                    continue
                if c.get("t") == "s":
                    txt = ss[int(c.find("m:v", NS).text)]
                elif c.get("t") == "inlineStr":
                    txt = "".join(x.text or "" for x in c.iter(f"{{{NS['m']}}}t"))
                else:
                    v = c.find("m:v", NS)
                    txt = v.text if v is not None else ""
                if txt != nm:
                    probs.append(f"tabela {t.get('name')}: cabeçalho {c.get('r')}={txt!r} difere do nome {nm!r}")
    tids = {}
    for n in pac.nomes():
        if re.fullmatch(r"xl/tables/table\d*\.xml", n):
            t = xmls[n]
            for k in ("id", "name"):
                tids.setdefault(k, []).append(t.get(k))
    for k, v in tids.items():
        if len(set(v)) != len(v):
            probs.append(f"tabelas: {k} repetido {v}")
    # calcChain só pode apontar para células com fórmula
    for n in pac.nomes():
        if n.endswith("calcChain.xml"):
            idx = {s.get("sheetId"): s.get("name") for s in wb.find("m:sheets", NS)}
            atual = None
            for c in xmls[n]:
                atual = c.get("i") if c.get("i") else atual
                if c.get("r") not in formulas.get(idx.get(atual), set()):
                    probs.append(f"calcChain: {c.get('r')} (aba {idx.get(atual)}) não tem fórmula")
                    break
    # tabelas dinâmicas: campos do cache x campos da tabela
    for n in pac.nomes():
        if re.fullmatch(r"xl/pivotTables/pivotTable\d*\.xml", n):
            for _i, _t, alvo in pac.rels(n):
                if alvo in xmls:
                    cf = xmls[alvo].find("m:cacheFields", NS)
                    pf = xmls[n].find("m:pivotFields", NS)
                    if cf is not None and pf is not None and len(cf) != len(pf):
                        probs.append(f"{n}: {len(pf)} pivotFields x {len(cf)} cacheFields em {alvo}")
    return probs
