"""Escritor DOCX do modelo A: o relatório em texto, exportado de um Google Doc (CONTRATOS.md, seção 5).

O documento tem o título (cliente), "Data-Base: DD/MM/AAAA", um quadro-resumo de 4 colunas (Nº DO PROCESSO |
ASSUNTO | MOMENTO ATUAL DO PROCESSO | ÚLTIMO ANDAMENTO) e uma tabela por processo: título mesclado
"PROCESSO Nº ... [ MOMENTO ATUAL ]", Assunto, Autor(es), Réu(s), Ajuizamento, Valor da Causa, Data de citação,
Juízo, Área do Direito, Matéria Principal e "Andamentos:" (texto corrido com as datas em negrito).
Vem do protótipo do spike S2 (`spikes/s2_docx/docx_atualizador.py`, mantido intacto), com as ressalvas do
relatório `docs/fase2/spikes/S2-docx.md` resolvidas.

API:
    gravar(molde, estado, destino, **opcoes) -> Resultado     contrato de CONTRATOS.md, seção 5
    atualizar(origem, destino, atualizacoes, data_base, **opcoes) -> Resultado    (baixo nível)
    gerar(destino, relatorio, estilo="a", **opcoes) -> Resultado                  (baixo nível, do zero)
    ler_estrutura(docx) -> dict            leitura dos blocos e do resumo (o leitor do WS-2 reaproveita)
    verificar_coerencia(docx) -> [str]     resumo x blocos x fecho x data-base (o WS-11 reaproveita)
    texto_do_evento(evento) -> str         cláusula do andamento (mesmas regras de relatorio.linha)
    separar_momento("X (Y)") -> ("X", "Y") momento canônico e qualificador entre parênteses
    criar_modelo(estilo, destino)          recria o modelo sanitizado (src/modelos/docx_a/criar_modelos.py)
    ensaio(origem, destino, data_base)     ciclo de teste numa cópia, para a conferência manual (linha de comando:
                                           python3 src/escritores/docx_a.py ler|ensaio|modelos ...)

`molde` é o `.docx` do cliente (atualização: uma CÓPIA é gravada em `destino`) ou `None` (cria do zero a partir do
modelo sanitizado `src/modelos/docx_a/modelo_<estilo>.docx`; estilos "a" e "compacto"). `estado` é o
EstadoRelatorio do contrato (cliente, data_base ISO, fichas, eventos aprovados, perfil, parametros).

Princípios (PLANO.md 3.3 e CONTRATOS.md 5):
- EDIÇÃO CIRÚRGICA DO PACOTE, como o planilha.py: só word/document.xml é reescrito (lxml); todas as outras partes do
  .zip (estilos, tema, mídia, comentários, cabeçalhos, rodapés) são copiadas byte a byte. Sem python-docx na
  gravação. Sem nenhuma mudança, o document.xml também sai idêntico byte a byte.
- SÓ ACRESCENTA no texto de andamentos: o que o advogado escreveu não é reescrito. Exceções mecânicas, nomeadas
  (campos que o sistema recalcula a cada ciclo): data da frase de fecho, "momento atual" (quadro-resumo e título do
  bloco), "último andamento" e "Data-Base". Se um humano alterou algum deles à mão e o sistema o troca, o resultado
  traz o aviso `edicao_manual_sobrescrita` (quando o valor anterior já divergia do último que o sistema gravou, o que
  se sabe por `textos_conhecidos`/`campos_conhecidos`; sem eles, só quando título e resumo já divergiam entre si).
- FRASE DE FECHO ("Em DD/MM/AAAA, sem atualizações.") só quando o processo NÃO teve andamento novo no ciclo (padrão
  `fecho_apos_novidade=False`, como na planilha da Fase 1 e no modelo de referência). Quando entra andamento novo,
  o fecho antigo sai e o texto termina na novidade. Reaplicar o mesmo estado sobre a própria saída (a Data-Base do
  arquivo já é a data-base pedida) não mexe no fecho: o processo sem fecho ali terminou numa novidade já gravada.
- O ORIGINAL NUNCA É SOBRESCRITO (destino != molde, destino não pode existir sem `sobrescrever_destino`).
- IDEMPOTENTE: gravar duas vezes o mesmo estado não duplica nada (`mudancas == []` na segunda).
- NADA SE PERDE EM SILÊNCIO: tudo que não deu para fazer vira aviso com `codigo` estável (lista na seção AVISOS).
  Erro esperado (molde ilegível) volta como aviso de nível "erro" e `gravado=False`, não como exceção; só erro de
  programação (destino igual ao molde, opção desconhecida) levanta exceção.

Resultado (CONTRATOS.md 5 + extras aditivos):
    destino, processos_atualizados, processos_novos, mudancas [{numero, campo, antes, depois}], avisos,
    ignorados [{numero, data, motivo}]            andamentos não gravados por já constarem no texto (não lista o evento
                                                  que já veio como "relatado" e consta: isso é rotina),
    textos_gravados {numero: texto}               texto de andamentos que ficou no arquivo (o coordenador guarda em
                                                  ficha["ultimo_texto_gravado"] e devolve em `textos_conhecidos`),
    campos_gravados {numero: {momento_atual, ultimo_andamento}}   (extra, ver docs/fase2/RFC-docx-campos-gravados.md),
    nao_encontrados [numero], gravado (bool).
`numero` é o da ficha (principal) em `gravar`; em `atualizar` é o primeiro número do título do bloco.

Opções (`gravar`/`atualizar`/`gerar`):
    fecho_apos_novidade=False   acrescenta o fecho também depois de andamento novo
    renovar_fecho_dos_demais=False   renova o fecho dos processos do arquivo que não vieram na lista
    textos_conhecidos={numero: texto}   texto de andamentos como o sistema o deixou no último ciclo (a `gravar` o
                                lê sozinha de ficha["ultimo_texto_gravado"]["texto"], se não vier)
    campos_conhecidos={numero: {...}}   `campos_gravados` do ciclo anterior (idem, de ficha["ultimo_texto_gravado"]
                                ["campos"]); alimenta o aviso `edicao_manual_sobrescrita`
    data_base_conhecida         Data-Base que o sistema gravou no ciclo anterior (ISO ou DD/MM/AAAA)
    limiar_duplicata=0.7, limiar_parecido=0.4    ver "Detecção de duplicata"
    estilo=None                 "a" | "compacto" (padrão: perfil["estilo_texto"]: a -> a, b -> compacto)
    sobrescrever_destino=False

Detecção de duplicata (heurística; limiares configuráveis, sem calibração com texto real: ver o piloto M5): o texto
de andamentos é separado em frases por marcadores de data: "Em DD/MM/AAAA", "Até", "No dia", "Na data de", e também
"Em DD/MM/AA", "Em DD/MM" (o ano vem da frase anterior ou da data-base) e "Em 18 de junho de 2026" (com ou sem
ano). Só vale a forma com inicial maiúscula ("em 10/10/2026" no meio da frase não é marcador) e, nas formas curtas,
só no começo de frase. Um andamento novo é IGNORADO se, na mesma data, o núcleo do texto (palavras sem acento, caixa
nem palavras-ponte) tem similaridade >= `limiar_duplicata` com uma frase existente; entre `limiar_parecido` e
`limiar_duplicata` também não entra, mas com aviso `possivel_duplicata_manual` (provável edição à mão); abaixo disso
entra. Erra para os dois lados; por isso sempre devolve `ignorados` e avisos para a revisão. Andamento escrito de
outro jeito ("18.06.2026", "dia 18") continua invisível para a checagem e pode repetir (ver a conferência manual).

AVISOS (campo `codigo`): molde_ilegivel, erro (nivel), controle_alteracoes_ligado, tem_comentarios, sem_data_base,
sem_resumo, processo_nao_encontrado, numero_em_varios_blocos, numero_vinculado_novo, sem_linha_no_resumo,
sem_andamentos, andamento_invalido, possivel_duplicata_manual, mesma_data, edicao_manual (o final do texto foi
alterado à mão; só acrescentou), edicao_manual_sobrescrita (campo mecânico trocado), revisao_no_trecho,
fecho_fora_do_fim, fecho_no_meio, fecho_acrescentado, momento_divergente, titulo_sem_momento, ja_existe, sem_modelo,
modelo_imperfeito, campo_sem_celula, celula_limpa, resumo_sem_modelo, processos_sem_atualizacao,
incoerencia_documento.

Limites conhecidos (avisados ou tratados de forma conservadora; detalhes em docs/fase2/spikes/S2-docx.md e na
conferência manual docs/fase2/conferencia-docx.md): controle de alterações/comentário no parágrafo de andamentos
(acrescenta no fim e avisa; as edições do sistema não saem como revisão), mesclagem vertical que cruza a linha de
andamentos, imagem dentro de bloco clonado, tabelas aninhadas, controles de conteúdo (`w:sdt`), negrito por estilo
nomeado (`rStyle`), fecho editado à mão ("..., sem atualizações, aguardando alvará."), número sem a pontuação CNJ.
Este módulo só foi exercitado com python-docx, lxml e LibreOffice com dados fictícios: NÃO foi aberto no Word nem no
Google Docs.

Dependências: lxml (execução). python-docx só em `criar_modelo` e nos testes.
"""
import copy
import datetime
import io
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

if not __package__:       # executado como script (python3 src/escritores/docx_a.py ...): põe src/ no caminho
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import ficha as fch  # noqa: E402

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
XML_NS = "http://www.w3.org/XML/1998/namespace"
PARTE_DOCUMENTO = "word/document.xml"
PASTA_MODELOS = Path(__file__).resolve().parent.parent / "modelos" / "docx_a"
ESTILOS = ("a", "compacto")
ESTILO_DO_PERFIL = {"a": "a", "b": "compacto", "compacto": "compacto"}   # perfil["estilo_texto"] = "a | b"

CNJ = re.compile(r"\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}")
DATA = r"\d{2}/\d{2}/\d{4}"
# "Em 18/09/2026, sem atualizações." (e variantes), no FIM do texto; tolerante a espaços e maiúsculas
FECHO = re.compile(r"(?:Em|Até)\s+(" + DATA + r")\s*,?\s*sem\s+(?:novas\s+)?"
                   r"(?:atualiza(?:ções|coes|ção|cao)|andamentos?|movimenta(?:ções|coes))\s*\.?\s*$", re.I)
MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
         "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
_MES = "janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro"
_FORMAS_DE_DATA = (
    r"\d{1,2}/\d{1,2}/\d{4}",                                       # 18/06/2026
    r"\d{1,2}/\d{1,2}/\d{2}(?![\d/])",                              # 18/06/26
    r"\d{1,2}º?\s+de\s+(?i:" + _MES + r")\s+de\s+\d{4}",            # 18 de junho de 2026
    r"\d{1,2}º?\s+de\s+(?i:" + _MES + r")(?!\s+de\s+\d)",           # 18 de junho
    r"\d{1,2}/\d{1,2}(?![\d/])",                                    # 18/06
)
# case-sensitive de propósito: "em 10/10/2026" no meio da frase não é início de andamento
INICIO_ANDAMENTO = re.compile(r"\b(Em|Até|No\s+dia|Na\s+data\s+de)\s+(" + "|".join(_FORMAS_DE_DATA) + r")\s*,?\s*")
DATA_BASE_RE = re.compile(r"(Data[-\s]*Base\s*:\s*)(" + DATA + ")", re.I)
COLCHETE = re.compile(r"\[(\s*)([^\]]*?)(\s*)\]")
QUALIFICADOR = re.compile(r"^(.*?)\s*\(([^()]*)\)\s*$")
ROTULOS = {"assunto": "assunto", "autor(es)": "autores", "autores": "autores", "autor": "autores",
           "reu(s)": "reus", "reus": "reus", "reu": "reus", "ajuizamento": "ajuizamento",
           "valor da causa": "valor_causa", "data de citacao": "data_citacao", "juizo": "juizo",
           "area do direito": "area", "materia principal": "materia", "andamentos": "andamentos"}
CAMPOS_FICHA_DO_BLOCO = ("assunto", "autores", "reus", "ajuizamento", "valor_causa", "data_citacao",
                         "juizo", "area", "materia", "andamentos")
ROTULO_DO_VINCULO = (("agravo", "agravo"), ("apenso", "apenso"), ("recurso", "recurso"),
                     ("reajuiz", "reajuizamento"), ("vinculad", "mesma_acao"))
TITULO_DO_VINCULO = {"agravo": "AGRAVO Nº", "apenso": "APENSO Nº", "recurso": "RECURSO Nº",
                     "reajuizamento": "REAJUIZAMENTO Nº", "mesma_acao": "PROCESSO VINCULADO Nº"}
# formatações do "run vizinho" que NÃO devem ser herdadas pelo texto novo (anotação do advogado em destaque etc.)
RPR_NAO_HERDAR = ("i", "iCs", "strike", "dstrike", "highlight", "u", "shd", "vertAlign", "bdr", "vanish")
ORDEM_RPR = ["rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike", "outline",
             "shadow", "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden", "color", "spacing",
             "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect", "bdr", "shd", "fitText",
             "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout", "specVanish", "oMath"]
TAGS_REVISAO = ("ins", "del", "moveFrom", "moveTo", "commentRangeStart", "commentRangeEnd", "commentReference")
PREFIXO_FECHO, SUFIXO_FECHO = "Em ", ", sem atualizações."
OPCOES_PADRAO = {"fecho_apos_novidade": False, "renovar_fecho_dos_demais": False, "textos_conhecidos": None,
                 "campos_conhecidos": None, "data_base_conhecida": None, "limiar_duplicata": 0.7,
                 "limiar_parecido": 0.4, "estilo": None, "sobrescrever_destino": False}


def w(tag):
    return f"{{{W_NS}}}{tag}"


def _opcoes(opcoes):
    """Opções do chamador sobre os padrões; opção desconhecida é erro de programação (typo não passa calado)."""
    desconhecidas = set(opcoes) - set(OPCOES_PADRAO)
    if desconhecidas:
        raise TypeError(f"opção desconhecida: {', '.join(sorted(desconhecidas))}")
    return {**OPCOES_PADRAO, **opcoes}


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


def _maior_data(datas):
    datas = [d for d in datas if d]
    return max(datas, key=_ordem_data) if datas else None


def _data_do_token(token, ano_anterior=None, data_base=None):
    """Data do marcador ('18/06/2026', '18/06/26', '18 de junho de 2026', '18/06', '18 de junho') -> 'DD/MM/AAAA'.
    Sem ano: usa o ano da frase anterior; sem frase anterior, o da data-base (e o ano anterior se passar dela)."""
    t = re.sub(r"\s+", " ", _sem_acento(token).lower()).replace("º", "")
    dia = mes = ano = None
    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})", t):
        dia, mes, ano = int(m[1]), int(m[2]), int(m[3])
        ano += 2000 if ano < 100 else 0
    elif m := re.fullmatch(r"(\d{1,2}) de (\w+) de (\d{4})", t):
        dia, mes, ano = int(m[1]), MESES.get(m[2]), int(m[3])
    elif m := re.fullmatch(r"(\d{1,2})/(\d{1,2})", t):
        dia, mes = int(m[1]), int(m[2])
    elif m := re.fullmatch(r"(\d{1,2}) de (\w+)", t):
        dia, mes = int(m[1]), MESES.get(m[2])
    if not dia or not mes:
        return None
    sem_ano = ano is None
    if sem_ano:
        ano = ano_anterior or (data_base.year if data_base else None)
        if ano is None:
            return None
    try:
        d = datetime.date(ano, mes, dia)
        if sem_ano and ano_anterior is None and data_base and d > data_base.date():
            d = datetime.date(ano - 1, mes, dia)
    except ValueError:
        return None
    return d.strftime("%d/%m/%Y")


def _dinheiro_br(valor):
    """'1234567.80' -> 'R$ 1.234.567,80' (texto já formatado passa direto)."""
    if valor in (None, ""):
        return ""
    if re.fullmatch(r"-?\d+(\.\d+)?", str(valor)):
        return fch.dinheiro_br(f"{float(valor):.2f}")
    return str(valor)


def _ajustar_inicio(texto):
    """'O juiz proferiu...' -> 'o juiz proferiu...' (cláusula depois de 'Em DATA, '), mantém siglas; garante ponto final."""
    t = (texto or "").strip()
    if not t:
        return t
    primeira = t.split()[0].rstrip(",.;:")
    if t[0].isupper() and not (len(primeira) > 1 and primeira.isupper()):
        t = t[0].lower() + t[1:]
    return t if t[-1] in ".!?" else t + "."


def separar_momento(texto):
    """'CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)' -> ('CUMPRIMENTO DE SENTENÇA', 'HONORÁRIOS SUSPENSOS')."""
    t = " ".join(str(texto or "").split())
    m = QUALIFICADOR.match(t)
    if m and m.group(1):
        return m.group(1).strip(), (m.group(2).strip() or None)
    return t, None


def _momento_texto(canonico, qualificador=None):
    canonico, qualificador = (canonico or "").strip().upper(), (qualificador or "").strip().upper()
    return f"{canonico} ({qualificador})" if canonico and qualificador else canonico


def _momento_do_proc(proc):
    """Texto do momento de um processo novo: canônico + qualificador ('X (Y)'), em caixa alta."""
    canonico, qualificador = separar_momento(proc.get("momento_atual"))
    return _momento_texto(canonico, proc.get("momento_qualificador") or qualificador)


def _mesmo_momento(texto_no_arquivo, canonico, qualificador):
    """O momento escrito no arquivo já é o novo? Só o canônico basta quando o novo não traz qualificador
    (preserva o que o advogado acrescentou entre parênteses)."""
    c, q = separar_momento(texto_no_arquivo)
    return _chave(c) == _chave(canonico) and (not qualificador or _chave(q or "") == _chave(qualificador))


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

def _comeco_de_frase(texto, pos):
    anterior = texto[:pos].rstrip()
    return not anterior or anterior[-1] in ".!?;:)\"”"


def _parse_andamentos(texto, data_base=None):
    """[{'data' (DD/MM/AAAA), 'texto', 'inicio', 'ini_data', 'fim_data', 'fecho'}]; o que vem antes da primeira data
    fica fora. `data_base` (DD/MM/AAAA) serve para completar o ano das formas curtas ('Em 18/06')."""
    base = _ordem_data(data_base) if _data_br(data_base) else None
    marcas, ano_anterior = [], None
    for m in INICIO_ANDAMENTO.finditer(texto):
        token = m.group(2)
        if not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", token) and not _comeco_de_frase(texto, m.start()):
            continue                              # forma curta no meio da frase ("Em 5/6 dos casos"): não é marcador
        data = _data_do_token(token, ano_anterior, base)
        if data is None:
            continue
        ano_anterior = int(data[-4:])
        marcas.append((m, data))
    saida = []
    for i, (m, data) in enumerate(marcas):
        fim = marcas[i + 1][0].start() if i + 1 < len(marcas) else len(texto)
        segmento = texto[m.start():fim].strip()
        saida.append({"data": data, "texto": texto[m.end():fim].strip(), "inicio": m.start(),
                      "ini_data": m.start(2), "fim_data": m.end(2), "fecho": bool(FECHO.fullmatch(segmento))})
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


def _achar_fecho(texto):
    return FECHO.search(texto)


def _pedacos_do_texto(texto):
    """Texto corrido -> [(trecho, negrito)] com a data de cada marcador em negrito (o resto, verbatim)."""
    pedacos, cursor = [], 0
    for a in _parse_andamentos(texto):
        if a["ini_data"] > cursor:
            pedacos.append((texto[cursor:a["ini_data"]], False))
        pedacos.append((texto[a["ini_data"]:a["fim_data"]], True))
        cursor = a["fim_data"]
    if cursor < len(texto):
        pedacos.append((texto[cursor:], False))
    return pedacos


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
        if self.body is None:
            raise ValueError("word/document.xml sem w:body")

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
            if CNJ.search(_texto_linha(linhas[0])) and re.search(
                    r"PROCESSO|AGRAVO|APENSO|RECURSO|REAJUIZ|VINCULAD", _sem_acento(_texto_linha(linhas[0])).upper()):
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

    def par_cliente(self):
        for p in self.paragrafos_topo():
            t = _texto_par(p).strip()
            if t and not DATA_BASE_RE.search(t):
                return p
        return None

    def cliente(self):
        p = self.par_cliente()
        return _texto_par(p).strip() if p is not None else None


# ------------------------------------------------------------------ avisos, resultado e contexto

def _novo_resultado(destino):
    return {"destino": Path(destino), "gravado": False, "processos_atualizados": [], "processos_novos": [],
            "ignorados": [], "mudancas": [], "textos_gravados": {}, "campos_gravados": {}, "nao_encontrados": [],
            "avisos": []}


def _aviso(res, nivel, onde, codigo, mensagem, candidatos=None):
    res["avisos"].append({"nivel": nivel, "codigo": codigo, "onde": onde, "mensagem": mensagem,
                          "candidatos": candidatos or []})


class _Ctx:
    """Tudo que as etapas de uma gravação compartilham."""

    def __init__(self, doc, data_base, opc, res, chaves=None):
        self.doc, self.data_base, self.opc, self.res = doc, data_base, opc, res
        self.chaves = chaves or {}                    # qualquer número do processo -> chave de saída (nº da ficha)
        self.conhecidos = opc.get("textos_conhecidos") or {}
        self.campos_conhecidos = opc.get("campos_conhecidos") or {}
        self.data_base_anterior = None                # Data-Base que o arquivo tinha ao ser aberto
        self.data_base_conhecida = _data_br(opc.get("data_base_conhecida"))

    def chave(self, bloco):
        return next((self.chaves[n] for n in bloco.numeros if n in self.chaves), bloco.numeros[0])

    def aviso(self, nivel, onde, codigo, mensagem, candidatos=None):
        _aviso(self.res, nivel, onde, codigo, mensagem, candidatos)

    def mudanca(self, numero, campo, antes, depois):
        res = self.res
        res["mudancas"].append({"numero": numero, "campo": campo, "antes": antes, "depois": depois})
        if (numero and numero not in res["processos_atualizados"] and numero not in res["processos_novos"]
                and campo != "data_base"):
            res["processos_atualizados"].append(numero)

    @property
    def reaplicacao(self):
        """O arquivo já está na data-base pedida: é a mesma rodada reaplicada sobre a própria saída."""
        return self.data_base_anterior is not None and self.data_base_anterior == self.data_base


# ------------------------------------------------------------------ leitura

def _abrir(docx):
    with zipfile.ZipFile(docx) as z:
        return _Documento(z.read(PARTE_DOCUMENTO))


def _vinculados_do_titulo(titulo, numeros):
    """[{'numero', 'tipo'}] dos números depois do primeiro, pelo rótulo escrito antes de cada um (tipo None se não houver)."""
    saida, fim_anterior = [], (titulo.find(numeros[0]) + len(numeros[0]) if numeros else 0)
    for n in numeros[1:]:
        i = titulo.find(n)
        rotulo = _sem_acento(titulo[fim_anterior:i]).lower()
        saida.append({"numero": n, "tipo": next((t for k, t in ROTULO_DO_VINCULO if k in rotulo), None)})
        fim_anterior = i + len(n)
    return saida


def ler_estrutura(docx):
    """{'cliente', 'data_base', 'resumo': [...], 'processos': [...], 'avisos': [...]} do .docx (nada é gravado).
    Cada processo traz números, vinculados (com tipo, lido do título), momento (inteiro, com qualificador),
    momento_atual/qualificador separados, os campos do bloco, o texto de andamentos, os andamentos
    ({data, texto, data_em_negrito}) e o fecho."""
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
        momento, qualificador = separar_momento(b.momento or "")
        item = {"numeros": b.numeros, "vinculados": _vinculados_do_titulo(b.titulo, b.numeros),
                "titulo": b.titulo.strip(), "momento_atual": b.momento, "momento": momento or None,
                "qualificador": qualificador}
        for campo in CAMPOS_FICHA_DO_BLOCO[:-1]:
            item[campo] = _texto_celula(b.campos[campo]).strip() if campo in b.campos else None
        item["andamentos_texto"] = b.andamentos_texto()
        andamentos, fecho = [], None
        pars = [p for p in _filhos(b.campos["andamentos"], "p") if _texto_par(p).strip()] if "andamentos" in b.campos else []
        for p in pars:
            tp = _texto_par(p)
            for a in _parse_andamentos(tp, est["data_base"]):
                negr = _formato_no_trecho(p, a["ini_data"], a["fim_data"])
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

def _filtrar_novos(ctx, numero, existentes, andamentos):
    """Separa o que de fato é novo do que já consta (mesma data + mesmo núcleo). -> (aceitos, quantos repetidos)."""
    aceitos, repetidos = [], 0
    lim_dup, lim_par = ctx.opc["limiar_duplicata"], ctx.opc["limiar_parecido"]
    for a in andamentos or []:
        data = _data_br(a.get("data"))
        clausula = _ajustar_inicio(a.get("texto", ""))
        if not data or not clausula:
            ctx.aviso("erro", numero, "andamento_invalido", f"andamento sem data válida ou sem texto: {a!r}")
            continue
        mesma_data = [e for e in existentes if e["data"] == data]
        sim = max([_similaridade(clausula, e["texto"]) for e in mesma_data] or [0.0])
        if sim >= lim_dup or any(_chave(clausula) == _chave(e["texto"]) for e in mesma_data):
            repetidos += 1
            if not a.get("relatado"):         # evento já relatado antes constar no texto é rotina, não vale listar
                ctx.res["ignorados"].append({"numero": numero, "data": data, "motivo": "andamento já presente"})
            continue
        if any(x["data"] == data and _similaridade(clausula, x["texto"]) >= lim_dup for x in aceitos):
            repetidos += 1
            ctx.res["ignorados"].append({"numero": numero, "data": data, "motivo": "repetido na própria atualização"})
            continue
        if mesma_data:
            if sim >= lim_par:
                ctx.aviso("atencao", numero, "possivel_duplicata_manual",
                          f"já há texto parecido em {data} (provável edição à mão): não acrescentado; conferir",
                          [e["texto"][:120] for e in mesma_data])
                ctx.res["ignorados"].append({"numero": numero, "data": data, "motivo": "parecido com texto existente"})
                repetidos += 1
                continue
            ctx.aviso("info", numero, "mesma_data", f"já existe outro andamento em {data}; o novo foi acrescentado")
        aceitos.append({"data": data, "texto": clausula})
    aceitos.sort(key=lambda a: _ordem_data(a["data"]))
    return aceitos, repetidos


def _atualizar_andamentos(ctx, bloco, upd):
    numero = ctx.chave(bloco)
    par = bloco.andamentos_par()
    if par is None:
        ctx.aviso("atencao", numero, "sem_andamentos", "bloco sem a linha 'Andamentos:': nada acrescentado")
        return []
    data_base, opc = ctx.data_base, ctx.opc
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
    corpo_celula = _plano(bloco.andamentos_texto())
    if fecho:
        cf = _achar_fecho(corpo_celula)
        corpo_celula = corpo_celula[:cf.start()] if cf else corpo_celula
    existentes = [a for a in _parse_andamentos(corpo_celula, data_base) if not a["fecho"]]
    if not fecho and any(a["fecho"] for a in _parse_andamentos(texto, data_base)):
        ctx.aviso("atencao", numero, "fecho_no_meio",
                  "há uma frase 'sem atualizações' que não é a última do texto (texto acrescentado depois dela): mantida")
    if fecho_longe:
        ctx.aviso("atencao", numero, "fecho_fora_do_fim",
                  "a frase de fecho está num parágrafo anterior ao último (texto do advogado depois dela): "
                  "nunca é apagada; sem novidade só a data é renovada ali; com novidade o texto novo vai no último parágrafo")

    # 1) o que de fato é novo
    aceitos, _repetidos = _filtrar_novos(ctx, numero, existentes, upd.get("andamentos"))

    # 2) edição manual recente? (final do texto diverge do último estado conhecido)
    conhecido = upd.get("texto_conhecido")
    if conhecido is not None and aceitos:
        cf2 = _achar_fecho(_plano(conhecido))
        cauda = _chave(_plano(conhecido)[:cf2.start()] if cf2 else conhecido)[-120:]
        if cauda and not _chave(corpo_celula).endswith(cauda):
            ctx.aviso("atencao", numero, "edicao_manual",
                      "o final do texto de andamentos foi alterado à mão desde o último ciclo: só foi acrescentado, "
                      "nada reescrito; conferir o resultado")
    # o fecho que está no arquivo foi mexido à mão? (comparado com o fecho do último texto gravado)
    fecho_manual = False
    if conhecido is not None and (fecho or fecho_longe):
        atual_f = fecho or fecho_longe[1]
        antigo_f = _achar_fecho(_plano(conhecido))
        fecho_manual = antigo_f is None or antigo_f.group(1) != atual_f.group(1)

    # 3) formatos: do próprio parágrafo, fora do fecho
    unidades = list(_unidades(par))
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
    prefixo = texto[fecho.start():fecho.start(1)] if fecho else PREFIXO_FECHO
    sufixo = texto[fecho.end(1):fecho.end()].rstrip() if fecho else SUFIXO_FECHO
    if normal is None and negrito is None and ref is None:
        rotulo = bloco.rotulos.get("andamentos")
        normal = _rpr_de(_unidades(rotulo.find(w("p")))[0]) if rotulo is not None and _unidades(rotulo.find(w("p"))) else None
    modelo_normal = _rpr_modelo(normal if normal is not None else (ref if ref is not None else negrito), False)
    modelo_negrito = _rpr_modelo(negrito if negrito is not None else modelo_normal, True, herdar_destaques=negrito is not None)
    fecho_normal = _rpr_modelo(rpr_fecho_txt if rpr_fecho_txt is not None else modelo_normal, False, herdar_destaques=False)
    fecho_negrito = _rpr_modelo(rpr_fecho_data if rpr_fecho_data is not None else modelo_negrito, True)
    antes_fecho = fecho.group(0).strip() if fecho else None
    fecho_novo = f"{prefixo}{data_base}{sufixo}".strip()

    def anexar(pedacos):
        for t, neg in _juntar_pedacos(pedacos):
            par.append(_novo_run(t, modelo_negrito if neg else modelo_normal))

    def anexar_fecho():
        par.append(_novo_run(prefixo, fecho_normal))
        par.append(_novo_run(data_base, fecho_negrito))
        par.append(_novo_run(sufixo, fecho_normal))

    def avisar_fecho_manual():
        if fecho_manual:
            ctx.aviso("atencao", numero, "edicao_manual_sobrescrita",
                      "a frase de fecho tinha sido alterada à mão desde o último ciclo; foi trocada pela do sistema",
                      [antes_fecho or (fecho_longe[1].group(0).strip() if fecho_longe else "")])

    # 4) gravação
    if not aceitos:
        if fecho_longe:
            p_longe, m_longe = fecho_longe
            if m_longe.group(1) != data_base and not _tem_revisao(p_longe):
                _substituir(p_longe, m_longe.start(1), m_longe.end(1), data_base)
                avisar_fecho_manual()
                ctx.mudanca(numero, "andamentos_fecho", m_longe.group(0).strip(),
                            m_longe.group(0).strip().replace(m_longe.group(1), data_base))
        elif fecho:
            if fecho.group(1) != data_base:
                avisar_fecho_manual()
                if revisao:
                    ctx.aviso("atencao", numero, "revisao_no_trecho",
                              "controle de alterações/comentário no trecho final: fecho antigo mantido e novo acrescentado")
                    par.append(_novo_run(" ", modelo_normal))
                    anexar_fecho()
                else:
                    _substituir(par, fecho.start(1), fecho.end(1), data_base)
                ctx.mudanca(numero, "andamentos_fecho", antes_fecho, fecho_novo)
        elif not ctx.reaplicacao:
            if texto.strip() and not texto.endswith((" ", "\n")):
                par.append(_novo_run(" ", modelo_normal))
            anexar_fecho()
            ctx.mudanca(numero, "andamentos_fecho", None, fecho_novo)
            ctx.aviso("info", numero, "fecho_acrescentado", "o texto não tinha frase de fecho: acrescentada")
    else:
        if fecho and not revisao:
            avisar_fecho_manual()
            _substituir(par, fecho.start(), fecho.end(), "")
            sobra = _texto_par(par)
            if sobra != sobra.rstrip():          # tira o espaço que separava o fecho
                _substituir(par, len(sobra.rstrip()), len(sobra), "")
        elif fecho and revisao:
            ctx.aviso("atencao", numero, "revisao_no_trecho",
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
        ctx.mudanca(numero, "andamentos", None, novo_txt)
        if fecho and not revisao:
            ctx.mudanca(numero, "andamentos_fecho", antes_fecho, fecho_novo if opc["fecho_apos_novidade"] else None)
    return aceitos


def _atualizar_resumo_e_titulo(ctx, resumo, bloco, linha, upd, aceitos):
    numero = ctx.chave(bloco)
    # momento atual: quadro-resumo e título do bloco andam juntos
    canonico, qualificador = separar_momento(upd.get("momento_atual"))
    qualificador = qualificador or (upd.get("momento_qualificador") or None)
    novo = _momento_texto(canonico, qualificador)
    if novo:
        titulo = _filhos(_filhos(bloco.linhas[0], "tc")[0], "p")
        par_t = next((p for p in titulo if COLCHETE.search(_texto_par(p))), None)
        antes_t = bloco.momento
        celula = resumo.celula(linha, "momento") if resumo is not None and linha is not None else None
        antes_r = _texto_celula(celula).strip() if celula is not None else None
        divergia = antes_t is not None and antes_r is not None and _chave(antes_t) != _chave(antes_r)
        conhecido = (ctx.campos_conhecidos.get(numero) or {}).get("momento_atual")
        trocou_titulo = trocou_resumo = False
        if par_t is not None and (antes_t is None or not _mesmo_momento(antes_t, canonico, qualificador)):
            m = COLCHETE.search(_texto_par(par_t))
            if m.group(2):
                _substituir(par_t, m.start(2), m.end(2), novo)
            else:                                   # '[ ]' vazio: insere dentro do colchete
                par_t.append(_novo_run(novo, _rpr_modelo(_rpr_no_offset(par_t, m.start()), True)))
            trocou_titulo = True
        elif par_t is None:
            ctx.aviso("atencao", numero, "titulo_sem_momento", "título do bloco sem '[ MOMENTO ]': não alterado")
        if celula is not None and (not antes_r or not _mesmo_momento(antes_r, canonico, qualificador)):
            _definir_texto_celula(celula, novo)
            trocou_resumo = True
        if trocou_titulo:
            ctx.mudanca(numero, "momento_atual", antes_t, novo)
        elif trocou_resumo:
            ctx.mudanca(numero, "momento_atual", antes_r, novo)
        trocado = (antes_t if trocou_titulo else None) or (antes_r if trocou_resumo else None)
        if (trocou_titulo or trocou_resumo) and trocado and (
                divergia or (conhecido and _chave(trocado) != _chave(conhecido))):
            ctx.aviso("atencao", numero, "edicao_manual_sobrescrita",
                      "o 'momento atual' do arquivo " + (
                          "estava diferente no título e no quadro-resumo" if divergia else
                          "tinha sido alterado à mão desde o último ciclo") + f" ('{trocado}'); foi trocado por '{novo}'",
                      [x for x in (antes_t, antes_r) if x])
    # último andamento: nunca recua (vale a maior data entre o valor da ficha, os andamentos novos e o que está lá)
    celula = resumo.celula(linha, "ultimo") if resumo is not None and linha is not None else None
    if celula is not None:
        atual = _texto_celula(celula).strip()
        candidatos = [_data_br(upd.get("ultimo_andamento"))] + [a["data"] for a in aceitos] + [_data_br(atual)]
        novo_u = _maior_data(candidatos)
        if novo_u and novo_u != atual:
            conhecido = (ctx.campos_conhecidos.get(numero) or {}).get("ultimo_andamento")
            if conhecido and atual and _chave(conhecido) != _chave(atual):
                ctx.aviso("atencao", numero, "edicao_manual_sobrescrita",
                          f"o 'último andamento' do arquivo tinha sido alterado à mão desde o último ciclo ('{atual}'); "
                          f"foi trocado por '{novo_u}'")
            _definir_texto_celula(celula, novo_u)
            ctx.mudanca(numero, "ultimo_andamento", atual, novo_u)


def _atualizar_data_base(ctx):
    doc = ctx.doc
    par, m = doc.par_data_base()
    if par is None:
        ctx.aviso("atencao", "documento", "sem_data_base", "parágrafo 'Data-Base: DD/MM/AAAA' não encontrado")
        return
    ctx.data_base_anterior = m.group(2)
    if m.group(2) != ctx.data_base:
        if ctx.data_base_conhecida and ctx.data_base_conhecida != m.group(2):
            ctx.aviso("atencao", "documento", "edicao_manual_sobrescrita",
                      f"a Data-Base do arquivo ({m.group(2)}) não era a que o sistema gravou no último ciclo "
                      f"({ctx.data_base_conhecida}); foi trocada por {ctx.data_base}")
        _substituir(par, m.start(2), m.end(2), ctx.data_base)
        ctx.mudanca(None, "data_base", m.group(2), ctx.data_base)


# ------------------------------------------------------------------ processo novo (clona bloco-modelo e linha do resumo)

def _titulo_processo(proc):
    numeros = proc.get("numeros") or [proc.get("numero")]
    tipos = proc.get("tipos") or []
    partes = [f"PROCESSO Nº {numeros[0]}"]
    for i, n in enumerate(numeros[1:]):
        partes.append(f"{TITULO_DO_VINCULO.get(tipos[i] if i < len(tipos) else '', 'PROCESSO VINCULADO Nº')} {n}")
    momento = _momento_do_proc(proc)
    return " / ".join(partes) + (f" [ {momento} ]" if momento else "")


def _linhas_numero_resumo(proc):
    numeros = proc.get("numeros") or [proc.get("numero")]
    tipos = proc.get("tipos") or []
    return [numeros[0]] + [f"{(tipos[i] if i < len(tipos) and tipos[i] else 'vinculado').replace('_', ' ').capitalize()}: {n}"
                           for i, n in enumerate(numeros[1:])]


def _texto_campos(proc):
    return {"assunto": proc.get("assunto") or "-", "autores": proc.get("autores") or "-",
            "reus": proc.get("reus") or "-", "ajuizamento": _data_br(proc.get("ajuizamento")) or proc.get("ajuizamento") or "-",
            "valor_causa": _dinheiro_br(proc.get("valor_causa")) or "-",
            "data_citacao": _data_br(proc.get("data_citacao")) or proc.get("data_citacao") or "-",
            "juizo": proc.get("juizo") or "-", "area": proc.get("area") or "-", "materia": proc.get("materia") or "-"}


def _sem_fecho(texto):
    texto = texto.rstrip()
    f = _achar_fecho(_plano(texto))
    return texto[:f.start()].rstrip() if f else texto


def _pedacos_novo(ctx, proc, prefixo=PREFIXO_FECHO, sufixo=SUFIXO_FECHO):
    """Pedaços [(texto, negrito)] do texto de andamentos de um processo novo: histórico migrado (linha de base, com as
    datas em negrito), andamentos novos que ainda não constam nele e, se não houve novidade, o fecho."""
    numero = (proc.get("numeros") or [proc.get("numero")])[0]
    historico = _sem_fecho(proc.get("historico") or "")
    pedacos = _pedacos_do_texto(historico) if historico else []
    existentes = [a for a in _parse_andamentos(historico, ctx.data_base) if not a["fecho"]]
    aceitos, _ = _filtrar_novos(ctx, numero, existentes, proc.get("andamentos"))
    for a in aceitos:
        if pedacos:
            pedacos.append((" ", False))
        pedacos += _pedacos_andamento(a["data"], a["texto"])
    if not aceitos or ctx.opc["fecho_apos_novidade"]:
        if pedacos:
            pedacos.append((" ", False))
        pedacos += [(prefixo, False), (ctx.data_base, True), (sufixo, False)]
    datas = [a["data"] for a in existentes] + [a["data"] for a in aceitos]
    return pedacos, _maior_data(datas + [_data_br(proc.get("ultimo_andamento"))])


def _preencher_andamentos_novo(ctx, bloco, proc):
    """Andamentos de um processo novo, com os formatos do bloco clonado. Devolve a data do último andamento."""
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
    prefixo = texto[fecho.start():fecho.start(1)] if fecho else PREFIXO_FECHO
    sufixo = texto[fecho.end(1):fecho.end()].rstrip() if fecho else SUFIXO_FECHO
    for p in _filhos(cel, "p"):
        if p is not par:
            cel.remove(p)
    for filho in list(par):
        if filho.tag != w("pPr"):
            par.remove(filho)
    pedacos, ultimo = _pedacos_novo(ctx, proc, prefixo, sufixo)
    for t, neg in _juntar_pedacos(pedacos):
        par.append(_novo_run(t, negrito if neg else normal))
    return ultimo


def _escolher_modelo(blocos):
    """Último bloco 'limpo': todos os campos mapeados, sem mesclagem vertical, imagem, revisão ou texto solto."""
    def limpo(b):
        return (all(c in b.campos for c in CAMPOS_FICHA_DO_BLOCO) and not b.tem_vmerge() and not b.tem_imagem()
                and not _tem_revisao(b.tbl) and not b.nao_mapeadas())
    bons = [b for b in blocos if limpo(b)]
    return (bons[-1], True) if bons else ((blocos[-1], False) if blocos else (None, False))


_ETIQUETAS_SOLTAS = ("bookmarkStart", "bookmarkEnd", "commentRangeStart", "commentRangeEnd", "commentReference")


def _sem_marcas_soltas(el):
    for tag in _ETIQUETAS_SOLTAS:
        for x in list(el.iter(w(tag))):
            x.getparent().remove(x)


class _Insersor:
    """Insere processos novos no fim do documento (bloco clonado + linha do resumo), sem reler o documento a cada
    inserção (200 processos novos: O(n))."""

    def __init__(self, ctx, modelo=None, modelo_linha=None):
        self.ctx = ctx
        doc = ctx.doc
        blocos = doc.blocos()
        self.resumo = doc.resumo()
        self.existentes = {n for b in blocos for n in b.numeros}
        self.ultimo = blocos[-1].tbl if blocos else None
        if modelo is not None:
            self.modelo, self.modelo_limpo = modelo, True
        else:
            self.modelo, self.modelo_limpo = _escolher_modelo(blocos)
        linhas = self.resumo.dados() if self.resumo is not None else []
        self.linha_modelo = modelo_linha if modelo_linha is not None else (linhas[-1][0] if linhas else None)
        self.ultima_linha = linhas[-1][0] if linhas else (self.resumo.linhas[self.resumo.cabecalho] if self.resumo is not None else None)

    def inserir(self, proc):
        ctx = self.ctx
        numeros = proc.get("numeros") or [proc.get("numero")]
        proc = dict(proc, numeros=numeros)
        repetidos = [n for n in numeros if n in self.existentes]
        if repetidos:
            ctx.aviso("info", numeros[0], "ja_existe", "processo já está no documento: não duplicado", repetidos)
            ctx.res["ignorados"].append({"numero": numeros[0], "data": None, "motivo": "processo já existe"})
            return
        if self.modelo is None:
            pedacos, ultimo_andamento = _pedacos_novo(ctx, proc)
            tbl = _el(_bloco_xml(_Estilo("a"), proc, pedacos))
            ctx.aviso("info", numeros[0], "sem_modelo", "documento sem bloco de processo: bloco construído do zero")
        else:
            if not self.modelo_limpo:
                ctx.aviso("atencao", numeros[0], "modelo_imperfeito",
                          "nenhum bloco 'limpo' para clonar (mesclagem vertical, imagem ou revisão): usado o último; conferir")
            tbl, ultimo_andamento = self._clonar(proc)
        self._colocar_bloco(tbl)
        self._inserir_linha(proc, ultimo_andamento)
        self.existentes.update(numeros)
        ctx.res["processos_novos"].append(numeros[0])
        ctx.mudanca(numeros[0], "processo", None, "novo")

    def _clonar(self, proc):
        ctx = self.ctx
        tbl = copy.deepcopy(self.modelo.tbl)
        _sem_marcas_soltas(tbl)
        b = _Bloco(tbl)
        _definir_texto_celula(_filhos(b.linhas[0], "tc")[0], _titulo_processo(proc), unico=True)
        for campo, texto in _texto_campos(proc).items():
            if campo in b.campos:
                rpr = None
                rot = b.rotulos[campo]
                if rot is not None and _unidades(_filhos(rot, "p")[0]):
                    rpr = _rpr_modelo(_rpr_de(_unidades(_filhos(rot, "p")[0])[0]), False)
                _definir_texto_celula(b.campos[campo], texto, rpr, unico=True)
            else:
                ctx.aviso("atencao", proc["numeros"][0], "campo_sem_celula", f"o bloco-modelo não tem a linha '{campo}'")
        for tc in b.nao_mapeadas():                   # texto solto do modelo não pode virar dado do processo novo
            _definir_texto_celula(tc, "", unico=False)
            ctx.aviso("atencao", proc["numeros"][0], "celula_limpa",
                      "célula do modelo fora do padrão foi esvaziada no clone")
        ultimo = _preencher_andamentos_novo(ctx, b, proc) if "andamentos" in b.campos else None
        return tbl, ultimo

    def _colocar_bloco(self, tbl):
        doc = self.ctx.doc
        if self.ultimo is None:
            ancora = self.resumo.tbl if self.resumo is not None else (doc.body[-2] if len(doc.body) > 1 else None)
            pos = list(doc.body).index(ancora) + 1 if ancora is not None else max(len(doc.body) - 1, 0)
            doc.body.insert(pos, _el(_par_vazio_xml(_Estilo("a"))))
            doc.body.insert(pos + 1, tbl)
            doc.body.insert(pos + 2, _el(_par_vazio_xml(_Estilo("a"))))
        else:
            seguinte = self.ultimo.getnext()
            if seguinte is not None and seguinte.tag == w("p") and not _texto_par(seguinte).strip():
                seguinte.addnext(tbl)
                tbl.addnext(copy.deepcopy(seguinte))
            else:
                self.ultimo.addnext(tbl)
                self.ultimo.addnext(_el(_par_vazio_xml(_Estilo("a"))))
        self.ultimo = tbl

    def _inserir_linha(self, proc, ultimo_andamento):
        ctx, resumo = self.ctx, self.resumo
        if resumo is None:
            return
        if self.linha_modelo is not None:
            nova = copy.deepcopy(self.linha_modelo)
        else:
            nova = copy.deepcopy(resumo.linhas[resumo.cabecalho])
            for el in nova.iter(w("tblHeader")):
                el.getparent().remove(el)
            ctx.aviso("atencao", proc["numeros"][0], "resumo_sem_modelo",
                      "quadro-resumo sem linha de dados: linha criada a partir do cabeçalho")
        _sem_marcas_soltas(nova)
        cels = _filhos(nova, "tc")
        valores = {"assunto": proc.get("assunto") or "-", "momento": _momento_do_proc(proc),
                   "ultimo": ultimo_andamento or "-"}
        if resumo.col["numero"] is not None:
            _definir_paragrafos_celula(cels[resumo.col["numero"]], _linhas_numero_resumo(proc))
        for chave, texto in valores.items():
            i = resumo.col[chave]
            if i is not None and i < len(cels):
                _definir_texto_celula(cels[i], texto, unico=True)
        self.ultima_linha.addnext(nova)
        self.ultima_linha = nova


# ------------------------------------------------------------------ construção do XML (modelo sanitizado e reserva)

class _Estilo:
    """Layout de um estilo do modelo: 'a' (o do modelo de referência) ou 'compacto' (fonte menor, três pares
    rótulo/valor por linha, margens estreitas)."""

    def __init__(self, nome):
        if nome not in ESTILOS:
            raise ValueError(f"estilo desconhecido: {nome!r} (use {', '.join(ESTILOS)})")
        self.nome = nome
        compacto = nome == "compacto"
        self.tam, self.tam_resumo, self.tam_cliente = (18, 16, 24) if compacto else (22, 18, 28)
        self.margem = 1134 if compacto else 1440                      # laterais, em twips (A4: 11906 de largura)
        self.mar_v, self.mar_h = (30, 70) if compacto else (60, 100)
        self.cor_borda, self.esp_borda = ("7F7F7F", 4) if compacto else ("000000", 4)
        self.fill_titulo, self.fill_rotulo, self.fill_cab = ("E7E6E6", "F5F5F5", "E7E6E6") if compacto else ("D9D9D9", "F3F3F3", "D9D9D9")
        self.grade = [1300, 1700, 1500, 1700, 1500, 1938] if compacto else [1900, 2600, 1900, 2626]
        self.larg_resumo = [2400, 2900, 2638, 1700] if compacto else [2700, 2150, 2550, 1626]

    def rpr(self, negrito=False, tam=None):
        b = '<w:b w:val="1"/>' if negrito else ""
        t = tam or self.tam
        return (f'<w:rPr><w:rFonts w:ascii="Arial" w:cs="Arial" w:eastAsia="Arial" w:hAnsi="Arial"/>{b}'
                f'<w:sz w:val="{t}"/><w:szCs w:val="{t}"/></w:rPr>')

    def run(self, texto, negrito=False, tam=None):
        return f'<w:r>{self.rpr(negrito, tam)}<w:t xml:space="preserve">{escape(texto)}</w:t></w:r>'

    def par(self, runs="", jc="left"):
        return (f'<w:p><w:pPr><w:spacing w:after="0" w:before="0" w:line="240" w:lineRule="auto"/>'
                f'<w:jc w:val="{jc}"/></w:pPr>{runs}</w:p>')

    def borda(self):
        return "".join(f'<w:{l} w:val="single" w:sz="{self.esp_borda}" w:space="0" w:color="{self.cor_borda}"/>'
                       for l in ("top", "left", "bottom", "right"))

    def tc(self, larg, pars, span=1, fill=None):
        return (f'<w:tc><w:tcPr><w:tcW w:w="{larg}" w:type="dxa"/>' + (f'<w:gridSpan w:val="{span}"/>' if span > 1 else "")
                + f'<w:tcBorders>{self.borda()}</w:tcBorders>' + (f'<w:shd w:fill="{fill}" w:val="clear"/>' if fill else "")
                + f'<w:tcMar><w:top w:w="{self.mar_v}" w:type="dxa"/><w:left w:w="{self.mar_h}" w:type="dxa"/>'
                  f'<w:bottom w:w="{self.mar_v}" w:type="dxa"/><w:right w:w="{self.mar_h}" w:type="dxa"/></w:tcMar>'
                  '<w:vAlign w:val="top"/></w:tcPr>' + pars + '</w:tc>')

    def tr(self, tcs, cabecalho=False, inteira=False):
        """Linha da tabela. `inteira`: a linha não se parte entre duas páginas (linhas curtas do quadro-resumo)."""
        pr = (f'<w:trPr><w:cantSplit w:val="{1 if inteira else 0}"/>' + ('<w:tblHeader w:val="1"/>' if cabecalho else '') + '</w:trPr>')
        return f'<w:tr>{pr}{"".join(tcs)}</w:tr>'

    def tbl(self, grade, linhas):
        cols = "".join(f'<w:gridCol w:w="{g}"/>' for g in grade)
        return (f'<w:tbl><w:tblPr><w:tblW w:w="{sum(grade)}" w:type="dxa"/><w:jc w:val="left"/><w:tblInd w:w="0" w:type="dxa"/>'
                f'<w:tblBorders>{self.borda()}<w:insideH w:val="single" w:sz="{self.esp_borda}" w:space="0" w:color="{self.cor_borda}"/>'
                f'<w:insideV w:val="single" w:sz="{self.esp_borda}" w:space="0" w:color="{self.cor_borda}"/></w:tblBorders>'
                f'<w:tblLayout w:type="fixed"/></w:tblPr><w:tblGrid>{cols}</w:tblGrid>{"".join(linhas)}</w:tbl>')


def _el(xml):
    raiz = etree.fromstring(f'<w:raiz xmlns:w="{W_NS}">{xml}</w:raiz>')
    filho = raiz[0]
    raiz.remove(filho)
    return filho


def _par_vazio_xml(e):
    return f'<w:p><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr><w:r>{e.rpr()}</w:r></w:p>'


def _bloco_xml(e, proc, pedacos_andamentos):
    """Tabela de um processo, pelo estilo `e`. `pedacos_andamentos` = [(texto, negrito)] do texto de andamentos."""
    t = _texto_campos(proc)
    g = e.grade
    rot = lambda s, i: e.tc(g[i], e.par(e.run(s, True)), fill=e.fill_rotulo)
    runs = "".join(e.run(x, n) for x, n in _juntar_pedacos(pedacos_andamentos))
    titulo = lambda n: e.tr([e.tc(sum(g), e.par(e.run(_titulo_processo(proc), True)), n, fill=e.fill_titulo)])
    if e.nome == "a":
        val = lambda i, s, span=1: e.tc(sum(g[i:i + span]), e.par(e.run(s) if s else ""), span)
        linhas = [titulo(4),
                  e.tr([rot("Assunto", 0), val(1, t["assunto"], 3)]),
                  e.tr([rot("Autor(es)", 0), val(1, t["autores"], 3)]),
                  e.tr([rot("Réu(s)", 0), val(1, t["reus"], 3)]),
                  e.tr([rot("Ajuizamento", 0), val(1, t["ajuizamento"]), rot("Valor da Causa", 2), val(3, t["valor_causa"])]),
                  e.tr([rot("Data de citação", 0), val(1, t["data_citacao"]), rot("Juízo", 2), val(3, t["juizo"])]),
                  e.tr([rot("Área do Direito", 0), val(1, t["area"]), rot("Matéria Principal", 2), val(3, t["materia"])]),
                  e.tr([rot("Andamentos:", 0), e.tc(sum(g[1:]), e.par(runs, "both"), 3)])]
    else:   # compacto: grade de 6 colunas, até três pares rótulo/valor por linha
        val = lambda i, s, span=1: e.tc(sum(g[i:i + span]), e.par(e.run(s) if s else ""), span)
        linhas = [titulo(6),
                  e.tr([rot("Assunto", 0), val(1, t["assunto"], 5)]),
                  e.tr([rot("Autor(es)", 0), val(1, t["autores"], 2), rot("Réu(s)", 3), val(4, t["reus"], 2)]),
                  e.tr([rot("Ajuizamento", 0), val(1, t["ajuizamento"]), rot("Valor da Causa", 2), val(3, t["valor_causa"]),
                        rot("Data de citação", 4), val(5, t["data_citacao"])]),
                  e.tr([rot("Juízo", 0), val(1, t["juizo"]), rot("Área do Direito", 2), val(3, t["area"]),
                        rot("Matéria Principal", 4), val(5, t["materia"])]),
                  e.tr([rot("Andamentos:", 0), e.tc(sum(g[1:]), e.par(runs, "both"), 5)])]
    return e.tbl(g, linhas)


def _resumo_xml(e, processos):
    """Quadro-resumo; `processos` = [(proc, momento, ultimo_andamento)]."""
    L = e.larg_resumo
    cab = e.tr([e.tc(L[i], e.par(e.run(s, True, e.tam_resumo)), fill=e.fill_cab) for i, s in
                enumerate(["Nº DO PROCESSO", "ASSUNTO", "MOMENTO ATUAL DO PROCESSO", "ÚLTIMO ANDAMENTO"])], cabecalho=True, inteira=True)
    linhas = [cab]
    for p, momento, ultimo in processos:
        numeros = "".join(e.par(e.run(n, False, e.tam_resumo)) for n in _linhas_numero_resumo(p))
        linhas.append(e.tr([e.tc(L[0], numeros), e.tc(L[1], e.par(e.run(p.get("assunto") or "-", False, e.tam_resumo))),
                            e.tc(L[2], e.par(e.run(momento, True, e.tam_resumo))),
                            e.tc(L[3], e.par(e.run(ultimo or "-", False, e.tam_resumo)))], inteira=True))
    return e.tbl(L, linhas)


def _esqueleto(e, elementos, destino, titulo):
    """Pacote .docx mínimo e válido (estilos, tema, rels do python-docx) com os `elementos` no corpo; bytes
    determinísticos (sem data de gravação), para o modelo versionado não mudar a cada geração."""
    import docx   # python-docx só aqui (criação do modelo e dos testes), nunca na atualização de arquivo existente
    d = docx.Document()
    corpo = d.element.body
    sect = corpo.find(w("sectPr"))
    for filho in list(corpo):
        if filho is not sect:
            corpo.remove(filho)
    pg = sect.find(w("pgSz"))
    pg.set(w("w"), "11906"), pg.set(w("h"), "16838")
    mar = sect.find(w("pgMar"))
    mar.set(w("left"), str(e.margem)), mar.set(w("right"), str(e.margem))
    for el in elementos:
        sect.addprevious(el)
    props = d.core_properties
    props.author = props.last_modified_by = props.comments = props.keywords = ""
    props.title = titulo
    props.created = props.modified = datetime.datetime(2026, 10, 7)
    props.revision = 1
    buf = io.BytesIO()
    d.save(buf)
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(buf.getvalue())) as zin, zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in zin.infolist():
            novo = zipfile.ZipInfo(info.filename, date_time=(2026, 10, 7, 0, 0, 0))
            novo.compress_type, novo.external_attr = zipfile.ZIP_DEFLATED, info.external_attr
            zout.writestr(novo, zin.read(info.filename))


# Processo-modelo do modelo sanitizado: só marcadores; o número é o de exemplo permitido pelo empacotar.sh.
DATA_MODELO = "01/01/2000"
PROC_MODELO = {"numeros": ["0000000-00.0000.0.00.0000"], "tipos": [], "assunto": "(assunto)", "autores": "(autor)",
               "reus": "(réu)", "ajuizamento": DATA_MODELO, "valor_causa": "R$ 0,00", "data_citacao": DATA_MODELO,
               "juizo": "(juízo)", "area": "(área do direito)", "materia": "(matéria principal)",
               "momento_atual": "MOMENTO ATUAL"}


def criar_modelo(estilo, destino):
    """Grava o modelo sanitizado do estilo ('a' | 'compacto'): título, Data-Base, quadro-resumo com UMA linha-modelo
    e UM bloco-modelo, só com marcadores (sem nome, número real nem valor). Exige python-docx."""
    e = _Estilo(estilo)
    pedacos = [("Em ", False), (DATA_MODELO, True), (", descrição do andamento.", False), (" ", False),
               ("Em ", False), (DATA_MODELO, True), (SUFIXO_FECHO, False)]
    elementos = [_el(e.par(e.run("NOME DO CLIENTE", True, e.tam_cliente))),
                 _el(e.par(e.run("Data-Base: ", True) + e.run(DATA_MODELO))),
                 _el(_par_vazio_xml(e)),
                 _el(_resumo_xml(e, [(PROC_MODELO, "MOMENTO ATUAL", DATA_MODELO)])), _el(_par_vazio_xml(e)),
                 _el(_bloco_xml(e, PROC_MODELO, pedacos)), _el(_par_vazio_xml(e))]
    _esqueleto(e, elementos, destino, f"Modelo A ({estilo}), sem dados")
    return Path(destino)


def _caminho_modelo(estilo):
    _Estilo(estilo)                        # valida o nome
    caminho = PASTA_MODELOS / f"modelo_{estilo}.docx"
    if not caminho.exists():
        raise FileNotFoundError(f"modelo sanitizado ausente: {caminho} (recrie com criar_modelos.py)")
    return caminho


# ------------------------------------------------------------------ gravação do pacote

def _gravar_pacote(origem, destino, xml_novo):
    """Copia `origem` para `destino` trocando só word/document.xml (mesmo ZipInfo: nome, data e compressão)."""
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=destino.parent, suffix=".tmp")
    os.close(fd)
    try:
        with zipfile.ZipFile(origem) as zin, zipfile.ZipFile(tmp, "w") as zout:
            for info in zin.infolist():
                dados = xml_novo if info.filename == PARTE_DOCUMENTO else zin.read(info.filename)
                zout.writestr(info, dados)
        os.replace(tmp, destino)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _checar_destino(origem, destino, sobrescrever):
    destino = Path(destino)
    if origem is not None:
        origem = Path(origem)
        if destino.resolve() == origem.resolve() or (destino.exists() and origem.exists() and os.path.samefile(destino, origem)):
            raise ValueError("o arquivo original nunca é sobrescrito: informe outro destino")
    if destino.exists() and not sobrescrever:
        raise FileExistsError(f"{destino} já existe")


def _fechar_resultado(ctx, destino):
    """Preenche textos_gravados/campos_gravados pelo estado final do documento e roda o portão de coerência."""
    doc, res = ctx.doc, ctx.res
    resumo = doc.resumo()
    linha_por_numero = {}
    if resumo is not None:
        for _tr, ns, d in resumo.dados():
            for n in ns:
                linha_por_numero.setdefault(n, d)
    for b in doc.blocos():
        chave = ctx.chave(b)
        res["textos_gravados"][chave] = b.andamentos_texto()
        d = next((linha_por_numero[n] for n in b.numeros if n in linha_por_numero), None)
        res["campos_gravados"][chave] = {"momento_atual": b.momento or (d or {}).get("momento") or None,
                                         "ultimo_andamento": (d or {}).get("ultimo") or None}
    res["destino"], res["gravado"] = Path(destino), True


def _portao(destino, res):
    """Conferência pós-escrita: o arquivo recarrega e resumo e blocos continuam coerentes."""
    try:
        with zipfile.ZipFile(destino) as z:
            ruim = z.testzip()
        problemas = [f"parte do pacote corrompida: {ruim}"] if ruim else verificar_coerencia(destino, fechos=False, ultimo=False)
    except Exception as exc:    # arquivo gravado que não reabre: o chamador precisa saber
        _aviso(res, "erro", "documento", "erro", f"o arquivo gravado não pôde ser relido: {exc}")
        return
    for p in problemas:
        _aviso(res, "atencao", "documento", "incoerencia_documento", p)


def _molde_ilegivel(destino, mensagem):
    res = _novo_resultado(destino)
    _aviso(res, "erro", "molde", "molde_ilegivel", mensagem)
    return res


# ------------------------------------------------------------------ construção do zero (gerar) e atualização

def gerar(destino, relatorio, *, chaves=None, **opcoes):
    """Cria o .docx do zero a partir do modelo sanitizado (abre o modelo, insere cada processo pelo mesmo caminho do
    'processo novo' e tira o bloco e a linha de exemplo).
    relatorio = {'cliente', 'data_base', 'processos': [proc, ...]}, com
    proc = {'numeros': [principal, vinculados...], 'tipos': [tipo de cada vinculado], 'assunto', 'autores', 'reus',
            'ajuizamento', 'valor_causa', 'data_citacao', 'juizo', 'area', 'materia', 'momento_atual',
            'momento_qualificador', 'ultimo_andamento', 'historico' (texto migrado), 'andamentos': [{'data', 'texto'}]}."""
    opc = _opcoes(opcoes)
    destino = Path(destino)
    _checar_destino(None, destino, opc["sobrescrever_destino"])
    modelo = _caminho_modelo(opc["estilo"] or "a")
    data_base = _data_br(relatorio["data_base"])
    if not data_base:
        raise ValueError("data_base inválida")
    with zipfile.ZipFile(modelo) as z:
        doc = _Documento(z.read(PARTE_DOCUMENTO))
    res = _novo_resultado(destino)
    ctx = _Ctx(doc, data_base, opc, res, chaves)
    # cabeçalho: cliente e Data-Base (o modelo traz marcadores)
    par_cliente = doc.par_cliente()
    if par_cliente is not None:
        _substituir(par_cliente, 0, len(_texto_par(par_cliente)), relatorio.get("cliente") or "")
    par, m = doc.par_data_base()
    _substituir(par, m.start(2), m.end(2), data_base)
    resumo = doc.resumo()
    bloco_modelo = doc.blocos()[0]
    linha_modelo = resumo.dados()[0][0]
    ins = _Insersor(ctx, modelo=bloco_modelo, modelo_linha=linha_modelo)
    ins.existentes.clear()                              # o número do modelo não conta como processo existente
    for proc in relatorio["processos"]:
        ins.inserir(proc)
    # o bloco-modelo (e o parágrafo vazio que o segue) e a linha-modelo saem
    seguinte = bloco_modelo.tbl.getnext()
    if seguinte is not None and seguinte.tag == w("p") and not _texto_par(seguinte).strip():
        doc.body.remove(seguinte)
    doc.body.remove(bloco_modelo.tbl)
    linha_modelo.getparent().remove(linha_modelo)
    ctx.mudanca(None, "documento", None, "gerado do zero")
    _gravar_pacote(modelo, destino, doc.serializar())
    _fechar_resultado(ctx, destino)
    _portao(destino, res)
    return res


def atualizar(origem, destino, atualizacoes, data_base, *, chaves=None, **opcoes):
    """Copia `origem` para `destino` aplicando as atualizações. Devolve o Resultado (ver o cabeçalho do módulo).

    atualizacoes: lista de dicts
      {'numero' | 'numeros': ..., 'momento_atual': 'AGUARDANDO SENTENÇA'|None, 'momento_qualificador': str|None,
       'ultimo_andamento': data|None, 'andamentos': [{'data': 'DD/MM/AAAA', 'texto': 'o juiz proferiu ...'}],
       'texto_conhecido': texto de andamentos como o sistema o deixou no último ciclo (opcional),
       'novo': proc (opcional: se nenhum número estiver no arquivo, o processo entra como novo)}
      {'novo': proc}  -> processo novo (mesmo formato de `gerar`); já existente: ignorado com aviso
    Processos do arquivo que não aparecem na lista ficam INTACTOS (salvo renovar_fecho_dos_demais=True).
    `chaves`: {qualquer número do processo: número a usar nos resultados} (a `gravar` passa o da ficha)."""
    opc = _opcoes(opcoes)
    origem, destino = Path(origem), Path(destino)
    _checar_destino(origem, destino, opc["sobrescrever_destino"])
    data_base = _data_br(data_base)
    if not data_base:
        raise ValueError("data_base inválida")
    res = _novo_resultado(destino)
    try:
        with zipfile.ZipFile(origem) as z:
            original = z.read(PARTE_DOCUMENTO)
            extras = {n: z.read(n) for n in z.namelist() if n in ("word/settings.xml", "word/comments.xml")}
        doc = _Documento(original)
    except (zipfile.BadZipFile, KeyError, OSError, etree.XMLSyntaxError, ValueError) as exc:
        return _molde_ilegivel(destino, f"não foi possível abrir {origem.name} como documento Word (.docx): {exc}")
    ctx = _Ctx(doc, data_base, opc, res, chaves)
    if b"<w:trackRevisions" in extras.get("word/settings.xml", b""):
        ctx.aviso("atencao", "documento", "controle_alteracoes_ligado",
                  "o documento está com controle de alterações ligado: as edições do sistema NÃO ficam marcadas como revisão")
    if "word/comments.xml" in extras:
        ctx.aviso("info", "documento", "tem_comentarios", "o documento tem comentários: partes de comentários preservadas")

    _atualizar_data_base(ctx)
    resumo = doc.resumo()
    if resumo is None:
        ctx.aviso("atencao", "documento", "sem_resumo", "quadro-resumo não encontrado: só os blocos serão atualizados")
    todos_blocos = doc.blocos()                                   # índices feitos UMA vez (200 processos: O(n), não O(n²))
    bloco_por_numero = {}
    for b in todos_blocos:
        for n in b.numeros:
            bloco_por_numero.setdefault(n, []).append(b)
    linha_por_numero = {}
    if resumo is not None:
        for tr, ns, _ in resumo.dados():
            for n in ns:
                linha_por_numero.setdefault(n, tr)
    tocados, insersor = set(), None
    for upd in atualizacoes:
        novo = upd.get("novo")
        numeros = list(upd.get("numeros") or ([upd["numero"]] if upd.get("numero") else [])
                       or ((novo.get("numeros") or [novo.get("numero")]) if novo else []))
        achados = list(dict.fromkeys(b for n in numeros for b in bloco_por_numero.get(n, [])))
        solo = novo is not None and not (upd.get("numeros") or upd.get("numero"))
        if not achados or solo:
            if novo is not None:
                if insersor is None:
                    insersor = _Insersor(ctx)
                insersor.inserir(novo)
                continue
            res["nao_encontrados"].append(numeros[0] if numeros else None)
            ctx.aviso("atencao", numeros[0] if numeros else "documento", "processo_nao_encontrado",
                      "número não encontrado em nenhum título de bloco", numeros)
            continue
        if len(achados) > 1:
            ctx.aviso("atencao", numeros[0], "numero_em_varios_blocos",
                      "número aparece em mais de um bloco: atualizado só o primeiro", [b.numeros[0] for b in achados])
        bloco = achados[0]
        tocados.add(id(bloco.tbl))
        chave = ctx.chave(bloco)
        if set(numeros) - set(bloco.numeros):
            ctx.aviso("info", chave, "numero_vinculado_novo",
                      "a atualização traz número que não está no título do bloco (não acrescentado ao título)",
                      sorted(set(numeros) - set(bloco.numeros)))
        linha = None
        if resumo is not None:
            linha = next((linha_por_numero[n] for n in bloco.numeros if n in linha_por_numero), None)
            if linha is None:
                ctx.aviso("atencao", chave, "sem_linha_no_resumo", "bloco sem linha correspondente no quadro-resumo")
        aceitos = _atualizar_andamentos(ctx, bloco, upd) or []
        _atualizar_resumo_e_titulo(ctx, resumo, bloco, linha, upd, aceitos)
    novos = set(res["processos_novos"])
    demais = [b for b in todos_blocos if id(b.tbl) not in tocados and b.numeros[0] not in novos]
    if opc["renovar_fecho_dos_demais"]:
        for bloco in demais:
            _atualizar_andamentos(ctx, bloco, {"andamentos": []})
    elif demais:
        ctx.aviso("info", "documento", "processos_sem_atualizacao",
                  f"{len(demais)} processo(s) do arquivo ficaram intactos (sem atualização informada)",
                  [b.numeros[0] for b in demais])
    mudou = bool(res["mudancas"])
    _gravar_pacote(origem, destino, doc.serializar() if mudou else original)
    _fechar_resultado(ctx, destino)
    _portao(destino, res)
    return res


# ------------------------------------------------------------------ conferência de coerência

def verificar_coerencia(docx, fechos=True, ultimo=True):
    """Lista de problemas entre quadro-resumo, blocos, fecho e data-base (lista vazia = coerente).
    fechos=False ignora fecho com data diferente da data-base (esperado quando só parte dos processos foi atualizada);
    ultimo=False ignora diferença entre o último andamento do resumo e o último do texto (o resumo pode trazer a
    data de um movimento que o texto não narra)."""
    doc = _abrir(docx)
    problemas = []
    _, m = doc.par_data_base()
    data_base = m.group(2) if m else None
    if not data_base:
        problemas.append("sem 'Data-Base'")
    resumo = doc.resumo()
    blocos = doc.blocos()
    linhas = resumo.dados() if resumo is not None else []
    linha_por_numero = {}
    for _tr, ns, d in linhas:
        for n in ns:
            linha_por_numero.setdefault(n, (ns, d))
    vistos = {}
    for b in blocos:
        for n in b.numeros:
            if n in vistos:
                problemas.append(f"{n}: número em dois blocos")
            vistos[n] = b
    for b in blocos:
        par = next((linha_por_numero[n] for n in b.numeros if n in linha_por_numero), None)
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
        itens = [a for a in _parse_andamentos(_plano(texto), data_base) if not a["fecho"]]
        if ultimo and itens:
            ult = max((a["data"] for a in itens), key=_ordem_data)
            if d["ultimo"] != ult:
                problemas.append(f"{rotulo}: último andamento do resumo ({d['ultimo']}) difere do último do texto ({ult})")
        fe = _achar_fecho(_plano(texto))
        if fechos and fe and data_base and fe.group(1) != data_base:
            problemas.append(f"{rotulo}: fecho com {fe.group(1)} difere da data-base {data_base}")
    numeros_dos_blocos = set(vistos)
    for _tr, ns, _d in linhas:
        if not (set(ns) & numeros_dos_blocos):
            problemas.append(f"{ns[0]}: linha do resumo sem bloco")
    return problemas


# ------------------------------------------------------------------ contrato CONTRATOS.md 5: gravar(molde, estado, destino)

def texto_do_evento(ev):
    """Cláusula do andamento a partir de um evento aprovado: as mesmas regras de relatorio.linha (frase + conteúdo +
    Audiência/Prazo) e de planilha.frase_planilha (prefixo 'no 2º grau,' fora do 1º grau)."""
    import relatorio
    frase, extras = relatorio.linha(ev)
    frase = frase.strip()
    if frase and ev.get("grau") and ev["grau"] != "1º grau":
        primeira = frase.split()[0]
        corpo = frase if (len(primeira) > 1 and primeira.isupper()) else frase[0].lower() + frase[1:]   # mantém siglas
        frase = f"no {ev['grau']}, {corpo}"
    for x in extras:
        frase += f" {x}."
    return frase


def _data_do_evento(ev):
    return _data_br(ev.get("data")) or _data_br(str(ev.get("detectado_em") or "")[:10])


def _qualificador_da_ficha(f):
    campos = f.get("campos") or {}
    q = (campos.get("momento_qualificador") or {}).get("valor") or f.get("momento_qualificador")
    return q or (campos.get("momento_atual") or {}).get("qualificador")


def _proc_da_ficha(f, eventos_do_processo):
    numeros = fch.todos_os_numeros(f)
    tipos = [v.get("tipo") or "" for v in f.get("vinculados") or []]
    canonico, qualificador = separar_momento(fch.obter(f, "momento_atual"))
    andamentos = []
    for ev in eventos_do_processo:
        if ev.get("status", "aprovado") in ("aprovado", "relatado"):
            andamentos.append({"data": _data_do_evento(ev), "texto": texto_do_evento(ev),
                               "relatado": ev.get("status") == "relatado"})
    base = f.get("linha_de_base") or {}
    return {"numeros": numeros, "tipos": tipos, "assunto": fch.obter(f, "assunto"), "autores": fch.obter(f, "autores"),
            "reus": fch.obter(f, "reus"), "ajuizamento": _data_br(fch.obter(f, "data_ajuizamento")),
            "valor_causa": fch.obter(f, "valor_causa"), "data_citacao": _data_br(fch.obter(f, "data_citacao")),
            "juizo": fch.obter(f, "vara"), "area": fch.obter(f, "area"), "materia": fch.obter(f, "materia_principal"),
            "momento_atual": canonico or None, "momento_qualificador": _qualificador_da_ficha(f) or qualificador,
            "ultimo_andamento": _data_br(fch.obter(f, "ultimo_andamento")),
            "historico": base.get("andamentos_texto") or "", "andamentos": andamentos}


def gravar(molde, estado, destino, **opcoes):
    """Contrato docx_a.gravar(molde, estado, destino) -> Resultado (CONTRATOS.md 5).
    molde=None cria do zero (modelo sanitizado); senão grava em `destino` uma cópia atualizada de `molde`.
    Processo da ficha que não está no molde entra como novo (clonado de um bloco-modelo do próprio arquivo, com o
    histórico migrado da linha de base); processo do molde que não está nas fichas fica intacto.
    Opções: ver o cabeçalho do módulo."""
    opc = _opcoes(opcoes)
    data_base = _data_br(estado["data_base"])
    if not data_base:
        raise ValueError("data_base inválida")
    fichas = estado.get("fichas") or []
    por_numero = {}
    for ev in estado.get("eventos") or []:
        por_numero.setdefault(ev.get("numero"), []).append(ev)
    procs = []
    for f in fichas:
        evs = [e for n in fch.todos_os_numeros(f) for e in por_numero.get(n, [])]
        procs.append(_proc_da_ficha(f, evs))
    chaves = {n: f["numero"] for f in fichas for n in fch.todos_os_numeros(f)}
    gravados = {f["numero"]: f.get("ultimo_texto_gravado") or {} for f in fichas}
    if opc["textos_conhecidos"] is None:
        opc["textos_conhecidos"] = {n: g["texto"] for n, g in gravados.items() if g.get("texto") is not None}
    if opc["campos_conhecidos"] is None:
        opc["campos_conhecidos"] = {n: g["campos"] for n, g in gravados.items() if g.get("campos")}
    if opc["data_base_conhecida"] is None:
        opc["data_base_conhecida"] = _maior_data([_data_br(g.get("data_base")) for g in gravados.values()])
    if opc["estilo"] is None:
        perfil = estado.get("perfil") or {}
        opc["estilo"] = ESTILO_DO_PERFIL.get(str(perfil.get("estilo_texto") or "a").strip().lower(), "a")
    destino = Path(destino)
    if molde is None:
        return gerar(destino, {"cliente": estado.get("cliente"), "data_base": data_base, "processos": procs},
                     chaves=chaves, **{k: v for k, v in opc.items()})
    molde = Path(molde)
    atualizacoes = []
    for f, p in zip(fichas, procs):
        atualizacoes.append({"numeros": p["numeros"], "momento_atual": p["momento_atual"],
                             "momento_qualificador": p["momento_qualificador"],
                             "ultimo_andamento": p["ultimo_andamento"], "andamentos": p["andamentos"],
                             "texto_conhecido": opc["textos_conhecidos"].get(f["numero"]), "novo": p})
    return atualizar(molde, destino, atualizacoes, data_base, chaves=chaves, **{k: v for k, v in opc.items()})


# ------------------------------------------------------------------ linha de comando

def ensaio(origem, destino, data_base, **opcoes):
    """Ciclo de teste para a conferência manual (docs/fase2/conferencia-docx.md): grava em `destino` uma CÓPIA do
    arquivo real com a data-base nova, uma frase de teste ("ENSAIO") em dois processos, fecho renovado nos demais e
    um processo novo de mentira (número de exemplo). Não usa fichas, eventos nem coleta."""
    est = ler_estrutura(origem)
    upds = [{"numeros": p["numeros"], "andamentos": [{"data": data_base, "texto": "foi feito um teste do programa "
             "(ENSAIO: pode apagar esta frase)."}]} for p in est["processos"][:2]]
    proc = {"numeros": [PROC_MODELO["numeros"][0]], "assunto": "(ENSAIO)", "autores": "(ENSAIO)", "reus": "(ENSAIO)",
            "momento_atual": "MOMENTO DE TESTE", "andamentos": [{"data": data_base, "texto": "processo de teste do programa."}]}
    return atualizar(origem, destino, upds + [{"novo": proc}], data_base, renovar_fecho_dos_demais=True, **opcoes)


def _cli(argv):
    if len(argv) >= 3 and argv[1] == "ler":
        print(json.dumps(ler_estrutura(argv[2]), ensure_ascii=False, indent=2))
    elif len(argv) >= 5 and argv[1] == "ensaio":
        res = ensaio(argv[2], argv[3], argv[4])
        print(f"{'Gravado' if res['gravado'] else 'NÃO gravado'}: {res['destino']}")
        print(f"{len(res['processos_atualizados'])} processo(s) atualizado(s), {len(res['processos_novos'])} novo(s), "
              f"{len(res['ignorados'])} ignorado(s)")
        for a in res["avisos"]:
            print(f"  [{a['nivel']}] {a['codigo']} ({a['onde']}): {a['mensagem']}")
    elif len(argv) >= 3 and argv[1] == "modelos":
        for estilo in ESTILOS:
            print(criar_modelo(estilo, Path(argv[2]) / f"modelo_{estilo}.docx"))
    else:
        print("uso: docx_a.py ler ARQ.docx | ensaio ORIGEM.docx DESTINO.docx DD/MM/AAAA | modelos PASTA")


if __name__ == "__main__":
    _cli(sys.argv)
