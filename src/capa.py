"""Capa e metadados do processo (Fase 2, WS-4): vara, município, UF, ajuizamento, citação, classe, assunto,
partes e valor da causa, extraídos das mesmas fontes que o coletor já abre (ou da API pública do CNJ) e
entregues num formato único, com a CONFIANÇA e a EVIDÊNCIA de cada campo.

    capa.extrair(fonte, dados, *, numero=None, cliente=None) -> {campo: {"valor", "confianca", "evidencia"}}
    capa.extrair_com_avisos(...)   -> (campos, avisos)       # avisos estruturados (CONTRATOS §0)
    capa.extrair_varias([(fonte, dados), ...], ...) -> (campos, avisos)   # junta fontes; avisa divergência
    capa.mesclar(*capas)           -> junta capas já extraídas (vence a de maior confiança)
    capa.de_coleta(resultado)      -> mesma estrutura, a partir do "capa" de um ResultadoColeta
    capa.aplicar(ficha, capa, ...) -> [{"campo", "antes", "depois"}]  # grava na ficha, origem "coletado"
    capa.consultar_datajud(numero, ...) -> (resposta | None, avisos)  # cliente da API pública do CNJ

Fontes (`fonte`) e o que `dados` aceita
    "autos"    autos do jus.br (PDPJ): HTML da tela (tests/fixtures/autos_pdpj.html), JSON da busca do portal
               (o que `coletor.tramitacoes_da_resposta` lê: {"content": [{"numeroProcesso", "tramitacoes": [...]}]}),
               uma lista dessas respostas, ou {"html": ..., "json": ...} com os dois.
    "trt"      JSON dos autos do PJe do TRT (o que `trt.itens_do_processo` lê: {"numero", "itensProcesso": [...]}).
    "djen"     publicações do DJEN (lista de itens de `djen.buscar`). Só devolve autores/réus/parte contrária
               quando `cliente` (nome ou lista de nomes) aparece em UM polo; senão, nada e um aviso.
    "datajud"  resposta da API pública do CNJ (ou só o `_source`, ou a lista de hits). Ver
               docs/fase2/spikes/S3-datajud.md: NÃO traz partes nem valor da causa.

Regras (CONTRATOS §6; PLANO 5.1)
    - campo ausente fica FORA do resultado: nunca é inventado nem preenchido com valor "neutro";
    - `polo_cliente` nunca vem de fonte alguma daqui (o tribunal não informa quem é o nosso cliente);
      `parte_contraria` só vem do DJEN, e só com o cliente identificável, sempre com confiança "baixa";
    - datas viram ISO e dinheiro vira texto decimal (`ficha.parse_data`, `ficha.parse_dinheiro`);
    - confiança: "alta" (campo próprio da fonte, formato conhecido), "media" (deduzido de movimento, de
      rótulo de tela ou de formato ainda não visto de perto), "baixa" (parcial ou possivelmente corrompido:
      só preenche campo vazio, nunca sobrescreve o que já existe);
    - dado de OUTRO processo (número que não confere) é recusado com aviso, nunca aproveitado.

Formatos presumidos: o que o coletor/`trt.py` já leem (título "Processo nº ... - CLASSE", blocos de movimento,
`dataHoraAjuizamento`, `orgaoJulgador.nome`, `classe[].descricao`, `itensProcesso`) é tratado como conhecido.
Os demais nomes de campo dos portais (assunto, partes, valor da causa, rótulos de um bloco "Dados do
processo") ainda NÃO foram capturados de página real: a leitura tenta vários nomes plausíveis e o que sai
deles tem confiança "media". Validar no piloto com `coletor.py --explorar` / `trt.py --explorar`.

DataJud (flag): o cliente só roda com `config.json -> "fontes_externas": {"datajud": {"ativo": true,
"chave": "<chave pública da wiki do CNJ>"}}` (ou `"datajud": true` com a chave na variável de ambiente
DATAJUD_CHAVE). Desligado por padrão. Respeita o limite de 120 requisições por minuto dos termos de uso.
Os testes injetam um transporte falso: nenhuma chamada de rede.
"""
import datetime
import json
import os
import re
import time
import urllib.error
import urllib.request

import carteira as cart
import comum
import djen
import ficha as fch

CONFIANCAS = ("baixa", "media", "alta")
_ORDEM = {c: i for i, c in enumerate(CONFIANCAS)}
FONTES = ("autos", "trt", "djen", "datajud")
# Campos que a capa pode devolver (grupos capa e partes da ficha; sem polo_cliente, ver regras acima).
CAMPOS_DA_CAPA = ("vara", "municipio", "uf", "data_ajuizamento", "data_citacao", "classe", "assunto",
                  "valor_causa", "autores", "reus", "parte_contraria", "outras_partes")
DATAJUD_URL = "https://api-publica.datajud.cnj.jus.br/api_publica_{alias}/_search"
DATAJUD_INTERVALO_S = 0.55   # 120 requisições por minuto (termo de uso, item 3.13) com folga
UF_DO_IBGE = {"11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP", "17": "TO", "21": "MA",
              "22": "PI", "23": "CE", "24": "RN", "25": "PB", "26": "PE", "27": "AL", "28": "SE", "29": "BA",
              "31": "MG", "32": "ES", "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS",
              "51": "MT", "52": "GO", "53": "DF"}
MESES = {m: i for i, m in enumerate(["janeiro", "fevereiro", "marco", "abril", "maio", "junho", "julho", "agosto",
                                     "setembro", "outubro", "novembro", "dezembro"], start=1)}


def aviso(nivel, codigo, onde, mensagem, candidatos=None):
    """Aviso estruturado (CONTRATOS §4): nivel info|atencao|erro; codigo estável."""
    return {"nivel": nivel, "codigo": codigo, "onde": onde, "mensagem": mensagem, "candidatos": list(candidatos or [])}


# ---------------------------------------------------------------- saída de cada fonte

class _Saida:
    """Acumula campos e avisos de uma fonte. Cada campo entra normalizado pelo tipo da ficha; se o mesmo campo
    chegar duas vezes, fica o de maior confiança (empate: o primeiro)."""

    def __init__(self, fonte, permitidos=None):
        self.fonte, self.campos, self.avisos = fonte, {}, []
        self.permitidos = set(permitidos or CAMPOS_DA_CAPA)

    def aviso(self, nivel, codigo, mensagem, candidatos=None):
        self.avisos.append(aviso(nivel, codigo, f"capa/{self.fonte}", mensagem, candidatos))

    def por(self, nome, valor, confianca, evidencia):
        if nome not in self.permitidos or nome not in fch.CAMPOS:
            return False
        if valor is None or (isinstance(valor, str) and not valor.strip()):
            return False
        _, _, tipo, _ = fch.CAMPOS[nome]
        if tipo == "data":
            norm = _data(valor)
        elif tipo == "dinheiro":
            norm = fch.parse_dinheiro(valor)
        else:
            norm = " ".join(str(valor).split())
        if norm in (None, ""):
            self.aviso("atencao", "capa_valor_ilegivel", f"{fch.CAMPOS[nome][0]}: valor não reconhecido ({str(valor)[:60]!r}); campo deixado vazio.")
            return False
        if tipo == "dinheiro" and fch.dinheiro(norm) <= 0:
            self.aviso("info", "capa_valor_zerado", f"{fch.CAMPOS[nome][0]}: a fonte traz valor zerado; tratado como não informado.")
            return False
        if nome == "uf":
            norm = norm.upper()
            if norm not in cart.UFS:
                self.aviso("atencao", "capa_valor_ilegivel", f"UF não reconhecida ({norm!r}); campo deixado vazio.")
                return False
        atual = self.campos.get(nome)
        if atual is not None and _ORDEM[atual["confianca"]] >= _ORDEM[confianca]:
            return False
        self.campos[nome] = {"valor": norm, "confianca": confianca, "evidencia": evidencia}
        return True


# ---------------------------------------------------------------- utilidades de leitura

def _sem_acento(texto):
    return comum.normalizar(str(texto))


def _digitos(texto):
    return re.sub(r"\D", "", str(texto or ""))


def _data(valor):
    """Data ISO a partir de ISO (com ou sem hora, com 'Z'), DD/MM/AAAA, 'd de mês de aaaa' ou AAAAMMDD[hhmmss].
    A parte da data é tomada como vem (sem conversão de fuso: ver S3-datajud.md)."""
    if valor in (None, ""):
        return None
    if isinstance(valor, (int, float)) and not isinstance(valor, bool):
        valor = str(int(valor))
    if isinstance(valor, (datetime.date, datetime.datetime)):
        return fch.parse_data(valor)
    s = str(valor).strip()
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})(?:\d{6})?", s)
    if m:
        s = f"{m[1]}-{m[2]}-{m[3]}"
    m = re.search(r"(\d{1,2})\s+de\s+([a-zç]+)\s+de\s+(\d{4})", _sem_acento(s))
    if m and m[2] in MESES:
        s = f"{int(m[1]):02d}/{MESES[m[2]]:02d}/{m[3]}"
    return fch.parse_data(s)


def _br(iso):
    return fch.data_br(iso)


def _texto_limpo(html_ou_texto):
    import html as _h
    return " ".join(_h.unescape(re.sub(r"<[^>]+>", " ", str(html_ou_texto))).split())


def _primeiro(reg, chaves):
    """Valor da primeira chave presente e não vazia (sem diferenciar maiúsculas)."""
    minusc = {str(k).lower(): v for k, v in reg.items()}
    for k in chaves:
        v = minusc.get(k.lower())
        if v not in (None, "", [], {}):
            return v
    return None


def _nome(v):
    """Texto de um valor que pode ser str, {"nome"|"descricao"...} ou lista (primeiro com texto)."""
    if isinstance(v, str):
        return " ".join(v.split())
    if isinstance(v, dict):
        for k in ("nome", "descricao", "nomeOrgao", "nomeOrgaoJulgador", "texto", "titulo"):
            if isinstance(v.get(k), str) and v[k].strip():
                return " ".join(v[k].split())
        return ""
    if isinstance(v, (list, tuple)):
        for x in v:
            n = _nome(x)
            if n:
                return n
    return ""


def _achatar(v):
    if isinstance(v, (list, tuple)):
        for x in v:
            yield from _achatar(x)
    elif v not in (None, ""):
        yield v


def _corrompido(texto):
    return "?" in texto or "�" in texto


# ---------------------------------------------------------------- partes, município, citação

_NAO_PARTE = re.compile(r"advog|procurador|defensor|perit|testemunha|fiscal da lei|ministerio publico|curador|leiloeiro", re.I)


def _polo(texto):
    n = _sem_acento(texto)
    if not n:
        return None
    if "ativo" in n or n in ("a", "autor", "autora", "autores", "reclamante", "requerente", "exequente", "impetrante"):
        return "A"
    if "passivo" in n or n in ("p", "reu", "re", "reus", "reclamado", "reclamada", "requerido", "requerida",
                                "executado", "executada", "impetrado"):
        return "P"
    if any(t in n for t in ("terceir", "outros", "interessad", "assistente", "litisconsorte")):
        return "outros"
    return None


def _nomes_de_polo(v):
    """Nomes de um polo (str, lista de str/dict, dict com "partes"), sem advogados e afins."""
    nomes = []
    for x in _achatar(v):
        if isinstance(x, str):
            nomes.append(" ".join(x.split()))
        elif isinstance(x, dict):
            tipo = " ".join(str(x.get(k, "")) for k in ("tipoParte", "tipo", "papel", "tipoPessoa") if isinstance(x.get(k), str))
            if _NAO_PARTE.search(_sem_acento(tipo)):
                continue
            if x.get("partes"):
                nomes += _nomes_de_polo(x["partes"])
            elif _nome(x):
                nomes.append(_nome(x))
    visto = []
    for n in nomes:
        if n and n not in visto:
            visto.append(n)
    return visto


def _partes(reg):
    """{"A": [...], "P": [...], "outros": [...]} de um registro de portal (poloAtivo/poloPassivo e/ou partes[])."""
    saida = {"A": [], "P": [], "outros": []}
    for chaves, polo in ((("poloAtivo", "polo_ativo", "autores"), "A"), (("poloPassivo", "polo_passivo", "reus"), "P")):
        saida[polo] += _nomes_de_polo(_primeiro(reg, chaves))
    lista = reg.get("partes")
    if isinstance(lista, list):
        for p in lista:
            if not isinstance(p, dict):
                continue
            polo = _polo(str(p.get("polo") or p.get("poloProcessual") or ""))
            if polo:
                saida[polo] += [n for n in _nomes_de_polo(p) if n not in saida[polo]]
    return saida


_MUNICIPIO = (re.compile(r"\bcomarca\s+d[eao]s?\s+(.+)$", re.I), re.compile(r"\bvara\s+do\s+trabalho\s+d[eao]s?\s+(.+)$", re.I),
              re.compile(r"\bforo\s+(?:regional\s+.{0,40}?\s+)?d[eao]s?\s+(.+)$", re.I))


def _municipio_do_orgao(nome):
    """Município deduzido do nome do órgão ("... da Comarca de X", "Vara do Trabalho de X"); None se não houver
    um desses padrões (não há palpite por 'de X' solto: 'Vara de Execução Fiscal' não é município)."""
    for rx in _MUNICIPIO:
        m = rx.search(nome or "")
        if m:
            x = re.sub(r"\s*[-/(].*$", "", m[1]).strip(" .")
            if x:
                return x
    return None


_CITA_SIM = re.compile(
    r"confirmad[ao]\s+a\s+cita|cita[cç][aã]o\s+(?:realizada|efetivada|confirmada|cumprida|positiva|"
    r"eletr[oô]nica\s+(?:realizada|confirmada))|cumprid[oa]\s+.{0,30}cita[cç][aã]o|"
    r"aviso\s+de\s+recebimento.{0,25}cita[cç][aã]o.{0,25}(?:positiv|recebid)|^\s*cita[cç][aã]o\s*$|^\s*citad[oa]\b", re.I)
_CITA_NAO = re.compile(r"expedi|determinad|designa|negativ|sem\s+[eê]xito|frustr|n[aã]o\s+localiz|ausen|aguard|prazo|"
                       r"dispens|cancel|anulad|nulidade|requer|pedido|devolvid", re.I)
_DISTRIBUICAO = re.compile(r"^\s*(?:distribu[ií]d[oa]|distribui[cç][aã]o)\b", re.I)


def _de_movimentos(saida, movimentos, de_onde, usar_distribuicao=True):
    """Deduz data de citação (e, se faltar, de ajuizamento) dos movimentos [(data ISO, texto)].
    Citação só quando o texto diz que foi REALIZADA/confirmada; "expedida", "prazo de citação", tentativa
    negativa etc. ficam de fora (campo vazio é melhor que data errada). Vale a mais antiga."""
    citacoes = sorted((d, t) for d, t in movimentos if d and t and _CITA_SIM.search(t) and not _CITA_NAO.search(t))
    if citacoes:
        d, t = citacoes[0]
        saida.por("data_citacao", d, "media", f"{de_onde}: movimento \"{t[:90]}\" em {_br(d)}")
    if usar_distribuicao:
        dist = sorted((d, t) for d, t in movimentos if d and t and _DISTRIBUICAO.search(t))
        if dist:
            d, t = dist[0]
            saida.por("data_ajuizamento", d, "media", f"{de_onde}: movimento \"{t[:90]}\" em {_br(d)} (distribuição, não a data de ajuizamento propriamente dita)")


# ---------------------------------------------------------------- leitor tolerante de um registro de portal

_CH_CLASSE = ("classe", "classeJudicial", "classeProcessual", "nomeClasse")
_CH_ASSUNTO = ("assunto", "assuntos", "assuntoPrincipal", "assuntosProcesso")
_CH_ORGAO = ("orgaoJulgador", "orgao_julgador", "orgao", "vara", "juizo", "nomeOrgao")
_CH_AJUIZ = ("dataHoraAjuizamento", "dataAjuizamento", "autuadoEm", "dataAutuacao", "distribuidoEm", "dataDistribuicao")
_CH_VALOR = ("valorDaCausa", "valorCausa", "valorAcao", "valorDaAcao")
_CH_MUNICIPIO = ("municipio", "comarca", "cidade")
_CH_MOVS = ("movimentos", "movimentacoes", "movimentacao")


def _assunto(reg):
    itens = list(_achatar(_primeiro(reg, _CH_ASSUNTO)))
    if not itens:
        return None, 0
    escolhido = next((i for i in itens if isinstance(i, dict) and i.get("principal") in (True, "true", "S", "s", 1)), itens[0])
    return _nome(escolhido), len(itens) - 1


def _ibge_para_uf(codigo):
    c = _digitos(codigo)
    return UF_DO_IBGE.get(c[:2]) if len(c) == 7 else None


def _ler_registro(saida, reg, de_onde, conf_conhecida="alta", conf_presumida="media", conf_data=None):
    """Campos de capa de um dict de portal. `conf_conhecida` vale para os nomes de campo que o coletor já lê
    de página real (dataHoraAjuizamento, orgaoJulgador, classe); o resto sai com `conf_presumida`."""
    if not isinstance(reg, dict):
        return
    chave_ajuiz = next((k for k in _CH_AJUIZ if k.lower() in {str(x).lower() for x in reg}), None)
    if chave_ajuiz:
        conf = conf_data or (conf_conhecida if chave_ajuiz == "dataHoraAjuizamento" else conf_presumida)
        saida.por("data_ajuizamento", _primeiro(reg, (chave_ajuiz,)), conf, f"{de_onde}: {chave_ajuiz}")
    classe = _nome(_primeiro(reg, _CH_CLASSE))
    if classe:
        saida.por("classe", classe, conf_conhecida, f"{de_onde}: classe")
    assunto, outros = _assunto(reg)
    if assunto:
        extra = f" (+{outros} outro(s) assunto(s) na fonte)" if outros else ""
        saida.por("assunto", assunto, conf_presumida, f"{de_onde}: assunto{extra}")
    orgao_bruto = _primeiro(reg, _CH_ORGAO)
    orgao = _nome(orgao_bruto)
    if orgao:
        corrompido = _corrompido(orgao)
        if corrompido:
            saida.aviso("atencao", "capa_texto_corrompido", f"Vara/juízo com caracteres trocados na fonte ({orgao!r}); só preenche campo vazio.")
        saida.por("vara", orgao, "baixa" if corrompido else conf_conhecida, f"{de_onde}: órgão julgador")
        mun = _municipio_do_orgao(orgao)
        if mun and not corrompido:
            saida.por("municipio", mun, "media", f"{de_onde}: deduzido do nome do órgão julgador ({orgao[:60]})")
    mun_direto = _nome(_primeiro(reg, _CH_MUNICIPIO))
    if mun_direto:
        saida.por("municipio", mun_direto, conf_presumida, f"{de_onde}: município")
    uf = _primeiro(reg, ("uf", "siglaUF", "siglaUf"))
    if isinstance(orgao_bruto, dict):
        ibge = _primeiro(orgao_bruto, ("codigoMunicipioIBGE", "codigoIBGE", "municipioIBGE"))
        if not uf and ibge and _ibge_para_uf(ibge):
            saida.por("uf", _ibge_para_uf(ibge), "media", f"{de_onde}: código IBGE do município do órgão julgador ({_digitos(ibge)})")
    if uf and isinstance(uf, str):
        saida.por("uf", uf, conf_presumida, f"{de_onde}: UF")
    valor = _primeiro(reg, _CH_VALOR)
    if isinstance(valor, dict):
        valor = _primeiro(valor, ("valor", "valorCausa"))
    if valor is not None:
        saida.por("valor_causa", valor, conf_presumida, f"{de_onde}: valor da causa")
    partes = _partes(reg)
    if partes["A"]:
        saida.por("autores", "; ".join(partes["A"]), conf_presumida, f"{de_onde}: polo ativo")
    if partes["P"]:
        saida.por("reus", "; ".join(partes["P"]), conf_presumida, f"{de_onde}: polo passivo")
    if partes["outros"]:
        saida.por("outras_partes", "; ".join(partes["outros"]), conf_presumida, f"{de_onde}: demais partes")
    movs = _movimentos_do_registro(reg)
    if movs:
        _de_movimentos(saida, movs, de_onde, usar_distribuicao=not chave_ajuiz)


def _movimentos_do_registro(reg):
    lista = _primeiro(reg, _CH_MOVS)
    if not isinstance(lista, list):
        return []
    movs = []
    for m in lista:
        if isinstance(m, dict):
            texto = _nome(m.get("nome") or m.get("descricao") or m.get("texto") or m.get("titulo") or "")
            for c in m.get("complementosTabelados") or []:
                if isinstance(c, dict) and c.get("nome"):
                    texto += f" {c['nome']}"
            movs.append((_data(m.get("dataHora") or m.get("data")), texto.strip()))
    return movs


def _numero_confere(esperado, achado):
    return not esperado or not achado or _digitos(esperado) == _digitos(achado)


# ---------------------------------------------------------------- fonte 1: autos do jus.br

_ROTULOS_HTML = {
    "classe": ("classe", "classe judicial"),
    "assunto": ("assunto", "assunto principal"),
    "vara": ("orgao julgador", "vara", "juizo", "orgao"),
    "data_ajuizamento": ("data de ajuizamento", "data do ajuizamento", "ajuizamento", "data de distribuicao", "distribuido em",
                         "data da autuacao", "autuado em"),
    "data_citacao": ("data da citacao", "data de citacao"),
    "valor_causa": ("valor da causa", "valor da acao"),
    "municipio": ("comarca", "municipio"),
    "uf": ("uf",),
    "autores": ("polo ativo", "autor", "autores", "autora", "requerente", "reclamante", "exequente"),
    "reus": ("polo passivo", "reu", "reus", "re", "requerido", "reclamado", "reclamada", "executado"),
    "outras_partes": ("outras partes", "terceiros", "terceiro interessado"),
}


def _linhas_e_pares(html):
    """Texto visível do HTML em linhas e os pares <dt>/<dd> (rótulo, valor)."""
    import html as _h
    limpo = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    pares = [(_texto_limpo(a), _texto_limpo(b)) for a, b in re.findall(r"(?is)<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", limpo)]
    quebrado = re.sub(r"(?i)</?(p|div|li|tr|dt|dd|h[1-6]|br|table|section|mat-[a-z-]+|app-[a-z-]+)\b[^>]*>", "\n", limpo)
    linhas = [" ".join(_h.unescape(re.sub(r"<[^>]+>", " ", l)).split()) for l in quebrado.splitlines()]
    return [l for l in linhas if l], pares


def _movimentos_da_aba(html):
    """[(data ISO, texto)] da aba "Movimentos" da tela de autos (mesma estrutura que o coletor lê).
    Associa cada corpo de aba ao rótulo de mesma posição (as duas abas usam os mesmos blocos .movimento)."""
    rotulos = [_texto_limpo(r) for r in re.findall(r'(?is)class="[^"]*\bmat-tab-label-content\b[^"]*"[^>]*>(.*?)</div>', html)]
    corpos = re.split(r"(?i)<mat-tab-body\b", html)[1:]
    alvo = next((c for r, c in zip(rotulos, corpos) if _sem_acento(r).startswith("movimento")), None)
    if alvo is None:
        return []
    movs = []
    for bloco in re.split(r'(?i)<div\b[^>]*class="[^"]*\bmovimento\b[^"]*"[^>]*>', alvo)[1:]:
        m = re.search(r'(?is)class="[^"]*\bdata\b[^"]*"[^>]*>(.*?)</div>', bloco)
        data = _data(_texto_limpo(m[1])) if m else None
        for t in re.findall(r'(?is)class="[^"]*\btexto\b[^"]*"[^>]*>(.*?)</div>', bloco):
            movs.append((data, _texto_limpo(t)))
    return movs


def _ler_html_autos(saida, html, numero):
    linhas, pares = _linhas_e_pares(html)
    titulo = next((re.search(r"Processo\s*n[ºo°.]*\s*([\d.\-]+)\s*[-–]\s*(.+)$", l, re.I) for l in linhas
                   if re.search(r"Processo\s*n[ºo°.]*\s*[\d.\-]+\s*[-–]", l, re.I)), None)
    if titulo and not _numero_confere(numero, titulo[1]):
        saida.aviso("erro", "capa_processo_nao_encontrado", f"A tela é de outro processo ({titulo[1]}); nada foi aproveitado.")
        return
    if titulo:
        saida.por("classe", titulo[2], "alta", "tela dos autos (jus.br): título da página")
    rotulos = {r: campo for campo, rs in _ROTULOS_HTML.items() for r in rs}
    candidatos = list(pares)
    for l in linhas:
        m = re.match(r"([^:]{2,40}):\s*(.+)$", l)
        if m:
            candidatos.append((m[1], m[2]))
    for rot, valor in candidatos:
        campo = rotulos.get(_sem_acento(rot).strip(" :"))
        if campo and valor and _sem_acento(valor) not in ("-", "nao informado", "nao se aplica"):
            saida.por(campo, valor, "media", f"tela dos autos (jus.br): rótulo \"{rot.strip(' :')}\"")
    vara = saida.campos.get("vara")
    if vara and "municipio" not in saida.campos and _municipio_do_orgao(vara["valor"]):
        saida.por("municipio", _municipio_do_orgao(vara["valor"]), "media",
                  f"tela dos autos (jus.br): deduzido do nome do órgão julgador ({vara['valor'][:60]})")
    _de_movimentos(saida, _movimentos_da_aba(html), "tela dos autos (jus.br)", usar_distribuicao=True)


def _eh_segundo_grau(t):
    orgao = _nome(t.get("orgaoJulgador"))
    classes = " ".join(_nome(c) for c in _achatar(t.get("classe")))
    return bool(re.search(r"C[AÂ]MARA|TURMA|GADES|GABINETE|DESEMBARG|SE[CÇ][AÃ]O|PLENO|[ÓO]RG[AÃ]O ESPECIAL", orgao, re.I)
                or re.search(r"apela|agravo|recurso|remessa necess", classes, re.I))


def _tramitacao_de_1o_grau(respostas, numero, saida):
    digitos = _digitos(numero)
    achadas = []
    for resp in respostas:
        for proc in (resp.get("content") or []) if isinstance(resp, dict) else []:
            if digitos and _digitos(proc.get("numeroProcesso")) != digitos:
                continue
            achadas.append(proc)
    if not achadas:
        return None
    tramitacoes = [t for p in achadas for t in (p.get("tramitacoes") or []) if isinstance(t, dict)]
    if not tramitacoes:
        return None
    primeiras = [t for t in tramitacoes if not _eh_segundo_grau(t)] or tramitacoes
    primeiras.sort(key=lambda t: str(t.get("dataHoraAjuizamento") or "9999"))
    if len(primeiras) > 1 and _nome(primeiras[0].get("orgaoJulgador")) != _nome(primeiras[1].get("orgaoJulgador")):
        saida.aviso("info", "capa_varias_tramitacoes", "O processo tem mais de uma tramitação de 1º grau; usada a de ajuizamento mais antigo.",
                    [_nome(t.get("orgaoJulgador")) for t in primeiras])
    return primeiras[0]


def _de_autos(saida, dados, numero, cliente):
    html, respostas = None, []
    if isinstance(dados, str):
        html = dados
    elif isinstance(dados, dict) and ("html" in dados or "json" in dados):
        html = dados.get("html")
        j = dados.get("json")
        respostas = j if isinstance(j, list) else ([j] if j else [])
    elif isinstance(dados, dict):
        respostas = [dados]
    elif isinstance(dados, list):
        respostas = [d for d in dados if isinstance(d, dict)]
    else:
        saida.aviso("erro", "capa_dados_ilegiveis", "Os dados dos autos não estão em formato conhecido (esperado HTML ou JSON do portal).")
        return
    if respostas:
        t = _tramitacao_de_1o_grau(respostas, numero, saida)
        if t is not None:
            _ler_registro(saida, t, "busca do portal jus.br")
        elif not html:
            saida.aviso("erro", "capa_processo_nao_encontrado", "A resposta do portal não traz este processo.")
    if html:
        _ler_html_autos(saida, html, numero)


# ---------------------------------------------------------------- fonte 2: consulta do TRT

def _de_trt(saida, dados, numero, cliente):
    if not isinstance(dados, dict):
        saida.aviso("erro", "capa_dados_ilegiveis", "Os autos do TRT não estão em formato conhecido (esperado o JSON dos autos).")
        return
    if not _numero_confere(numero, dados.get("numero")):
        saida.aviso("erro", "capa_processo_nao_encontrado", f"Os autos são de outro processo ({dados.get('numero')}); nada foi aproveitado.")
        return
    if dados.get("segredoJustica") in (True, "true", "True") or "segredo de justiça" in _sem_acento(json.dumps(dados.get("situacao", ""))):
        saida.aviso("atencao", "capa_sigilo", "Processo em segredo de justiça: capa não aproveitada.")
        return
    _ler_registro(saida, dados, "consulta do TRT")
    movs = []
    for it in dados.get("itensProcesso") or []:
        if isinstance(it, dict) and it.get("documento") not in (True, "True"):
            movs.append((_data(it.get("data")), " ".join(str(it.get("titulo") or "").split())))
    if movs:
        _de_movimentos(saida, movs, "consulta do TRT", usar_distribuicao="data_ajuizamento" not in saida.campos)


# ---------------------------------------------------------------- fonte 3: DJEN

def _nomes_do_cliente(cliente):
    if not cliente:
        return []
    if isinstance(cliente, str):
        return [cliente]
    if isinstance(cliente, dict):
        return [cliente.get("nome", ""), *cliente.get("variacoes", [])]
    return [str(c) for c in cliente if c]


def _de_djen(saida, dados, numero, cliente):
    itens = dados.get("items") if isinstance(dados, dict) else dados
    if not isinstance(itens, list):
        saida.aviso("erro", "capa_dados_ilegiveis", "As publicações do DJEN não estão em formato conhecido (esperada a lista de itens).")
        return
    if numero:
        itens = [i for i in itens if _numero_confere(numero, i.get("numeroprocessocommascara") or i.get("numero_processo"))]
    partes = djen.partes_por_polo(itens)
    if not (partes["A"] or partes["P"]):
        saida.aviso("info", "capa_djen_sem_partes", "O DJEN não trouxe destinatários com polo para este processo.")
        return
    nomes = _nomes_do_cliente(cliente)
    do_cliente = {p for p in ("A", "P") if any(cart.nome_bate(n, d) for n in nomes for d in partes[p])}
    if not nomes or len(do_cliente) != 1:
        motivo = "cliente não informado" if not nomes else ("cliente não aparece nas publicações" if not do_cliente
                                                            else "cliente aparece nos dois polos")
        saida.aviso("atencao", "capa_cliente_nao_identificado",
                    f"Partes do DJEN não aproveitadas: {motivo}. Sem identificar o cliente, não dá para dizer quem é autor, réu ou parte contrária.")
        return
    polo = next(iter(do_cliente))
    contrario = "P" if polo == "A" else "A"
    ev = "DJEN: destinatários das publicações (podem ser só parte das partes; nomes longos vêm cortados)"
    saida.por("autores", "; ".join(partes["A"]), "baixa", f"{ev}, polo A")
    saida.por("reus", "; ".join(partes["P"]), "baixa", f"{ev}, polo P")
    saida.por("parte_contraria", "; ".join(partes[contrario]), "baixa", f"{ev}; cliente no polo {polo}")
    if partes["outros"]:
        saida.por("outras_partes", "; ".join(partes["outros"]), "baixa", f"{ev}, polo não identificado")


# ---------------------------------------------------------------- fonte 4: DataJud (API pública do CNJ)

_GRAU_PREFERIDO = ("G1", "JE", "TR", "G2", "SUP")


def _fontes_datajud(dados):
    """Lista de _source a partir da resposta completa, de um hit, de um _source ou de uma lista deles."""
    if isinstance(dados, list):
        return [s for d in dados for s in _fontes_datajud(d)]
    if not isinstance(dados, dict):
        return []
    if "hits" in dados:
        h = dados["hits"]
        return _fontes_datajud(h.get("hits") if isinstance(h, dict) else h)
    if "_source" in dados:
        return [dados["_source"]] if isinstance(dados["_source"], dict) else []
    return [dados] if "numeroProcesso" in dados else []


def _de_datajud(saida, dados, numero, cliente):
    fontes = _fontes_datajud(dados)
    if numero:
        fontes = [s for s in fontes if _digitos(s.get("numeroProcesso")) == _digitos(numero)]
    if not fontes:
        saida.aviso("info", "capa_processo_nao_encontrado", "O DataJud não devolveu este processo (pode não estar na base ou ser sigiloso).")
        return
    public = [s for s in fontes if not s.get("nivelSigilo")]
    if len(public) < len(fontes):
        saida.aviso("atencao", "capa_sigilo", "O DataJud marca o processo com nível de sigilo: capa não aproveitada.")
    if not public:
        return
    public.sort(key=lambda s: _GRAU_PREFERIDO.index(s.get("grau")) if s.get("grau") in _GRAU_PREFERIDO else 99)
    s = public[0]
    if len(public) > 1:
        saida.aviso("info", "capa_varias_tramitacoes", f"O DataJud devolveu {len(public)} tramitações; usada a do grau {s.get('grau')}.",
                    [str(p.get("grau")) for p in public])
    de_onde = f"DataJud ({s.get('tribunal', '?')}, grau {s.get('grau', '?')})"
    # O DataJud usa "assuntos" (às vezes lista de listas), "orgaoJulgador" e "dataAjuizamento"; não tem partes nem valor.
    reg = {k: v for k, v in s.items() if k not in ("poloAtivo", "poloPassivo", "partes", "valorCausa", "valorDaCausa")}
    # classe, assuntos e órgão são campos documentados no glossário; a data fica "media" (a própria wiki mostra
    # dataAjuizamento diferente do movimento de Distribuição) e o município/UF são deduzidos (ver _ler_registro).
    _ler_registro(saida, reg, de_onde, conf_conhecida="alta", conf_presumida="alta", conf_data="media")
    saida.campos.pop("valor_causa", None)
    saida.campos.pop("autores", None)
    saida.campos.pop("reus", None)


# ---------------------------------------------------------------- API de extração

_LEITORES = {"autos": _de_autos, "trt": _de_trt, "djen": _de_djen, "datajud": _de_datajud}
# Campos que NENHUMA fonte devolve (tribunal não sabe quem é o cliente) e os que só o DJEN pode devolver.
_NUNCA = ("polo_cliente",)
_SO_DJEN = ("parte_contraria",)


def extrair_com_avisos(fonte, dados, *, numero=None, cliente=None):
    """(campos, avisos). `numero`: confere se os dados são mesmo deste processo (recusa se não forem);
    `cliente`: nome ou lista de nomes, só usado pelo DJEN. Fonte desconhecida é erro de programação (ValueError)."""
    if fonte not in _LEITORES:
        raise ValueError(f"Fonte de capa desconhecida: {fonte!r} (use {', '.join(FONTES)})")
    saida = _Saida(fonte)
    if dados in (None, "", [], {}):
        saida.aviso("info", "capa_sem_dados", "Nenhum dado recebido desta fonte.")
        return {}, saida.avisos
    try:
        _LEITORES[fonte](saida, dados, numero, cliente)
    except (TypeError, ValueError, KeyError, AttributeError) as e:  # formato inesperado do portal: aviso, não queda
        saida.aviso("erro", "capa_dados_ilegiveis", f"Não consegui ler os dados desta fonte ({type(e).__name__}).")
        saida.campos = {}
    campos = {k: v for k, v in saida.campos.items()
              if k in CAMPOS_DA_CAPA and k not in _NUNCA and (k not in _SO_DJEN or fonte == "djen")}
    return campos, saida.avisos


def extrair(fonte, dados, *, numero=None, cliente=None):
    """{campo: {"valor", "confianca", "evidencia"}}; só os campos que a fonte realmente trouxe."""
    return extrair_com_avisos(fonte, dados, numero=numero, cliente=cliente)[0]


def mesclar(*capas):
    """Junta capas já extraídas: por campo, vence a de maior confiança (empate: a primeira da lista)."""
    saida = {}
    for c in capas:
        for campo, reg in (c or {}).items():
            atual = saida.get(campo)
            if atual is None or _ORDEM[reg["confianca"]] > _ORDEM[atual["confianca"]]:
                saida[campo] = reg
    return saida


def extrair_varias(entradas, *, numero=None, cliente=None):
    """(campos, avisos) de várias fontes, `entradas = [(fonte, dados), ...]` em ordem de preferência.
    Se duas fontes trazem valores diferentes para o mesmo campo, vale a de maior confiança e vem o aviso
    `capa_fontes_divergem` (com os dois valores) para a revisão."""
    todas, avisos = [], []
    for fonte, dados in entradas:
        c, a = extrair_com_avisos(fonte, dados, numero=numero, cliente=cliente)
        todas.append((fonte, c))
        avisos += a
    final = mesclar(*(c for _, c in todas))
    for campo, reg in final.items():
        outros = [(f, c[campo]["valor"]) for f, c in todas if campo in c and c[campo]["valor"] != reg["valor"]]
        if outros and campo not in ("autores", "reus", "outras_partes", "parte_contraria", "assunto"):
            avisos.append(aviso("atencao", "capa_fontes_divergem", f"capa/{campo}",
                                f"{fch.CAMPOS[campo][0]}: as fontes divergem; ficou \"{reg['valor']}\" (confiança {reg['confianca']}).",
                                [f"{f}: {v}" for f, v in outros]))
    return final, avisos


def de_coleta(resultado, fonte="coletor"):
    """Capa no formato desta API a partir do `capa` de um ResultadoColeta ({campo: valor}). Confiança "alta"
    (o coletor já entrega o que o tribunal mostrou); polo_cliente e parte_contraria nunca passam."""
    capa_ = (resultado or {}).get("capa") or {}
    saida = _Saida(fonte)
    for campo, valor in capa_.items():
        if campo not in _NUNCA and campo not in _SO_DJEN:
            saida.por(campo, valor, "alta", f"coleta ({fonte})")
    return saida.campos


# ---------------------------------------------------------------- gravação na ficha

def aplicar(ficha, capa_, *, somente_vazios=False):
    """Grava a capa na ficha com origem "coletado" (`ficha.definir`: humano nunca é sobrescrito; coletado
    novo substitui coletado ou migrado antigo). Volta [{"campo", "antes", "depois"}] só do que mudou.

    - confiança "baixa" só preenche campo vazio (não sobrescreve nada);
    - `polo_cliente` nunca é gravado; `parte_contraria` só quando estiver vazia;
    - `somente_vazios=True` não troca nenhum valor já existente (útil depois de uma migração curada à mão).
    A segunda aplicação da mesma capa não muda nada."""
    mudancas = []
    for campo, reg in (capa_ or {}).items():
        if campo in _NUNCA or campo not in fch.CAMPOS:
            continue
        antes = fch.obter(ficha, campo)
        if antes not in (None, "") and (somente_vazios or reg.get("confianca") == "baixa" or campo in _SO_DJEN):
            continue
        evidencia = f"{reg.get('evidencia', '')} [confiança {reg.get('confianca', '?')}]".strip()
        if fch.definir(ficha, campo, reg["valor"], "coletado", evidencia=evidencia, forcar=True):
            depois = fch.obter(ficha, campo)
            if depois != antes:
                mudancas.append({"campo": campo, "antes": antes, "depois": depois})
    return mudancas


# ---------------------------------------------------------------- cliente do DataJud

def alias_datajud(numero):
    """'api_publica_<alias>' sem o prefixo: 'tjce', 'trt7', 'trf1', 'tjdft', 'stj', 'tst'; None se o DataJud
    não tiver índice para o número (STF, CNJ, Justiça Eleitoral e Militar não são tratados aqui)."""
    validos, _ = cart.numeros_no_texto(str(numero))
    if not validos:
        return None
    m = cart.CNJ.search(validos[0][0])
    j, tr = m[4], int(m[5])
    if j == "8" and 1 <= tr <= 27:
        uf = cart.UFS[tr - 1]
        return "tjdft" if uf == "DF" else f"tj{uf.lower()}"
    if j == "4" and 1 <= tr <= 6:
        return f"trf{tr}"
    if j == "5":
        return "tst" if tr == 0 else (f"trt{tr}" if 1 <= tr <= 24 else None)
    if j == "3":
        return "stj"
    return None


def _config_datajud():
    """(ligado, chave). Vale o config.json; sem a seção `fontes_externas.datajud` nele (instalação antiga),
    vale o config.exemplo.json (fonte ligada). A chave pública do CNJ não vai no repositório: vem de
    `config.json` (`chave`) ou da variável DATAJUD_CHAVE; sem ela não há consulta."""
    padrao = ((comum.load_json(comum.RAIZ / "config.exemplo.json", {}).get("fontes_externas") or {}).get("datajud")) or {}
    cfg = (comum.config().get("fontes_externas") or {}).get("datajud")
    if cfg is None:
        cfg = padrao
    if isinstance(cfg, dict):
        return bool(cfg.get("ativo")), cfg.get("chave") or os.environ.get("DATAJUD_CHAVE")
    return bool(cfg), os.environ.get("DATAJUD_CHAVE")


def _transporte_urllib(url, cabecalhos, corpo, timeout=40):
    req = urllib.request.Request(url, data=corpo, headers=cabecalhos, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


_ultima_datajud = [0.0]


def consultar_datajud(numero, *, transporte=None, ativo=None, chave=None, relogio=time.monotonic, dormir=time.sleep, alias=None):
    """Consulta o DataJud pelo número. Volta (resposta JSON | None, avisos); erro esperado vira aviso.

    `ativo`/`chave`: sobrepõem a configuração (`fontes_externas.datajud`); sem flag ligada ou sem chave, NÃO
    há chamada. `transporte(url, cabecalhos, corpo_bytes) -> (status, bytes)` é injetável (testes sem rede);
    `relogio`/`dormir` também. `alias` troca o índice (o padrão vem do número; "tst" consulta o TST com o mesmo número CNJ).
    A chave é a pública da wiki do CNJ e pode mudar sem aviso: por isso não vai no código."""
    onde = "capa/datajud"
    cfg_ativo, cfg_chave = _config_datajud()
    ativo = cfg_ativo if ativo is None else ativo
    chave = chave or cfg_chave
    if not ativo:
        return None, [aviso("info", "datajud_desativado", onde, "Fonte DataJud desligada (fontes_externas.datajud); nenhuma consulta feita.")]
    if not chave:
        return None, [aviso("atencao", "datajud_sem_chave", onde,
                            "DataJud ligado, mas sem a chave pública do CNJ (copie da wiki do DataJud para fontes_externas.datajud.chave).")]
    alias = alias or alias_datajud(numero)
    if not alias:
        return None, [aviso("info", "datajud_tribunal_sem_indice", onde, f"O DataJud não tem índice para o tribunal de {numero}.")]
    espera = DATAJUD_INTERVALO_S - (relogio() - _ultima_datajud[0])
    if espera > 0:
        dormir(espera)
    _ultima_datajud[0] = relogio()
    corpo = json.dumps({"query": {"match": {"numeroProcesso": _digitos(numero)}}}).encode()
    cabecalhos = {"Authorization": f"APIKey {chave}", "Content-Type": "application/json"}
    try:
        status, bruto = (transporte or _transporte_urllib)(DATAJUD_URL.format(alias=alias), cabecalhos, corpo)
    except (OSError, TimeoutError) as e:  # urllib.error.URLError é OSError
        return None, [aviso("atencao", "datajud_indisponivel", onde, f"O DataJud não respondeu ({type(e).__name__}); tente de novo mais tarde.")]
    if status in (401, 403):
        return None, [aviso("erro", "datajud_chave_recusada", onde, "O DataJud recusou a chave (o CNJ pode tê-la trocado; copie a atual da wiki).")]
    if status == 429:
        return None, [aviso("atencao", "datajud_limite", onde, "O DataJud pediu para reduzir o ritmo (limite de requisições); tente mais tarde.")]
    if status != 200:
        return None, [aviso("atencao", "datajud_indisponivel", onde, f"O DataJud respondeu com erro {status}.")]
    try:
        return json.loads(bruto), []
    except (ValueError, TypeError):
        return None, [aviso("atencao", "datajud_resposta_ilegivel", onde, "A resposta do DataJud não é um JSON válido.")]


# ---------------------------------------------------------------- graus no DataJud e o TST

def graus_do_datajud(dados, numero=None):
    """Graus em que o DataJud mostra o processo ("G1", "G2", "SUP", "JE", "TR"...), sem repetir."""
    fontes = _fontes_datajud(dados)
    if numero:
        fontes = [s for s in fontes if _digitos(s.get("numeroProcesso")) == _digitos(numero)]
    return sorted({s.get("grau") for s in fontes if s.get("grau")})


def indica_segundo_grau(dados, numero=None):
    """True se o DataJud mostra tramitação no 2º grau (G2) para o número."""
    return "G2" in graus_do_datajud(dados, numero)


def consultar_tst(numero, **kw):
    """O mesmo número CNJ no índice do TST do DataJud. Volta (dados | None, avisos). Só vale para processo da
    Justiça do Trabalho; o resto volta (None, []). `kw` vai para consultar_datajud (transporte, ativo, chave...).
    Quem recebe `dados` usa `no_tst` e `movimentos_do_tst`."""
    validos, _ = cart.numeros_no_texto(str(numero))
    m = cart.CNJ.search(validos[0][0]) if validos else None
    if not m or m[4] != "5":
        return None, []
    return consultar_datajud(numero, alias="tst", **kw)


def no_tst(dados, numero):
    """True se o índice do TST devolveu o processo (sem sigilo)."""
    return any(_digitos(s.get("numeroProcesso")) == _digitos(numero) and not s.get("nivelSigilo")
               for s in _fontes_datajud(dados))


def movimentos_do_tst(dados, numero):
    """Movimentos do TST no formato de ResultadoColeta: {"data": ISO, "texto", "grau": "TST", "chave"}.
    A chave leva a data com hora do DataJud e o código do movimento: estável entre rodadas."""
    saida = []
    for s in _fontes_datajud(dados):
        if _digitos(s.get("numeroProcesso")) != _digitos(numero) or s.get("nivelSigilo"):
            continue
        for m in s.get("movimentos") or []:
            if not isinstance(m, dict):
                continue
            texto = _nome(m.get("nome") or "")
            for c in m.get("complementosTabelados") or []:
                if isinstance(c, dict) and c.get("nome"):
                    texto += f" {_nome(c['nome'])}"
            data = _data(m.get("dataHora"))
            if data and texto.strip():
                saida.append({"data": data, "texto": texto.strip(), "grau": "TST",
                              "chave": f"tst|{m.get('dataHora')}|{m.get('codigo')}"})
    saida.sort(key=lambda m: m["data"])
    return saida
