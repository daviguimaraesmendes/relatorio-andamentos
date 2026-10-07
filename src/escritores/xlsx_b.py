"""Escritor do relatório em planilha (modelo B): grava `.xlsx` do cliente ou cria um novo do modelo
padrão, sem passar por bibliotecas que apagam gráficos e tabelas dinâmicas ao salvar.

Duas camadas no mesmo módulo (um só conjunto de testes, um só caminho de código):

1. MOTOR CIRÚRGICO (Pacote, Folha, Edicao e as funções inserir_linhas, escrever_celulas,
   acrescentar_coluna, ler_coluna, validar). Só biblioteca padrão: o pacote .xlsx (zip) é lido inteiro,
   só as partes que precisam mudar são reescritas (por edição do TEXTO do XML, sem reserializar) e todas
   as outras voltam com o mesmo conteúdo, byte a byte. Evoluiu do protótipo do spike S1
   (docs/fase2/spikes/S1-xlsx.md).
2. ESCRITOR DO CONTRATO (gravar), que traduz fichas v2 + eventos aprovados em edições:

       gravar(molde, estado, destino, **opcoes) -> Resultado        (CONTRATOS.md, seção 5)

   `molde`: Path do .xlsx do cliente (atualização) ou None (cria do modelo padrão em
   src/modelos/xlsx_b/, gerado por gerar_modelo.py). `estado`: {"cliente", "data_base" (ISO), "fichas",
   "eventos" (aprovados), "perfil", "parametros"}; chaves opcionais: "historico" (retratos mensais
   anteriores, CONTRATOS 9) e "campos_nao_migrados" (como `RelatorioLido["colunas_sem_destino"]`, com
   "valores": {numero: valor} opcional). O Resultado é um dict com as chaves do contrato (destino,
   processos_atualizados, processos_novos, ignorados, mudancas, avisos, textos_gravados) mais
   valores_gravados, partes_alteradas, partes_removidas e cache_formulas.

Regras de gravação no arquivo do cliente (por coluna, sempre achada pelo CABEÇALHO, nunca pela posição):

  - Andamentos: só acrescenta (comportamento da Fase 1). O fecho "Até DD/MM/AAAA sem atualizações." só
    entra quando o processo não teve andamento no ciclo (`fecho_apos_novidade=False`); a frase de
    andamento que já consta no texto não é repetida (vai para `ignorados`). Texto acima de 32.767
    caracteres não é truncado: aquele processo fica sem a atualização, com aviso de erro.
  - Colunas "mecânicas" (situação, ativo, houve recurso, momento atual, último andamento, fase): o
    sistema as recalcula a cada ciclo e troca o valor. Se a pessoa as editou à mão desde a última
    gravação (a ficha guarda `ultimos_valores_gravados`; ver docs/fase2/RFC-xlsx-valores-gravados.md),
    sai o aviso `edicao_manual_sobrescrita`.
  - Colunas objetivas (partes, vara, datas, valor da causa...): preenche só célula vazia; valor diferente
    do coletado não é sobrescrito (aviso agregado `valor_divergente`).
  - Colunas de julgamento (probabilidade, valores estimado/arbitrado..., resultado): só célula vazia.
    Célula já preenchida nunca é sobrescrita; se a ficha tem outro valor, aviso `campo_divergente`.
  - Células com fórmula nunca são sobrescritas; linhas novas herdam estilo e fórmulas da última linha.
  - Processo que não está na planilha entra ao fim da tabela (na aba de encerrados, se houver uma e o
    processo estiver encerrado). Nada é apagado nem reordenado.

Cache de fórmulas: o LibreOffice ignora `fullCalcOnLoad` e confia no valor em cache, então o padrão é
`invalidar_cache=True` (fórmulas sem valor guardado; o Excel recalcula ao abrir). Leitores que não
calculam (pandas, prévia do celular) veem vazio até alguém abrir e salvar. Mitigação opcional
(`recalcular_com_soffice=True`): se o LibreOffice (`soffice`) existir, recalcula numa CÓPIA temporária e
grava os valores como cache; sem ele, cai no padrão e avisa. A ferramenta não exige LibreOffice.

Limites do formato viram RECUSA com mensagem em português, nunca arquivo corrompido: linha de totais na
tabela, conteúdo logo abaixo da tabela, célula mesclada na faixa nova, tabela dinâmica com cache salvo ao
acrescentar coluna, macros (.xlsm), segmentação de dados, consultas externas, aba protegida, várias
tabelas na aba, arquivo com senha ou que não é .xlsx. `gravar` devolve esses casos como avisos de erro
(destino None), e todo arquivo gerado passa por `validar()` antes de ser entregue; o original e o destino
anterior só são tocados se a gravação inteira der certo.

Validado aqui só com LibreOffice e leitura do XML; Excel e Google Sheets não puderam ser testados
(roteiro em docs/fase2/conferencia-xlsx.md).

Uso do motor:
    from escritores import xlsx_b
    xlsx_b.inserir_linhas("entrada.xlsx", "saida.xlsx", "Processos", [{"Número do Processo": "..."}])
Uso do contrato:
    res = xlsx_b.gravar(Path("cliente.xlsx"), estado, Path("saida/relatorio.xlsx"))
"""
import datetime
import html
import os
import posixpath
import re
import shutil
import subprocess
import tempfile
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


class _Limpar:
    def __repr__(self):
        return 'LIMPAR'


LIMPAR = _Limpar()   # valor especial de escrever_celulas: esvazia a célula


# ------------------------------------------------------------------ erros e tipos

class ErroXlsx(Exception):
    """Erro esperado de gravação: arquivo fora do que o motor sabe editar com segurança.
    `codigo` é estável (vira o `codigo` do aviso em gravar); `candidatos` lista o que ajuda a corrigir."""
    codigo = "xlsx_erro"

    def __init__(self, mensagem, codigo=None, candidatos=None):
        super().__init__(mensagem)
        if codigo:
            self.codigo = codigo
        self.candidatos = list(candidatos or [])


class NaoSuportado(ErroXlsx):
    codigo = "xlsx_nao_suportado"


class ColunaDesconhecida(ErroXlsx):
    codigo = "coluna_desconhecida"


class ConflitoDeConteudo(ErroXlsx):
    codigo = "conflito_de_conteudo"


class Formula(str):
    """Marca um texto como fórmula (sem o '='): Formula('SUM(A1:A3)')."""


@dataclass
class ResultadoEdicao:
    """O que uma edição do motor fez (o `Resultado` do contrato é o dict que `gravar` devolve)."""
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
            with open(self.caminho, "rb") as f:
                cabeca = f.read(8)
            with zipfile.ZipFile(self.caminho) as z:
                self._infos = z.infolist()
                self._dados = {i.filename: z.read(i.filename) for i in self._infos}
        except FileNotFoundError as e:
            raise ErroXlsx(f"O arquivo {self.caminho.name} não foi encontrado.", "arquivo_nao_encontrado") from e
        except zipfile.BadZipFile as e:
            if cabeca.startswith(b"\xd0\xcf\x11\xe0"):
                raise ErroXlsx(f"{self.caminho.name} está protegido por senha ou está no formato antigo (.xls). "
                               "Salve uma cópia sem senha, em .xlsx, e tente de novo.", "arquivo_com_senha") from e
            raise ErroXlsx(f"{self.caminho.name} não é uma planilha .xlsx válida ({e}).", "arquivo_nao_xlsx") from e
        self._originais = dict(self._dados)
        self._checar_formato()

    def _checar_formato(self):
        """Recusa o que não é uma pasta de trabalho .xlsx comum (macros, modelo .xltx etc.)."""
        if "xl/workbook.xml" not in self._dados or "[Content_Types].xml" not in self._dados:
            raise ErroXlsx(f"{self.caminho.name} não parece uma planilha .xlsx (faltam partes essenciais).",
                           "arquivo_nao_xlsx")
        ct = self._dados["[Content_Types].xml"].decode("utf-8", "replace")
        m = re.search(r'<Override\b[^>]*PartName="/xl/workbook.xml"[^>]*ContentType="([^"]+)"', ct) or \
            re.search(r'<Override\b[^>]*ContentType="([^"]+)"[^>]*PartName="/xl/workbook.xml"', ct)
        tipo = m.group(1) if m else ""
        if "macroEnabled" in tipo or "xl/vbaProject.bin" in self._dados:
            raise NaoSuportado("A planilha tem macros (.xlsm). Salve uma cópia sem macros, em .xlsx, ou use outro "
                               "arquivo: o programa não edita planilhas com macros.", "xlsm")
        if tipo and not tipo.endswith("sheet.main+xml"):
            raise NaoSuportado("O arquivo é um modelo do Excel (.xltx) ou outro tipo de pasta de trabalho. "
                               "Salve como planilha comum (.xlsx).", "formato_diferente")

    def nomes(self):
        return list(self._dados)

    def existe(self, nome):
        return nome in self._dados

    def texto(self, nome):
        try:
            return self._dados[nome].decode("utf-8")
        except UnicodeDecodeError as e:
            raise NaoSuportado(f"A parte {nome} da planilha usa codificação diferente de UTF-8.", "codificacao") from e

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
        raise ErroXlsx(f"A aba {nome!r} não existe na planilha (abas: {', '.join(map(str, nomes))}).",
                       "aba_inexistente", nomes)

    def abas(self):
        """[(nome, parte)] das abas, na ordem do arquivo."""
        wb = ET.fromstring(self._dados["xl/workbook.xml"])
        ids = {i: alvo for i, _t, alvo in self.rels("xl/workbook.xml")}
        return [(s.get("name"), ids.get(s.get(f"{{{NS['r']}}}id"))) for s in wb.find("m:sheets", NS)]

    def tabelas_da_aba(self, parte):
        """[(parte_da_tabela, nome, ref, tag_raiz)] das Tabelas do Excel da aba."""
        saida = []
        for _i, tipo, alvo in self.rels(parte):
            if tipo.endswith("/table"):
                tx = self.texto(alvo)
                raiz = re.search(r"<table\b[^>]*>", tx).group(0)
                saida.append((alvo, html.unescape(re.search(r'\sdisplayName="([^"]*)"', raiz).group(1)),
                              re.search(r'\sref="([^"]+)"', raiz).group(1), raiz))
        return saida

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
            raise NaoSuportado("A aba tem uma estrutura interna fora do padrão (sem <sheetData>); o programa não a edita.", "aba_fora_do_padrao")
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
                raise NaoSuportado("Há linha sem número na aba (estrutura fora do padrão); o programa não a edita.", "aba_fora_do_padrao")
            n = int(r.group(1))
            if n <= ultimo:
                raise NaoSuportado(f"As linhas da aba estão fora de ordem ou repetidas (linha {n}); o programa não a edita.", "aba_fora_do_padrao")
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
            raise ErroXlsx("Número inválido (NaN ou infinito) não cabe em célula.", "valor_invalido")
        return None, f"<v>{format(v, 'f') if isinstance(v, Decimal) else repr(v)}</v>"
    if isinstance(v, str):
        if len(v) > LIMITE_CELULA:
            raise ErroXlsx(f"Texto com {len(v)} caracteres: o Excel aceita no máximo {LIMITE_CELULA} por célula.", "texto_acima_do_limite")
        t = _ILEGAIS.sub("", v).replace("\r\n", "\n").replace("\r", "\n")
        return "inlineStr", f'<is><t xml:space="preserve">{html.escape(t, quote=False)}</t></is>'
    raise ErroXlsx(f"Tipo de valor sem suporte para célula: {type(v).__name__}.", "valor_invalido")


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

    def formula(self, texto, na_aba, grafico=False):
        """Texto de fórmula -> texto de fórmula. na_aba: as refs sem aba são da aba da tabela.
        grafico: série de gráfico; numa tabela de UMA linha só (o modelo recém-criado) a referência a uma
        célula única da linha também vale como intervalo e acompanha o crescimento."""
        def sub(m):
            if not m.group("ref"):
                return m.group(0)
            if not m.group("b") and not (grafico and self.lin1 == self.lin2):
                return m.group(0)
            aba = m.group("aba")
            if aba:
                if _nome_aba(aba).casefold() != self.aba.casefold():
                    return m.group(0)
            elif not na_aba:
                return m.group(0)
            a = m.group("a")
            b = m.group("b") or a
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


def _sub_f(xml, extensor, na_aba, tags=r"(?:\w+:)?f|formula[12]?|definedName|(?:\w+:)?formula[12]?", grafico=False):
    """Aplica extensor.formula ao conteúdo de <f>, <c:f>, <xm:f>, <formula*>, <definedName>."""
    def sub(m):
        bruto = m.group(2)
        if not bruto or "!" not in bruto and not na_aba:
            return m.group(0)
        txt = html.unescape(bruto)
        novo = extensor.formula(txt, na_aba, grafico)
        if novo == txt:
            return m.group(0)
        return m.group(1) + html.escape(novo, quote=False) + m.group(3)
    return re.sub(rf"(<(?:{tags})\b[^>]*(?<!/)>)(.*?)(</(?:{tags})>)", sub, xml, flags=re.S)


# ------------------------------------------------------------------ edição

_EST_DATA_BUILTIN = set(range(14, 23)) | set(range(27, 37)) | set(range(45, 48)) | set(range(50, 59))


class Edicao:
    """Uma ou mais operações sobre UMA aba de um .xlsx.

    `salvar(destino)` grava tudo de uma vez. Para editar várias abas do mesmo arquivo, crie uma Edicao por
    aba, UMA DE CADA VEZ, passando o mesmo `pacote` (objeto Pacote) e chamando `aplicar()` em cada uma; no
    fim, `pacote.gravar(destino)`. `recalcular=False` não mexe no recálculo nem no cache de fórmulas (uso da
    Fase 1: só texto em uma coluna que nenhuma fórmula lê). `linha_cabecalho=None` (ou aba sem cabeçalho com
    `exigir_cabecalho=False`) edita células soltas, sem região de tabela."""

    def __init__(self, origem, aba, tabela=None, linha_cabecalho=1, humanos=None, preservar_humanos=True,
                 invalidar_cache=True, *, pacote=None, recalcular=True, exigir_cabecalho=True):
        self.invalidar_cache = invalidar_cache
        self.recalcular = recalcular
        self.pac = pacote if pacote is not None else Pacote(origem)
        self.origem = Path(origem) if origem is not None else self.pac.caminho
        self.parte = self.pac.parte_da_aba(aba)
        self.aba = self.pac.nome_da_aba(self.parte) or aba
        self._checar_suportado()
        self.folha = Folha(self.pac.texto(self.parte))
        self.preservar_humanos = preservar_humanos
        self.avisos, self.ignoradas = [], []
        self._ss = None
        self._cab_norm = None
        self._xfs_data = None
        self._base1904 = 'date1904="1"' in self.pac.texto("xl/workbook.xml")
        self.sem_regiao = False
        self._calc_ignoradas = {}
        self._aplicada = False
        self._carregar_regiao(tabela, linha_cabecalho, exigir_cabecalho)
        self.colunas_humanas = self._resolver_humanos(humanos)
        self.lin2_orig, self.col2_orig = self.lin2, self.col2
        self.escritas = 0
        self.inseridas = 0
        self._primeira = None
        self._avisou_data = set()
        self._avisar_filtro()

    # ---- o que o motor se recusa a editar ----------------------------------------
    def _checar_suportado(self):
        nomes = self.pac.nomes()
        if any(n.startswith(("xl/slicers/", "xl/slicerCaches/", "xl/timelines/", "xl/timelineCaches/")) for n in nomes):
            raise NaoSuportado("A planilha tem segmentação de dados (botões de filtro) ou linha do tempo. O programa "
                               "ainda não sabe editar planilhas com esses recursos sem arriscar quebrá-los.",
                               "segmentacao_de_dados")
        if any(n.startswith("xl/queryTables/") for n in nomes):
            raise NaoSuportado("A planilha tem tabela ligada a uma consulta externa (Power Query ou banco de dados). "
                               "O programa não edita esse tipo de tabela.", "consulta_externa")
        if re.search(r'<sheetProtection\b[^>]*\ssheet="(?:1|true)"', self.pac.texto(self.parte)):
            raise NaoSuportado(f"A aba {self.aba!r} está protegida. Remova a proteção (Revisão > Desproteger Planilha) "
                               "e tente de novo; o programa não contorna proteção.", "aba_protegida")

    def _avisar_filtro(self):
        """Filtro ativo com linhas ocultas: as linhas novas não entram ocultas e o filtro não é reaplicado."""
        tabela_filtrada = False
        if self.tabela_parte:
            tabela_filtrada = "<filterColumn" in self.pac.texto(self.tabela_parte)
        if (tabela_filtrada or "<filterColumn" in self.folha.pre + self.folha.pos) and \
                re.search(r'<row\b[^>]*\shidden="(?:1|true)"', self.pac.texto(self.parte)):
            self.avisos.append("a aba tem filtro ativo com linhas ocultas: as linhas novas entram visíveis e o filtro "
                               "não é reaplicado (reaplique-o no Excel)")

    # ---- região -------------------------------------------------------------
    def _carregar_regiao(self, nome_tabela, linha_cabecalho, exigir_cabecalho=True):
        tabelas = self.pac.tabelas_da_aba(self.parte)
        for parte_t, _n, _r, raiz_t in tabelas:
            if re.search(r'\stableType="queryTable"', raiz_t):
                raise NaoSuportado("A planilha tem tabela ligada a uma consulta externa (Power Query ou banco de "
                                   "dados). O programa não edita esse tipo de tabela.", "consulta_externa")
        if nome_tabela:
            tabelas = [t for t in tabelas if t[1].casefold() == nome_tabela.casefold()]
            if not tabelas:
                raise ErroXlsx(f"A tabela {nome_tabela!r} não existe na aba {self.aba!r}.", "tabela_inexistente")
        if len(tabelas) > 1:
            raise ErroXlsx(f"A aba {self.aba!r} tem mais de uma tabela do Excel ({', '.join(t[1] for t in tabelas)}); o programa não sabe em qual gravar.", "varias_tabelas", [t[1] for t in tabelas])
        self.tabela_parte = self.tabela_nome = None
        if tabelas:
            parte, nome, ref, raiz = tabelas[0]
            if re.search(r'\stotalsRowCount="[1-9]', raiz):
                raise NaoSuportado(f"A tabela da aba {self.aba!r} tem linha de totais. Linhas novas teriam de entrar antes dos "
                                   "totais e o programa ainda não consegue deslocá-los. Desligue a linha de totais "
                                   "(Design da Tabela > Linha de Totais) e tente de novo.", "tabela_com_totais")
            if re.search(r'\sheaderRowCount="0"', raiz):
                raise NaoSuportado(f"A tabela da aba {self.aba!r} não tem linha de cabeçalho.", "tabela_sem_cabecalho")
            self.tabela_parte, self.tabela_nome = parte, nome
            self.col1, self.lin_cab, self.col2, self.lin2 = _intervalo_ref(ref)
            self.lin1 = self.lin_cab + 1
            self.col1, self.lin_cab, self.col2, self.lin2 = self.col1, self.lin_cab, self.col2, self.lin2
        else:   # sem tabela: região deduzida do cabeçalho
            self.tabela_parte = self.tabela_nome = None
            self.lin_cab = linha_cabecalho or 1
            cab = self.folha.linha(self.lin_cab) if linha_cabecalho else None
            cols = [c.col for c in (cab.celulas if cab else []) if not c.vazia]
            if not cols:
                if linha_cabecalho and exigir_cabecalho:
                    raise ErroXlsx(f"A aba {self.aba!r} não tem tabela do Excel nem cabeçalho na linha "
                                   f"{linha_cabecalho}.", "sem_cabecalho")
                self.sem_regiao = True
                self.lin_cab, self.lin1, self.lin2, self.col1, self.col2 = 0, 1, 0, 1, 1
                self.cabecalhos = {}
                return
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
            raise ErroXlsx(f"A linha de cabeçalho {self.lin_cab} não existe na aba {self.aba!r}.", "sem_cabecalho")
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
        if self._cab_norm is None or self._cab_norm[0] != len(self.cabecalhos):
            mapa = {}
            for c, t in self.cabecalhos.items():
                if t != "":
                    mapa.setdefault(_norm(t), []).append(c)
            self._cab_norm = (len(self.cabecalhos), mapa)
        achados = self._cab_norm[1].get(_norm(spec), [])
        if len(achados) > 1:
            raise ColunaDesconhecida(f"O cabeçalho {spec!r} aparece em mais de uma coluna ({', '.join(col_letra(c) for c in achados)}) "
                                     f"na aba {self.aba!r}.", "cabecalho_ambiguo", [col_letra(c) for c in achados])
        if achados:
            return achados[0]
        if re.fullmatch(r"[A-Za-z]{1,3}", str(spec)):
            return col_indice(str(spec).upper())
        raise ColunaDesconhecida(f"A coluna {spec!r} não existe na aba {self.aba!r}.", "coluna_desconhecida",
                                 [t for t in self.cabecalhos.values() if t])

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
        for m in re.finditer(r'<c r="([A-Z]+\d+)"[^>]*>(?:(?!</c>).)*?<f\b([^>]*?)(?<!/)>(.*?)</f>',
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
                raise NaoSuportado(f"Fórmula compartilhada (si={si}) sem a fórmula-mestre na aba; o programa não a edita.", "formula_fora_do_padrao")
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
        if self.sem_regiao:
            raise NaoSuportado(f"A aba {self.aba!r} não tem tabela nem cabeçalho: não há onde inserir linhas.",
                               "sem_cabecalho")
        mapa = colunas or {}
        indices = []   # por linha: {col: valor}
        for k, linha in enumerate(linhas):
            d = {}
            for chave, valor in linha.items():
                col = self.coluna(mapa.get(chave, chave))
                if not (self.col1 <= col <= self.col2):
                    raise ColunaDesconhecida(f"A coluna {chave!r} está fora da tabela da aba {self.aba!r}.", "coluna_desconhecida")
                d[col] = valor
            indices.append(d)
        n = len(linhas)
        ini = self.lin2 + 1
        self._checar_faixa(ini, ini + n - 1)
        modelo = self._linha_modelo()
        calc = self._colunas_calculadas()
        mestres = self._formulas_compartilhadas()
        # a altura da linha-modelo (ht/customHeight) não vale para as novas: o Excel ajusta sozinho
        attrs_modelo = {k: v for k, v in (modelo.attrs if modelo else {}).items()
                        if k not in ("hidden", "collapsed", "ht", "customHeight")}
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
                        self._calc_ignoradas[col] = self._calc_ignoradas.get(col, 0) + 1
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
                        f"A célula {c.ref} tem conteúdo logo abaixo da tabela (notas, totais soltos?). Inserir linhas ali "
                        "sobrescreveria esses dados e o programa não desloca o que está abaixo. Mova esse conteúdo para "
                        "longe da tabela e tente de novo.", "conteudo_abaixo_da_tabela")
        xml = self.folha.pos
        for m in re.finditer(r'<mergeCell\b[^>]*?\sref="([^"]+)"', xml):
            c1, r1, c2, r2 = _intervalo_ref(m.group(1))
            if r2 >= a and r1 <= b and c2 >= self.col1 and c1 <= self.col2:
                raise ConflitoDeConteudo(f"Há células mescladas ({m.group(1)}) onde entrariam as linhas novas. Desfaça a mesclagem e tente de novo.", "celula_mesclada_na_faixa")

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
            raise NaoSuportado("Para acrescentar coluna, a aba precisa ter uma tabela do Excel.", "sem_tabela")
        if self.inseridas:
            raise NaoSuportado("Erro de programação: a coluna nova deve ser acrescentada antes das linhas.", "ordem_de_operacoes")
        if "\n" in cabecalho or "\r" in cabecalho or not cabecalho.strip():
            raise ErroXlsx("Cabeçalho inválido para a coluna nova (vazio ou com quebra de linha).", "cabecalho_invalido")
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
                    raise ConflitoDeConteudo(f"A célula {c.ref} já tem conteúdo: a coluna nova não cabe ao lado da tabela.", "conteudo_ao_lado_da_tabela")
        modelo_cab = self.folha.linha(self.lin_cab)
        col_estilo = self.coluna(estilo_de) if estilo_de else self.col2
        if isinstance(valores, (list, tuple)):
            if len(valores) != self.lin2 - self.lin1 + 1:
                raise ErroXlsx(f"Erro de programação: {len(valores)} valores para {self.lin2 - self.lin1 + 1} linhas da tabela.", "valores_incompativeis")
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
            raise ErroXlsx(f"A coluna {nome!r} já existe na tabela.", "coluna_ja_existe")
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

    # ---- leitura de célula ----------------------------------------------------------
    def valor(self, linha, coluna):
        """Valor da célula como Python: str, date, Decimal, int, bool; None se vazia, só espaços, erro ou
        fórmula sem valor guardado."""
        col = self.coluna(coluna)
        lin = self.folha.linha(linha)
        cel = lin.celula(col) if lin else None
        if cel is None or cel.vazia:
            return None
        t = cel.attrs.get("t")
        if t in ("s", "inlineStr", "str"):
            txt = self._texto(cel)
            return txt if txt.strip() else None
        if t == "e":
            return None
        m = re.search(r"<v>(.*?)</v>", cel.inner, re.S)
        if not m or not m.group(1).strip():
            return None
        if t == "b":
            return m.group(1).strip() in ("1", "true")
        try:
            numero = Decimal(m.group(1).strip())
        except Exception:
            return html.unescape(m.group(1))
        if cel.estilo is not None and self._estilo_eh_data(cel.estilo):
            base = datetime.datetime(1904, 1, 1) if self._base1904 else datetime.datetime(1899, 12, 30)
            return (base + datetime.timedelta(days=float(numero))).date()
        return int(numero) if numero == numero.to_integral_value() else numero

    def dinamica_com_cache_salvo(self):
        """Há tabela dinâmica alimentada por esta aba/tabela com os dados guardados no arquivo (cache)?
        Nesse caso acrescentar coluna é recusado (ver _dinamica_nova_coluna)."""
        for nome in self.pac.nomes():
            if not re.fullmatch(r"xl/pivotCache/pivotCacheDefinition\d*\.xml", nome):
                continue
            txt = self.pac.texto(nome)
            fonte = re.search(r"<worksheetSource\b([^>]*?)/?>", txt)
            if not fonte:
                continue
            a = dict(_RE_ATTR.findall(fonte.group(1)))
            nossa = (a.get("name", "").casefold() == (self.tabela_nome or "\0").casefold()) or \
                    (a.get("sheet", "").casefold() == self.aba.casefold() and "ref" in a)
            if nossa and (re.search(r"<pivotCacheDefinition\b[^>]*\sr:id=", txt) or any(
                    t.endswith("/pivotCacheRecords") for _i, t, _a in self.pac.rels(nome))):
                return True
        return False

    def tem_formula(self, linha, coluna):
        lin = self.folha.linha(linha)
        cel = lin.celula(self.coluna(coluna)) if lin else None
        return bool(cel is not None and cel.tem_formula)

    # ---- colunas ocultas ----------------------------------------------------------------
    def colunas_ocultas(self):
        """Índices das colunas ocultas da aba."""
        m = re.search(r"<cols>(.*?)</cols>", self.folha.pre, re.S)
        saida = set()
        for c in re.finditer(r"<col\b([^>]*?)/?>", m.group(1) if m else ""):
            a = dict(_RE_ATTR.findall(c.group(1)))
            if a.get("hidden") in ("1", "true"):
                saida.update(range(int(a["min"]), int(a["max"]) + 1))
        return saida

    def definir_colunas_ocultas(self, ocultas, visiveis=()):
        """Oculta as colunas `ocultas` (índices) e reexibe as `visiveis`; não apaga nada (as fórmulas e os
        dados continuam lá). Edita só o <cols> da aba."""
        pre = self.folha.pre
        m = re.search(r"<cols>(.*?)</cols>", pre, re.S)
        por_col = {}
        for c in re.finditer(r"<col\b([^>]*?)/?>", m.group(1) if m else ""):
            a = dict(_RE_ATTR.findall(c.group(1)))
            for k in range(int(a["min"]), int(a["max"]) + 1):
                por_col[k] = {kk: v for kk, v in a.items() if kk not in ("min", "max")}
        for c in ocultas:
            d = por_col.setdefault(c, {"width": "9.140625", "customWidth": "1"})
            d["hidden"] = "1"
        for c in visiveis:
            if c in por_col:
                por_col[c].pop("hidden", None)
        corpo = "".join('<col min="%d" max="%d"%s/>' % (c, c, "".join(f' {k}="{v}"' for k, v in d.items()))
                        for c, d in sorted(por_col.items()))
        novo = f"<cols>{corpo}</cols>"
        self.folha.pre = pre.replace(m.group(0), novo, 1) if m else pre + novo

    # ---- salvar -------------------------------------------------------------------
    def salvar(self, destino):
        destino = Path(destino)
        if destino.resolve() == self.origem.resolve():
            raise ErroXlsx("O arquivo de destino é o mesmo do original; o original nunca é sobrescrito. Escolha outro nome.", "destino_igual_ao_molde")
        r = self.aplicar()
        self.pac.gravar(destino)
        r.destino = destino
        r.partes_alteradas, r.partes_removidas = self.pac.alteradas(), self.pac.removidas()
        return r

    def aplicar(self):
        """Fecha a edição dentro do Pacote (sem gravar arquivo) e devolve o ResultadoEdicao."""
        if self._aplicada:
            raise ErroXlsx("Erro de programação: a edição já foi aplicada.", "edicao_repetida")
        self._aplicada = True
        for col, n in sorted(self._calc_ignoradas.items()):
            self.avisos.append(f"coluna calculada {self.cabecalhos[col]!r} mantém a fórmula "
                               f"(valor informado ignorado em {n} linha(s))")
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
        if (self.escritas or mudou_estrutura) and self.recalcular:
            self._recalculo_ao_abrir()
            if self.invalidar_cache:
                self._invalidar_cache()
        r = ResultadoEdicao(linhas_inseridas=self.inseridas, celulas_escritas=self.escritas,
                            ignoradas=list(self.ignoradas), avisos=list(self.avisos))
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
                novo = _sub_f(txt, ext, False, tags=r"(?:\w+:)?f", grafico=True)
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
            raise NaoSuportado("A planilha tem tabela dinâmica com dados guardados (cache). Acrescentar uma coluna exigiria "
                               "descartar esses dados, o que o programa ainda não faz. Acrescente a coluna à mão no "
                               "Excel (ou apague a tabela dinâmica e refaça-a depois) e tente de novo.", "dinamica_com_cache")
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
                raise NaoSuportado("A planilha não tem abas reconhecíveis (workbook.xml sem <sheets>).", "arquivo_nao_xlsx")
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


# ------------------------------------------------------------------ API de função (motor)

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
    não é sobrescrito (vai em ResultadoEdicao.ignoradas). Valor None = não mexe; LIMPAR = esvazia."""
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


# ------------------------------------------------------------------ cache de fórmulas (LibreOffice opcional)

def localizar_soffice():
    """Caminho do LibreOffice (soffice) ou None. A ferramenta não exige que ele exista."""
    for nome in ("soffice", "libreoffice"):
        achado = shutil.which(nome)
        if achado:
            return achado
    for candidato in ("/usr/bin/soffice", "/usr/lib/libreoffice/program/soffice",
                      "/Applications/LibreOffice.app/Contents/MacOS/soffice",
                      r"C:\Program Files\LibreOffice\program\soffice.exe"):
        if Path(candidato).exists():
            return candidato
    return None


_RE_CELULA_COM_F = re.compile(r"<c\b([^>]*?)>((?:(?!</c>).)*?<f\b.*?)</c>", re.S)


def _valores_calculados(caminho):
    """{nome_da_aba: {ref: (t, texto_bruto_do_v)}} das células com fórmula de um .xlsx salvo pelo LibreOffice."""
    pac = Pacote(caminho)
    saida = {}
    for nome, parte in pac.abas():
        valores = {}
        for m in _RE_CELULA_COM_F.finditer(pac.texto(parte)):
            attrs = dict(_RE_ATTR.findall(m.group(1)))
            v = re.search(r"<v>(.*?)</v>", m.group(2), re.S)
            if v is not None and "r" in attrs:
                valores[attrs["r"]] = (attrs.get("t"), v.group(1))
        saida[nome] = valores
    return saida


def _injetar_valores(pac, valores):
    """Grava, como cache, os valores calculados nas células com fórmula e sem valor. Devolve quantas."""
    total = 0
    for nome, parte in pac.abas():
        txt = pac.texto(parte)
        if "<f" not in txt or nome not in valores:
            continue
        achados = valores[nome]

        def poe(m):
            nonlocal total
            attrs, inner = m.group(1), m.group(2) or ""
            if "<f" not in inner or re.search(r"<v\b", inner):
                return m.group(0)
            ref = (re.search(r'\sr="([^"]+)"', attrs) or [None, None])[1]
            if ref not in achados:
                return m.group(0)
            t, bruto = achados[ref]
            attrs = re.sub(r'\st="[^"]*"', "", attrs)
            if t in ("str", "b", "e"):
                attrs += f' t="{t}"'
            total += 1
            return f"<c{attrs}>{inner}<v>{bruto}</v></c>"
        novo = _RE_CELULA.sub(poe, txt)
        if novo != txt:
            pac.definir(parte, novo)
    return total


def recalcular_com_soffice(caminho, timeout=180):
    """Grava em `caminho` os valores que o LibreOffice calcula como cache das fórmulas.

    O LibreOffice abre uma CÓPIA temporária; o arquivo só muda se tudo der certo. Devolve (True, "") ou
    (False, motivo): quem chama cai no padrão (cache invalidado) e avisa."""
    soffice = localizar_soffice()
    if not soffice:
        return False, "o LibreOffice (soffice) não está instalado"
    caminho = Path(caminho)
    with tempfile.TemporaryDirectory(prefix="xlsx_b-lo-") as tmp:
        tmp = Path(tmp)
        entrada = tmp / "entrada.xlsx"
        shutil.copyfile(caminho, entrada)
        saida = tmp / "saida"
        saida.mkdir()
        cmd = [soffice, f"-env:UserInstallation={(tmp / 'perfil').as_uri()}", "--headless", "--convert-to", "xlsx",
               "--outdir", str(saida), str(entrada)]
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return False, f"o LibreOffice demorou mais de {timeout} s"
        except OSError as e:
            return False, f"não foi possível executar o LibreOffice ({e})"
        calculado = saida / "entrada.xlsx"
        if p.returncode != 0 or not calculado.exists():
            return False, f"o LibreOffice não converteu o arquivo ({(p.stderr or p.stdout).strip()[:200]})"
        try:
            valores = _valores_calculados(calculado)
            pac = Pacote(caminho)
            n = _injetar_valores(pac, valores)
        except (ErroXlsx, ET.ParseError, KeyError) as e:
            return False, f"não foi possível ler o resultado do LibreOffice ({e})"
        if n == 0 and any("<f" in pac.texto(parte) for _n, parte in pac.abas()):
            return False, "o LibreOffice não devolveu valores para as fórmulas"
        pac.gravar(caminho)
    return True, ""


# ------------------------------------------------------------------ colunas do modelo B

# (campo da ficha, cabeçalho do modelo, papel, extra, sinônimos de cabeçalho em planilhas de clientes)
# papel: numero | andamentos | objetivo | mecanico | julgamento
_COLUNAS = [
    ("numero", "Número do Processo", "numero", False, ("Número", "Nº do Processo", "Processo", "Nº Processo", "Número CNJ")),
    ("autores", "Autor(es)", "objetivo", False, ("Autor", "Autores", "Reclamante", "Reclamantes", "Requerente", "Parte autora")),
    ("reus", "Réu(s)", "objetivo", False, ("Réu", "Réus", "Reclamada", "Reclamadas", "Reclamado", "Requerido", "Parte ré")),
    ("vara", "Vara", "objetivo", False, ("Vara / Juízo", "Juízo", "Órgão julgador", "Vara/Comarca")),
    ("municipio", "Município", "objetivo", False, ("Cidade", "Comarca")),
    ("tribunal", "Tribunal", "objetivo", False, ("Tribunal / Justiça", "TRT/TJ")),
    ("data_ajuizamento", "Data do Ajuizamento", "objetivo", False, ("Ajuizamento", "Data de Ajuizamento", "Data de distribuição", "Distribuição")),
    ("area", "Área do Direito", "objetivo", False, ("Área", "Área do direito")),
    ("materia_principal", "Matéria Principal", "objetivo", False, ("Matéria", "Tese")),
    ("objeto", "Objeto", "objetivo", False, ("Pedido", "Pedidos", "Objeto da ação")),
    ("valor_causa", "Valor da Causa", "objetivo", False, ("Valor da causa (R$)", "Valor causa")),
    ("andamentos", "Andamentos", "andamentos", False, ("Andamento", "Histórico", "Andamentos processuais")),
    ("situacao", "Situação", "mecanico", False, ("Situação do processo", "Status")),
    ("ativo", "Ativo", "mecanico", False, ("Processo ativo",)),
    ("valor_arbitrado", "Valor Arbitrado em Juízo", "julgamento", False, ("Valor arbitrado", "Condenação arbitrada", "Valor da condenação")),
    ("probabilidade", "Probabilidade", "julgamento", False, ("Probabilidade do resultado", "Prognóstico")),
    ("valor_estimado", "Valor Estimado", "julgamento", False, ("Valor estimado (R$)", "Estimativa")),
    ("valor_execucao", "Valor da Execução", "julgamento", False, ("Valor execução", "Valor da execução (R$)")),
    ("custas", "Custas Processuais", "julgamento", False, ("Custas",)),
    ("depositos_recursais", "Depósitos Recursais", "julgamento", False, ("Depósito recursal",)),
    ("garantias", "Garantias Processuais", "julgamento", False, ("Garantias", "Garantia processual")),
    ("resultado", "Resultado", "julgamento", False, ("Resultado do processo", "Desfecho")),
    ("valor_economizado", "Valor Economizado", "julgamento", False, ("Economia", "Valor economizado (R$)")),
    ("data_transito", "Data do trânsito em julgado", "julgamento", False, ("Trânsito em julgado", "Data do trânsito")),
    ("taxa_resolucao_dias", "Taxa de resolução (em dias)", "julgamento", False, ("Taxa de resolução", "Tempo de resolução (dias)", "Dias para resolução")),
    ("houve_recurso", "Houve recurso da empresa?", "mecanico", False, ("Houve recurso?", "Recurso da empresa", "Houve recurso")),
    ("percentual_exito", "Percentual de êxito", "julgamento", False, ("% de êxito", "Êxito")),
    ("terceirizado", "Reclamante terceirizado?", "objetivo", False, ("Terceirizado?", "Reclamante terceirizado")),
    ("outras_partes", "Outra(s) Parte(s)", "objetivo", False, ("Outras partes", "Outra parte", "Litisconsortes")),
    # colunas extras do modelo padrão: existem, mas ficam ocultas até o perfil ativá-las
    ("momento_atual", "Momento Atual", "mecanico", True, ("Momento atual do processo", "Momento")),
    ("ultimo_andamento", "Último Andamento", "mecanico", True, ("Data do último andamento", "Último andamento (data)")),
    ("data_citacao", "Data de Citação", "objetivo", True, ("Data da citação", "Citação")),
    ("fase", "Fase", "mecanico", True, ("Fase processual",)),
    ("classe", "Classe", "objetivo", True, ("Classe processual",)),
    ("assunto", "Assunto", "objetivo", True, ("Assunto principal",)),
    ("valor_acordo", "Valor do Acordo", "julgamento", True, ("Acordo (R$)", "Valor acordo")),
    ("observacoes", "Observações", "objetivo", True, ("Observação", "Obs.", "Comentários")),
]
CAMPOS_B = {c[0]: c[1] for c in _COLUNAS}                       # campo da ficha -> cabeçalho do modelo B
PAPEIS = {c[0]: c[2] for c in _COLUNAS}
COLUNAS_PADRAO = tuple(c[0] for c in _COLUNAS if not c[3])      # as 29 colunas do modelo B, em ordem
COLUNAS_EXTRAS = tuple(c[0] for c in _COLUNAS if c[3])          # opcionais (ocultas por padrão)
# colunas que os indicadores do modelo padrão leem: ficam visíveis mesmo que o perfil não as liste
NUCLEO = frozenset({"numero", "andamentos", "situacao", "ativo", "valor_causa", "data_ajuizamento", "resultado",
                    "valor_arbitrado", "valor_execucao", "valor_estimado", "valor_economizado", "data_transito",
                    "taxa_resolucao_dias", "houve_recurso", "probabilidade"})
MODELO_PADRAO = Path(__file__).resolve().parent.parent / "modelos" / "xlsx_b" / "modelo_padrao.xlsx"
_CNJ = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")
_VINTE = re.compile(r"(?<!\d)(\d{7})(\d{2})(\d{4})(\d)(\d{2})(\d{4})(?!\d)")
_ABA_ENCERRADOS = re.compile(r"arquiv|encerr|baix|inativ|finaliz")


def _chave_cab(texto):
    """Chave de comparação de cabeçalhos: sem acento, caixa, pontuação e o que vem entre parênteses."""
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).casefold()
    sem_parenteses = re.sub(r"\([^)]*\)", "", t)
    chave = re.sub(r"[^a-z0-9]", "", sem_parenteses)
    return chave or re.sub(r"[^a-z0-9]", "", t)


_INDICE_CAB = {}
for _campo, _cab, _papel, _extra, _sin in _COLUNAS:
    for _forma in (_cab, *_sin):
        _INDICE_CAB.setdefault(_chave_cab(_forma), _campo)


def mapear_cabecalhos(cabecalhos, mapeamento=None):
    """{campo: índice_de_coluna} a partir de {índice: texto do cabeçalho}, mais {campo: [colunas]} dos campos
    que casam com mais de uma coluna (ambíguos: ficam de fora do mapa). `mapeamento` {campo: cabeçalho}
    força o cabeçalho de um campo."""
    forcado = {_chave_cab(v): k for k, v in (mapeamento or {}).items()}
    achados = {}
    for col, texto in cabecalhos.items():
        if not str(texto or "").strip():
            continue
        chave = _chave_cab(texto)
        campo = forcado.get(chave) or _INDICE_CAB.get(chave)
        if campo:
            achados.setdefault(campo, []).append(col)
    mapa = {c: cols[0] for c, cols in achados.items() if len(cols) == 1}
    ambiguos = {c: cols for c, cols in achados.items() if len(cols) > 1}
    return mapa, ambiguos


def _aviso(nivel, codigo, onde, mensagem, candidatos=None):
    return {"nivel": nivel, "codigo": codigo, "onde": onde, "mensagem": mensagem, "candidatos": list(candidatos or [])}


def _ficha():
    import ficha
    return ficha


def _numeros_da_celula(valor):
    """Números CNJ (formatados ou só dígitos) escritos numa célula de número de processo."""
    if valor is None:
        return []
    texto = str(valor)
    achados = _CNJ.findall(texto)
    for m in _VINTE.finditer(texto):
        achados.append(f"{m.group(1)}-{m.group(2)}.{m.group(3)}.{m.group(4)}.{m.group(5)}.{m.group(6)}")
    return list(dict.fromkeys(achados))


def _valor_da_ficha(f, campo):
    """Valor Python (str, date, Decimal, float) que a ficha tem para o campo, ou None."""
    fi = _ficha()
    if campo == "numero":
        return "; ".join(fi.todos_os_numeros(f))
    if campo == "ativo":
        a = f.get("ativo")
        return None if a is None else ("Sim" if a else "Não")
    if campo == "tribunal":
        bruto = f.get("tribunal") or fi.obter(f, "tribunal")
        return bruto or None
    if campo not in fi.CAMPOS:
        return None
    bruto = fi.obter(f, campo)
    if bruto in (None, ""):
        return None
    tipo = fi.CAMPOS[campo][2]
    if tipo == "data":
        return fi.data(bruto)
    if tipo == "dinheiro":
        return fi.dinheiro(bruto)
    if tipo == "numero":
        try:
            return float(bruto)
        except (TypeError, ValueError):
            return None
    return str(bruto)


def _iguais(a, b):
    """Valores da célula e da ficha são o mesmo (data, número com tolerância de centavo, texto sem acento/caixa)?"""
    if isinstance(a, datetime.datetime):
        a = a.date()
    if isinstance(b, datetime.datetime):
        b = b.date()
    if isinstance(a, datetime.date) or isinstance(b, datetime.date):
        return a == b
    if isinstance(a, bool) or isinstance(b, bool):
        return _norm(a) == _norm(b)
    if isinstance(a, (int, float, Decimal)) and isinstance(b, (int, float, Decimal)):
        return abs(Decimal(str(a)) - Decimal(str(b))) < Decimal("0.005")
    try:
        return abs(Decimal(str(a)) - Decimal(str(b))) < Decimal("0.005")
    except Exception:
        return _norm(a) == _norm(b)


def _como_texto(v):
    if v is None:
        return None
    if isinstance(v, datetime.datetime):
        v = v.date()
    if isinstance(v, datetime.date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return f"{v:.2f}"
    return str(v)


_CODIGOS_AVISO_EDICAO = (
    ("sem formato de data", "data_sem_formato", "atencao"),
    ("filtro ativo", "filtro_ativo", "atencao"),
    ("aba sem Tabela do Excel", "aba_sem_tabela", "info"),
    ("mantém a fórmula", "coluna_calculada_mantida", "info"),
    ("já existe", "coluna_ja_existe", "info"),
)


def _avisos_da_edicao(ed, textos, onde):
    saida = []
    for txt in textos:
        for trecho, codigo, nivel in _CODIGOS_AVISO_EDICAO:
            if trecho in txt:
                saida.append(_aviso(nivel, codigo, onde, txt[0].upper() + txt[1:] + "."))
                break
        else:
            saida.append(_aviso("info", "aviso_xlsx", onde, txt))
    return saida


def _compartilhadas_do_pacote(pac):
    ss = []
    if pac.existe("xl/sharedStrings.xml"):
        txt = pac.texto("xl/sharedStrings.xml")
        for m in re.finditer(r"<si\b[^>]*?(?:/>|>(.*?)</si>)", txt, re.S):
            corpo = re.sub(r"<rPh\b.*?</rPh>", "", m.group(1) or "", flags=re.S)
            ss.append(html.unescape("".join(re.findall(r"<t(?:\s[^>]*)?>(.*?)</t>", corpo, re.S))))
    return ss


def _cabecalhos_das_tabelas(pac, parte):
    """[(nome_da_tabela | None, {coluna: texto do cabeçalho})] de uma aba, sem recusar nada (só para descobrir
    quais abas são de processos). Aba fora do padrão devolve lista vazia."""
    try:
        folha = Folha(pac.texto(parte))
    except ErroXlsx:
        return []
    ss = _compartilhadas_do_pacote(pac)

    def texto(cel):
        t = cel.attrs.get("t")
        if t == "s":
            m = re.search(r"<v>(\d+)</v>", cel.inner)
            return ss[int(m.group(1))] if m and int(m.group(1)) < len(ss) else ""
        if t == "inlineStr":
            return html.unescape("".join(re.findall(r"<t(?:\s[^>]*)?>(.*?)</t>", cel.inner, re.S)))
        m = re.search(r"<v>(.*?)</v>", cel.inner, re.S)
        return html.unescape(m.group(1)) if m else ""

    def linha_de_cabecalho(n, c1=1, c2=10_000):
        try:
            lin = folha.linha(n)
        except ErroXlsx:
            return {}
        return {c.col: texto(c) for c in (lin.celulas if lin else []) if c1 <= c.col <= c2 and not c.vazia}

    tabelas = pac.tabelas_da_aba(parte)
    if tabelas:
        saida = []
        for _p, nome, ref, _raiz in tabelas:
            c1, r1, c2, _r2 = _intervalo_ref(ref)
            saida.append((nome, linha_de_cabecalho(r1, c1, c2)))
        return saida
    return [(None, linha_de_cabecalho(1))]


def _aba_pelo_nome(pac, chave):
    """(nome, parte) da primeira aba cujo nome normalizado é `chave` (ex.: 'historico'), ou None."""
    for nome, parte in pac.abas():
        if _chave_cab(nome) == chave:
            return nome, parte
    return None


# ------------------------------------------------------------------ gravar (contrato)

class _Plano:
    """Para cada ficha: onde ela está na planilha (ou None) e os eventos aprovados dela."""

    def __init__(self, ficha, eventos):
        self.ficha, self.eventos = ficha, eventos
        self.aba = None          # índice em abas de processos
        self.linha = None
        self.motivo_ignorado = None


def _tabela_vazia(ed):
    """Tabela de uma linha só, ainda em branco (o modelo padrão recém-criado)."""
    if ed.lin1 != ed.lin2:
        return False
    return all(ed.valor(ed.lin1, c) is None for c in range(ed.col1, ed.col2 + 1)
               if not ed.tem_formula(ed.lin1, c))


def _preencher_tabela(ed, linhas):
    """Grava `linhas` ({coluna: valor}) ao fim da tabela; a linha em branco do modelo é aproveitada."""
    if not linhas:
        return
    if _tabela_vazia(ed):
        primeira, resto = linhas[0], linhas[1:]
        ed.escrever_celulas({(ed.lin1, c): v for c, v in primeira.items() if not ed.tem_formula(ed.lin1, c)})
        ed.inserir_linhas(resto)
    else:
        ed.inserir_linhas(linhas)


def _totais_do_retrato(fichas, data_base):
    """Linha do histórico mensal (CONTRATOS 9) a partir das fichas."""
    fi = _ficha()

    def soma(campo):
        return sum((fi.dinheiro(fi.obter(f, campo)) or Decimal(0) for f in fichas), Decimal(0))
    ativos = sum(1 for f in fichas if f.get("ativo", True))
    return {"data_base": data_base, "totais": {
        "processos": len(fichas), "ativos": ativos, "encerrados": len(fichas) - ativos,
        "valor_causa": f"{soma('valor_causa'):.2f}", "valor_estimado": f"{soma('valor_estimado'):.2f}",
        "valor_economizado": f"{soma('valor_economizado'):.2f}"}}


def gravar(molde, estado, destino, *, aba=None, mapeamento=None, invalidar_cache=True,
           recalcular_com_soffice=False, fecho_apos_novidade=False, acrescentar_colunas=False,
           atualizar_data_referencia=True, limiar_duplicata=0.6, timeout_soffice=180, **opcoes):
    """Escritor do contrato (CONTRATOS 5): grava o relatório em planilha e devolve o `Resultado` (dict).

    molde: Path do .xlsx do cliente, ou None para criar do modelo padrão. estado: ver o cabeçalho do módulo.
    Opções: `aba` (nome ou lista de nomes das abas de processos; padrão: achar pelo cabeçalho), `mapeamento`
    ({campo: cabeçalho} para forçar colunas), `invalidar_cache` (padrão True), `recalcular_com_soffice`
    (mitigação opcional do cache), `fecho_apos_novidade` (padrão False), `acrescentar_colunas` (acrescenta
    à tabela do cliente as colunas do perfil que faltam; padrão False), `atualizar_data_referencia`,
    `limiar_duplicata` (0 a 1: parecença mínima para considerar que um andamento já consta no texto).

    Erros esperados (arquivo fora do que o motor edita com segurança, texto longo demais etc.) voltam como
    avisos de nível "erro" com `codigo` estável; nesse caso `destino` é None e nada foi gravado.
    """
    destino = Path(destino)
    res = {"destino": None, "processos_atualizados": [], "processos_novos": [], "ignorados": [], "mudancas": [],
           "avisos": [], "textos_gravados": {}, "valores_gravados": {}, "partes_alteradas": [],
           "partes_removidas": [], "cache_formulas": None}
    acc = {"processos_atualizados": [], "processos_novos": [], "ignorados": [], "mudancas": [], "avisos": [],
           "textos_gravados": {}, "valores_gravados": {}}
    tmp = destino.with_name(f".{destino.name}.{os.getpid()}.tmp")
    try:
        if molde is not None and Path(molde).resolve() == destino.resolve():
            raise ErroXlsx("O arquivo de destino é o mesmo do molde; o original nunca é sobrescrito. Escolha outro nome.",
                           "destino_igual_ao_molde")
        origem = Path(molde) if molde is not None else MODELO_PADRAO
        if molde is None and not origem.exists():
            raise ErroXlsx("O modelo padrão de planilha não foi encontrado (src/modelos/xlsx_b/modelo_padrao.xlsx). "
                           "Gere-o com gerar_modelo.py.", "modelo_padrao_ausente")
        pac = Pacote(origem)
        problemas_origem = set(validar(origem))
        if problemas_origem and molde is not None:
            acc["avisos"].append(_aviso(
                "atencao", "molde_com_problemas", origem.name,
                "A planilha de referência já tem inconsistências na estrutura interna (podem ser inofensivas); "
                "o programa só recusa se a gravação criar problemas novos.", sorted(problemas_origem)[:10]))
        _Gravacao(pac, estado, molde is None, acc, aba=aba, mapeamento=mapeamento, fecho_apos_novidade=fecho_apos_novidade,
                  acrescentar_colunas=acrescentar_colunas, atualizar_data_referencia=atualizar_data_referencia,
                  limiar=limiar_duplicata, invalidar_cache=invalidar_cache).executar()
        destino.parent.mkdir(parents=True, exist_ok=True)
        pac.gravar(tmp)
        partes_alteradas, partes_removidas = pac.alteradas(), pac.removidas()
        cache = "mantido"
        if invalidar_cache:
            cache = "invalidado"
            if recalcular_com_soffice:
                ok, motivo = _recalcular(tmp, timeout_soffice)
                if ok:
                    cache = "recalculado"
                else:
                    acc["avisos"].append(_aviso(
                        "atencao", "soffice_indisponivel", destino.name,
                        f"Não foi possível recalcular as fórmulas com o LibreOffice ({motivo}). As fórmulas ficam sem "
                        "valor guardado e o Excel as calcula ao abrir."))
            if cache == "invalidado":
                acc["avisos"].append(_aviso(
                    "info", "cache_de_formulas_invalidado", destino.name,
                    "Os resultados das fórmulas (indicadores) só aparecem depois de abrir a planilha no Excel ou no "
                    "Google Planilhas; programas que apenas leem o arquivo (prévia do celular, e-mail) mostram células "
                    "vazias até lá."))
        novos = [p for p in validar(tmp) if p not in problemas_origem]
        if novos:
            raise ErroXlsx("A planilha gerada não passou na verificação interna e não foi entregue. "
                           "Nada foi gravado.", "validacao_pos_escrita", novos[:20])
        os.replace(tmp, destino)
        res.update(acc)
        res.update(destino=destino, partes_alteradas=partes_alteradas, partes_removidas=partes_removidas,
                   cache_formulas=cache)
    except ErroXlsx as e:
        if tmp.exists():
            tmp.unlink()
        res["avisos"] = acc["avisos"] + [_aviso("erro", e.codigo, destino.name, str(e), e.candidatos)]
    except BaseException:
        if tmp.exists():
            tmp.unlink()
        raise
    return res


def _recalcular(caminho, timeout):
    return recalcular_com_soffice(caminho, timeout)


class _Gravacao:
    """Aplica o `estado` ao pacote: abas de processos, parâmetros, histórico e campos não migrados."""

    def __init__(self, pac, estado, modo_modelo, acc, *, aba, mapeamento, fecho_apos_novidade, acrescentar_colunas,
                 atualizar_data_referencia, limiar, invalidar_cache):
        fi = _ficha()
        self.pac, self.estado, self.modelo, self.acc = pac, estado or {}, modo_modelo, acc
        self.nomes_de_aba = [aba] if isinstance(aba, str) else list(aba or [])
        self.mapeamento = mapeamento or {}
        self.fecho_apos_novidade, self.acrescentar_colunas = fecho_apos_novidade, acrescentar_colunas
        self.atualizar_data_referencia, self.limiar = atualizar_data_referencia, limiar
        self.invalidar_cache = invalidar_cache
        self.perfil = self.estado.get("perfil") or {}
        self.data_base = (self.estado.get("data_base") or datetime.date.today().isoformat())[:10]
        self.data_br = fi.data_br(self.data_base)
        ativas = self.perfil.get("colunas_ativas")
        desconhecidas = [c for c in (ativas or []) if c not in CAMPOS_B]
        if desconhecidas:
            acc["avisos"].append(_aviso("atencao", "coluna_desconhecida_no_perfil", "perfil",
                                        "O perfil lista colunas que o modelo B não conhece (ignoradas): "
                                        + ", ".join(map(str, desconhecidas)) + ".", desconhecidas))
        if ativas:
            self.ativas = {c for c in ativas if c in CAMPOS_B} | {"numero", "andamentos"}
        else:
            self.ativas = set(COLUNAS_PADRAO) if modo_modelo else None
        if modo_modelo:
            self.ativas |= NUCLEO
        # fichas (uma por número) e eventos aprovados de cada uma (principal ou vinculados)
        self.fichas, vistos = [], set()
        for f in self.estado.get("fichas") or []:
            n = f.get("numero")
            if not n or n in vistos:
                acc["avisos"].append(_aviso("atencao", "ficha_ignorada", str(n or "?"),
                                            "Ficha sem número ou repetida no estado: ignorada.", [n] if n else []))
                continue
            vistos.add(n)
            self.fichas.append(f)
        dono = {}
        for f in self.fichas:
            for n in fi.todos_os_numeros(f):
                dono.setdefault(n, f["numero"])
        self.eventos = {}
        sem_ficha = set()
        for ev in self.estado.get("eventos") or []:
            if ev.get("status", "aprovado") != "aprovado":
                continue
            d = dono.get(ev.get("numero"))
            if d is None:
                sem_ficha.add(ev.get("numero"))
            else:
                self.eventos.setdefault(d, []).append(ev)
        if sem_ficha:
            acc["avisos"].append(_aviso("atencao", "evento_sem_ficha", "eventos",
                                        f"{len(sem_ficha)} processo(s) com andamento aprovado não estão nas fichas "
                                        "deste relatório; esses andamentos não foram gravados.", sorted(map(str, sem_ficha))))

    def ativa(self, campo):
        return self.ativas is None or campo in self.ativas

    def executar(self):
        self.processos()
        self.parametros()
        self.historico()
        self.campos_nao_migrados()

    # ---- abas de processos -------------------------------------------------------------
    def abas_de_processos(self):
        achadas = []
        for nome, parte in self.pac.abas():
            if self.nomes_de_aba and nome not in self.nomes_de_aba:
                continue
            for tabela, cabs in _cabecalhos_das_tabelas(self.pac, parte):
                mapa, ambiguos = mapear_cabecalhos(cabs, self.mapeamento)
                if "numero" in mapa and len(mapa) >= 4:
                    achadas.append({"nome": nome, "tabela": tabela if len(self.pac.tabelas_da_aba(parte)) > 1 else None,
                                    "mapa": mapa, "ambiguos": ambiguos,
                                    "encerrados": bool(_ABA_ENCERRADOS.search(_chave_cab(nome)))})
        if self.nomes_de_aba:
            faltam = [n for n in self.nomes_de_aba if n not in {a["nome"] for a in achadas}]
            if faltam:
                raise ErroXlsx(f"A aba {faltam[0]!r} não existe ou não tem a tabela de processos (cabeçalho com "
                               "'Número do Processo').", "aba_de_processos_nao_encontrada", faltam)
        if not achadas:
            raise NaoSuportado("Não encontrei na planilha nenhuma aba com a tabela de processos (uma linha de "
                               "cabeçalho com 'Número do Processo' e as demais colunas do relatório).",
                               "aba_de_processos_nao_encontrada")
        return achadas

    def _aba_para_novo(self, abas, f):
        def pontos(a):
            p = 0
            if a["encerrados"]:
                p += 2 if not f.get("ativo", True) else -3
            elif not f.get("ativo", True) and any(x["encerrados"] for x in abas):
                p -= 1
            area = _chave_cab(_ficha().obter(f, "area") or "")
            if area and area[:6] in _chave_cab(a["nome"]):
                p += 1
            return p
        return max(range(len(abas)), key=lambda i: (pontos(abas[i]), -i))

    def processos(self):
        acc = self.acc
        abas = self.abas_de_processos()
        for a in abas:
            for campo, cols in a["ambiguos"].items():
                acc["avisos"].append(_aviso(
                    "atencao", "cabecalho_ambiguo", a["nome"],
                    f"Mais de uma coluna da aba {a['nome']!r} parece ser '{CAMPOS_B[campo]}' "
                    f"({', '.join(col_letra(c) for c in cols)}); essa coluna não foi gravada. "
                    "Indique a coluna certa no perfil (mapeamento) ou renomeie o cabeçalho.", [col_letra(c) for c in cols]))
        # passo 1: onde cada processo está
        indice = {}
        for i, a in enumerate(abas):
            ed = Edicao(None, a["nome"], tabela=a["tabela"], pacote=self.pac)
            for r in range(ed.lin1, ed.lin2 + 1):
                for n in _numeros_da_celula(ed.valor(r, a["mapa"]["numero"])):
                    indice.setdefault(n, []).append((i, r))
        planos, ocupadas = [], {}
        for f in self.fichas:
            plano = _Plano(f, self.eventos.get(f["numero"], []))
            principal = list(dict.fromkeys(indice.get(f["numero"], [])))
            outros = list(dict.fromkeys(x for v in f.get("vinculados", []) for x in indice.get(v["numero"], [])))
            if len(principal) > 1:
                onde_esta = ", ".join("%s!%d" % (abas[i]["nome"], r) for i, r in principal)
                plano.motivo_ignorado = ("numero_duplicado_na_planilha",
                                         f"O processo {f['numero']} aparece em mais de uma linha da planilha "
                                         f"({onde_esta}); não foi atualizado para não escolher a errada.")
            elif principal:
                plano.aba, plano.linha = principal[0]
            elif len(outros) == 1:
                plano.aba, plano.linha = outros[0]
            elif len(outros) > 1:
                plano.motivo_ignorado = ("vinculados_em_linhas_diferentes",
                                         f"Os processos vinculados a {f['numero']} estão em linhas diferentes da "
                                         "planilha; não foi atualizado.")
            if plano.linha is not None:
                if (plano.aba, plano.linha) in ocupadas:
                    plano.motivo_ignorado = ("linha_compartilhada",
                                             f"A linha {plano.linha} da planilha já pertence ao processo "
                                             f"{ocupadas[(plano.aba, plano.linha)]}; {f['numero']} não foi gravado nela.")
                    plano.aba = plano.linha = None
                else:
                    ocupadas[(plano.aba, plano.linha)] = f["numero"]
            if plano.motivo_ignorado:
                codigo, msg = plano.motivo_ignorado
                acc["ignorados"].append({"numero": f["numero"], "motivo": codigo})
                acc["avisos"].append(_aviso("atencao", codigo, f["numero"], msg))
            elif plano.linha is None:
                plano.aba = self._aba_para_novo(abas, f)
            planos.append(plano)
        # passo 2: uma aba de cada vez
        for i, a in enumerate(abas):
            self._gravar_aba(i, a, [p for p in planos if p.aba == i and not p.motivo_ignorado])
        presentes = [d for d in acc["ignorados"] if d["motivo"] == "andamento_ja_presente"]
        if presentes:
            numeros = list(dict.fromkeys(d["numero"] for d in presentes))
            acc["avisos"].append(_aviso(
                "info", "andamento_ja_presente", "Andamentos",
                f"{len(presentes)} andamento(s) de {len(numeros)} processo(s) não foram gravados porque já constam no "
                "texto da planilha (igual ou reescrito com a mesma data). Confira os que foram tratados como "
                "'já presentes' em `ignorados`.", numeros[:50]))

    def _gravar_aba(self, i, a, planos):
        acc = self.acc
        mapa = dict(a["mapa"])
        ed = Edicao(None, a["nome"], tabela=a["tabela"], pacote=self.pac)
        onde = a["nome"]
        if self.ativas is None:
            # sem lista no perfil, coluna oculta na planilha do cliente é coluna que ninguém usa: não se grava nela
            ocultas = ed.colunas_ocultas()
            mapa = {c: col for c, col in mapa.items() if col not in ocultas or c in ("numero", "andamentos")}
        ed.colunas_humanas = {col for campo, col in mapa.items() if PAPEIS.get(campo) == "julgamento"}
        # colunas do perfil que a planilha não tem
        faltam = [c for c in COLUNAS_B_ORDEM if (self.ativas is not None and c in self.ativas) and c not in mapa
                  and c not in {k for k in a["ambiguos"]}] if not self.modelo else []
        if faltam:
            if self.acrescentar_colunas and ed.tabela_parte and not ed.dinamica_com_cache_salvo():
                for campo in faltam:
                    ed.acrescentar_coluna(CAMPOS_B[campo])
                    mapa[campo] = ed.coluna(CAMPOS_B[campo])
                acc["avisos"].append(_aviso("info", "coluna_acrescentada", onde,
                                            "Colunas acrescentadas à tabela (estavam no perfil e não na planilha): "
                                            + ", ".join(CAMPOS_B[c] for c in faltam) + ".", [CAMPOS_B[c] for c in faltam]))
            else:
                motivo = ("a opção de acrescentar colunas está desligada" if not self.acrescentar_colunas else
                          "a planilha tem tabela dinâmica com dados guardados" if ed.tabela_parte else
                          "a aba não tem tabela do Excel")
                acc["avisos"].append(_aviso("info", "coluna_ausente", onde,
                                            f"A planilha não tem as colunas {', '.join(CAMPOS_B[c] for c in faltam)} "
                                            f"({motivo}); esses campos não foram gravados.", [CAMPOS_B[c] for c in faltam]))
        divergencias = {}      # (campo) -> [numeros]
        celulas, novas, novos_numeros = {}, [], []
        for plano in planos:
            if plano.linha is not None:
                self._atualizar_existente(ed, onde, mapa, plano, celulas, divergencias)
            else:
                novas.append(self._linha_nova(ed, mapa, plano))
                novos_numeros.append(plano.ficha["numero"])
        ed.escrever_celulas(celulas)
        ini = ed.lin1 if (novas and _tabela_vazia(ed)) else ed.lin2 + 1
        _preencher_tabela(ed, [v for v, _t in novas])
        for k, (n, (_v, _t)) in enumerate(zip(novos_numeros, novas)):
            acc["processos_novos"].append(n)
            acc["mudancas"].append({"numero": n, "campo": "(linha nova)", "antes": None, "depois": f"{onde} linha {ini + k}"})
            acc["textos_gravados"][n] = _t
        if self.modelo:
            visiveis = {c for campo, c in mapa.items() if campo in self.ativas}
            ocultas = {c for campo, c in mapa.items() if campo not in self.ativas}
            ed.definir_colunas_ocultas(ocultas, visiveis)
        for campo, numeros in sorted(divergencias.items()):
            julgam = PAPEIS[campo] == "julgamento"
            acc["avisos"].append(_aviso(
                "atencao" if julgam else "info", "campo_divergente" if julgam else "valor_divergente", f"{onde}!{CAMPOS_B[campo]}",
                f"{CAMPOS_B[campo]}: em {len(numeros)} processo(s) a planilha tem um valor diferente do que o programa "
                f"tem; a planilha não foi alterada ({'campo de julgamento' if julgam else 'célula já preenchida'}).",
                numeros[:50]))
        for ref, motivo in ed.ignoradas:
            if "humano" in motivo:
                acc["avisos"].append(_aviso("info", "celula_humana_preservada", f"{onde}!{ref}",
                                            f"A célula {ref} já tinha valor de uma pessoa e foi preservada."))
        r = ed.aplicar()
        acc["avisos"].extend(_avisos_da_edicao(ed, r.avisos, onde))

    def _atualizar_existente(self, ed, onde, mapa, plano, celulas, divergencias):
        import planilha
        acc = self.acc
        f, r = plano.ficha, plano.linha
        numero = f["numero"]
        gravados = {}
        # --- coluna Andamentos
        col_a = mapa.get("andamentos")
        if col_a is not None:
            atual = ed.valor(r, col_a)
            atual = "" if atual is None else str(atual)
            base = ((f.get("linha_de_base") or {}).get("andamentos_texto") or "").strip()
            partida = atual if atual.strip() else base
            m = planilha.montar_texto(partida, plano.eventos, self.data_br, deduplicar=True,
                                      fecho_apos_novidade=self.fecho_apos_novidade, limiar=self.limiar)
            novo = m["texto"]
            ult = ((f.get("ultimo_texto_gravado") or {}).get("texto") or "")
            if ult and atual.strip() and planilha.chave_texto(ult) != planilha.chave_texto(atual):
                acc["avisos"].append(_aviso(
                    "info", "andamentos_editados_a_mao", f"{numero}",
                    "O texto de andamentos foi editado desde a última gravação; o programa só acrescentou, "
                    "sem reescrever o que estava lá."))
            if m["fecho_antigo"] and ult:
                fu = planilha.FECHO.search(ult)
                if fu and fu.group(0).strip() != m["fecho_antigo"] and novo != partida:
                    acc["avisos"].append(_aviso(
                        "atencao", "edicao_manual_sobrescrita", f"{numero}",
                        f"A frase de fecho do texto de andamentos ('{m['fecho_antigo']}') era diferente da última que o "
                        "programa gravou; foi trocada pela atual."))
            for ev, frase in m["ignorados"]:
                acc["ignorados"].append({"numero": numero, "motivo": "andamento_ja_presente", "data": ev.get("data"),
                                         "trecho": frase[:160]})
            if len(novo) > LIMITE_CELULA:
                acc["ignorados"].append({"numero": numero, "motivo": "texto_acima_do_limite"})
                acc["avisos"].append(_aviso(
                    "erro", "texto_acima_do_limite", numero,
                    f"O texto de andamentos de {numero} passaria de {LIMITE_CELULA} caracteres (limite do Excel por "
                    "célula). Este processo ficou sem a atualização; resuma ou divida o texto na planilha."))
                acc["textos_gravados"][numero] = atual
            else:
                if novo != atual.rstrip():
                    celulas[(r, col_a)] = novo
                    acc["mudancas"].append({"numero": numero, "campo": CAMPOS_B["andamentos"],
                                            "antes": atual or None, "depois": novo})
                acc["textos_gravados"][numero] = novo if novo != atual.rstrip() else atual
        # --- demais colunas
        for campo, col in mapa.items():
            if campo in ("numero", "andamentos") or not self.ativa(campo):
                continue
            novo = _valor_da_ficha(f, campo)
            if novo is None or ed.tem_formula(r, col):
                continue
            papel = PAPEIS[campo]
            atual = ed.valor(r, col)
            if atual is None:
                celulas[(r, col)] = novo
                acc["mudancas"].append({"numero": numero, "campo": CAMPOS_B[campo], "antes": None, "depois": _como_texto(novo)})
            elif _iguais(atual, novo):
                pass
            elif papel == "mecanico":
                anterior = (f.get("ultimos_valores_gravados") or {}).get(campo)
                if anterior is not None and not _iguais(atual, anterior):
                    acc["avisos"].append(_aviso(
                        "atencao", "edicao_manual_sobrescrita", f"{numero}",
                        f"{CAMPOS_B[campo]}: a planilha tinha '{_como_texto(atual)}', diferente do último valor que o "
                        f"programa gravou ('{anterior}'); foi trocado por '{_como_texto(novo)}'."))
                celulas[(r, col)] = novo
                acc["mudancas"].append({"numero": numero, "campo": CAMPOS_B[campo], "antes": _como_texto(atual),
                                        "depois": _como_texto(novo)})
            else:
                divergencias.setdefault(campo, []).append(numero)
                continue
            if papel == "mecanico":
                gravados[campo] = _como_texto(novo)
        if gravados:
            acc["valores_gravados"][numero] = gravados
        if any(k[0] == r for k in celulas) and numero not in acc["processos_atualizados"]:
            acc["processos_atualizados"].append(numero)

    def _linha_nova(self, ed, mapa, plano):
        import planilha
        f = plano.ficha
        valores = {}
        for campo, col in mapa.items():
            if campo == "andamentos" or not self.ativa(campo):
                continue
            v = _valor_da_ficha(f, campo)
            if v is not None:
                valores[col] = v
        gravados = {c: _como_texto(_valor_da_ficha(f, c)) for c in mapa
                    if PAPEIS.get(c) == "mecanico" and self.ativa(c) and _valor_da_ficha(f, c) is not None}
        if gravados:
            self.acc["valores_gravados"][f["numero"]] = gravados
        texto = ""
        col_a = mapa.get("andamentos")
        if col_a is not None:
            base = ((f.get("linha_de_base") or {}).get("andamentos_texto") or "").strip()
            m = planilha.montar_texto(base, plano.eventos, self.data_br, deduplicar=True,
                                      fecho_apos_novidade=self.fecho_apos_novidade, limiar=self.limiar)
            texto = m["texto"]
            if len(texto) > LIMITE_CELULA:
                self.acc["ignorados"].append({"numero": f["numero"], "motivo": "texto_acima_do_limite"})
                self.acc["avisos"].append(_aviso(
                    "erro", "texto_acima_do_limite", f["numero"],
                    f"O texto de andamentos de {f['numero']} passaria de {LIMITE_CELULA} caracteres; o processo entrou "
                    "na planilha sem o texto de andamentos."))
                texto = ""
            elif texto:
                valores[col_a] = texto
            for ev, frase in m["ignorados"]:
                self.acc["ignorados"].append({"numero": f["numero"], "motivo": "andamento_ja_presente",
                                              "data": ev.get("data"), "trecho": frase[:160]})
        return valores, texto

    # ---- outras abas ------------------------------------------------------------------------
    def _edicao_simples(self, nome, tabela=None, linha_cabecalho=None):
        return Edicao(None, nome, tabela=tabela, pacote=self.pac, linha_cabecalho=linha_cabecalho,
                      exigir_cabecalho=False)

    def parametros(self):
        achado = _aba_pelo_nome(self.pac, "parametros")
        if not achado:
            return
        nome, _parte = achado
        fi = _ficha()
        par = dict(self.perfil.get("parametros") or {})
        par.update(self.estado.get("parametros") or {})
        empresas = par.get("empresas_do_grupo")
        if isinstance(empresas, (list, tuple)):
            empresas = "; ".join(str(e) for e in empresas)
        # rótulo (chave) -> (valor, só_se_vazia)
        desejos = {}
        if self.atualizar_data_referencia:
            desejos["datadereferencia"] = (fi.data(par.get("data_referencia") or self.data_base), False)
        if par.get("headcount") not in (None, ""):
            desejos["numerodefuncionarios"] = (par["headcount"], True)
        if par.get("fator_correcao") not in (None, ""):
            desejos["fatordecorrecao"] = (par["fator_correcao"], True)
        if empresas:
            desejos["empresasdogrupo"] = (empresas, True)
        if not desejos:
            return
        ed = self._edicao_simples(nome)
        celulas = {}
        for r in ed.folha.numeros():
            lin = ed.folha.linha(r)
            rotulo = lin.celula(1) if lin else None
            chave = _chave_cab(ed._texto(rotulo)) if rotulo is not None else ""
            if chave in desejos:
                valor, so_vazia = desejos[chave]
                atual = ed.valor(r, 2)
                if valor is None or ed.tem_formula(r, 2):
                    continue
                if atual is None or (not so_vazia and not _iguais(atual, valor)):
                    celulas[(r, 2)] = valor
                    self.acc["mudancas"].append({"numero": "(parâmetros)", "campo": ed._texto(rotulo),
                                                 "antes": _como_texto(atual), "depois": _como_texto(valor)})
        ed.escrever_celulas(celulas)
        ed.aplicar()

    def _tabela_com(self, chave_aba, chaves_obrigatorias):
        achado = _aba_pelo_nome(self.pac, chave_aba)
        if not achado:
            return None
        nome, parte = achado
        tabelas = self.pac.tabelas_da_aba(parte)
        for tabela, cabs in _cabecalhos_das_tabelas(self.pac, parte):
            if set(chaves_obrigatorias) <= {_chave_cab(t) for t in cabs.values()}:
                return nome, (tabela if len(tabelas) > 1 else None)
        return None

    def historico(self):
        achado = self._tabela_com("historico", ("database", "processos"))
        if not achado:
            return
        fi = _ficha()
        nome, tabela = achado
        ed = self._edicao_simples(nome, tabela, linha_cabecalho=1)
        cols = {_chave_cab(t): c for c, t in ed.cabecalhos.items() if t}
        retratos = {}
        for ret in self.estado.get("historico") or []:
            if isinstance(ret, dict) and fi.data(ret.get("data_base")):
                retratos[str(ret["data_base"])[:10]] = ret
        retratos[self.data_base] = _totais_do_retrato(self.fichas, self.data_base)
        existentes = {}
        if "database" in cols:
            for r in range(ed.lin1, ed.lin2 + 1):
                d = ed.valor(r, cols["database"])
                if isinstance(d, datetime.date):
                    existentes[d] = r
        mapa = {"processos": "processos", "ativos": "ativos", "encerrados": "encerrados", "valordacausa": "valor_causa",
                "valorestimado": "valor_estimado", "valoreconomizado": "valor_economizado"}

        def linha(ret):
            d = {cols["database"]: fi.data(ret["data_base"])}
            for chave, campo in mapa.items():
                if chave in cols and campo in (ret.get("totais") or {}):
                    v = ret["totais"][campo]
                    d[cols[chave]] = v if isinstance(v, int) else Decimal(str(v))
            return d
        celulas, novas = {}, []
        for iso in sorted(retratos):
            d = fi.data(iso)
            if d in existentes:
                if iso == self.data_base:
                    celulas.update({(existentes[d], c): v for c, v in linha(retratos[iso]).items()})
            else:
                novas.append(linha(retratos[iso]))
        ed.escrever_celulas(celulas)
        _preencher_tabela(ed, novas)
        ed.aplicar()

    def campos_nao_migrados(self):
        dados = self.estado.get("campos_nao_migrados") or []
        if not dados:
            return
        achado = self._tabela_com("camposnaomigrados", ("colunadeorigem", "processo", "valor"))
        if not achado:
            self.acc["avisos"].append(_aviso(
                "info", "campos_nao_migrados_sem_aba", "campos_nao_migrados",
                "Há colunas do arquivo antigo sem destino no modelo, mas esta planilha não tem a aba 'Campos não "
                "migrados'; elas constam no relatório de migração.", [d.get("coluna") for d in dados]))
            return
        nome, tabela = achado
        ed = self._edicao_simples(nome, tabela, linha_cabecalho=1)
        cols = {_chave_cab(t): c for c, t in ed.cabecalhos.items() if t}
        ja = set()
        for r in range(ed.lin1, ed.lin2 + 1):
            ja.add(tuple(str(ed.valor(r, cols[k]) or "") for k in ("colunadeorigem", "processo", "valor")))
        novas = []
        for d in dados:
            valores = d.get("valores")
            itens = list(valores.items()) if isinstance(valores, dict) else [("", v) for v in d.get("amostra") or []]
            for numero, valor in itens:
                chave = (str(d.get("coluna") or ""), str(numero or ""), "" if valor is None else str(valor))
                if chave in ja:
                    continue
                ja.add(chave)
                linha = {cols["colunadeorigem"]: chave[0], cols["valor"]: chave[2]}
                if chave[1]:
                    linha[cols["processo"]] = chave[1]
                novas.append(linha)
        _preencher_tabela(ed, novas)
        ed.aplicar()


COLUNAS_B_ORDEM = tuple(c[0] for c in _COLUNAS)
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
