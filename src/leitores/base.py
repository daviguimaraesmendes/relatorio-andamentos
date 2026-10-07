"""Peças comuns dos leitores de relatórios (WS-2): avisos, texto, números CNJ, conversão de valores e
análise do texto de andamentos. Nada aqui abre arquivo; é só lógica, para os leitores `docx_a`, `xlsx_b`,
`lista` e `tabela_livre` falarem a mesma língua.

Regras que valem para todos os leitores (CONTRATOS §4):

- Erro esperado vira `Aviso` (`{"nivel", "codigo", "onde", "mensagem", "candidatos"}`), nunca exceção; o
  `codigo` é estável (os testes e a tela de conferência dependem dele, não do texto da mensagem).
- Ambiguidade nunca vira dado silencioso: rótulo fora do vocabulário, data inválida, valor ilegível, número
  repetido, coluna que poderia ser de dois campos: tudo gera aviso e o campo fica VAZIO (não se adivinha).
- Número de processo com dígito verificador errado é recusado e listado (`numero_dv_invalido`).

Códigos de aviso usados (estáveis):

    arquivo_inexistente, arquivo_ilegivel, arquivo_muito_grande, formato_nao_reconhecido      (erro)
    numero_dv_invalido, numero_invalido                                                       (erro)
    numero_repetido, numero_em_dois_lugares, linha_sem_numero, vinculo_tipo_indefinido        (atencao)
    data_invalida, valor_invalido, rotulo_fora_do_vocabulario, momento_fora_do_vocabulario    (atencao)
    momento_divergente, ultimo_andamento_divergente, coluna_ambigua, coluna_duplicada         (atencao)
    coluna_baixa_confianca, celula_com_erro, parametro_invalido, mapeamento_invalido          (atencao)
    resumo_sem_bloco, quadro_resumo_ausente, bloco_sem_andamentos, sem_aba_de_processos       (atencao)
    formula_sem_valor (atencao; info nas colunas derivadas), linhas_ignoradas, aba_ignorada   (info)
    rotulo_aproximado, momento_com_qualificador, situacao_era_momento, fecho_fora_do_fim      (info)
    andamentos_sem_marcador, bloco_sem_resumo, data_base_ausente, revisoes_no_documento       (info)

Convenções de valor (iguais às da ficha, `ficha.CAMPOS`): datas em ISO, dinheiro em texto decimal
("1234.56"), sim/não como "Sim"/"Não", números como float. `percentual_exito` é guardado como FRAÇÃO
(0,25 = 25%): célula com formato de porcentagem, texto "25%" e número até 1 viram fração; número maior que 1
é lido como pontos percentuais (25 -> 0,25). Ver docs/fase2/RFC-convencoes-leitores.md.
"""
import datetime
import difflib
import re
import unicodedata
from decimal import Decimal, InvalidOperation

import carteira as cart
import ficha
import taxonomia

NIVEIS = ("info", "atencao", "erro")


# ---------------------------------------------------------------- avisos e relatório

def aviso(nivel, codigo, onde, mensagem, candidatos=None):
    """Aviso estruturado (CONTRATOS §4)."""
    return {"nivel": nivel, "codigo": codigo, "onde": onde, "mensagem": mensagem, "candidatos": list(candidatos or [])}


def novo_relatorio(formato, arquivo):
    """RelatorioLido vazio, com todas as chaves do contrato."""
    return {"formato": formato, "arquivo": arquivo, "cliente": None, "data_base": None, "processos": [],
            "parametros": {}, "colunas_sem_destino": [], "avisos": []}


def processo_lido(numero, campos=None, vinculados=None, andamentos_texto="", ultimo_andamento=None,
                  origem_no_arquivo="", **extras):
    """ProcessoLido do contrato. `extras` (chaves aditivas, nunca obrigatórias): `ativo`, `fecho`, `andamentos`,
    `momento_qualificador`."""
    p = {"numero": numero, "vinculados": list(vinculados or []), "campos": dict(campos or {}),
         "andamentos_texto": andamentos_texto or "", "ultimo_andamento": ultimo_andamento,
         "origem_no_arquivo": origem_no_arquivo}
    p.update({k: v for k, v in extras.items() if v not in (None, [], "")})
    return p


# ---------------------------------------------------------------- texto

def chave(texto):
    """Comparação tolerante: minúsculas, sem acento nem pontuação, espaços colapsados ("Nº do Processo" -> "no do processo")."""
    s = unicodedata.normalize("NFKD", str(texto if texto is not None else ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def limpar_texto(texto):
    """Tira espaço não separável e caracteres invisíveis (exportação do Google Docs) e apara as pontas."""
    s = str(texto if texto is not None else "").replace("\xa0", " ")
    s = re.sub(r"[​‌‍﻿­]", "", s)
    return s.strip()


def vazio(valor):
    return valor is None or (isinstance(valor, str) and not valor.strip())


# placeholders que significam "não há valor"
_TRACOS = {"-", "--", "---", "–", "—", "n a", "na", "n d", "nd"}
_SEM_VALOR = _TRACOS | {"nao se aplica", "nao informado", "nao consta", "sem informacao", "a definir", "sem valor",
                        "nao ha", "nenhum", "nenhuma", "sem data", "tbd", ""}


def eh_vazio_logico(texto, amplo):
    """True se o texto é só um placeholder ("-", "N/A"); `amplo` inclui "não consta", "sem valor"..."""
    k = chave(texto)
    if limpar_texto(texto) in ("-", "–", "—", "--"):
        return True
    return k in (_SEM_VALOR if amplo else _TRACOS) or k == ""


# ---------------------------------------------------------------- números CNJ

def achar_numeros(texto):
    """Ocorrências de número CNJ no texto, na ordem: [{"numero", "valido", "inicio", "fim"}].
    Aceita com ou sem pontuação; o número volta SEMPRE com a máscara. Repetições entram (quem chama decide)."""
    saida = []
    for m in cart.CNJ.finditer(str(texto or "")):
        g = m.groups()
        saida.append({"numero": cart.mascara(g), "valido": cart.dv_correto(g), "inicio": m.start(), "fim": m.end()})
    return saida


_TIPOS_POR_PALAVRA = (("agravo", "agravo"), ("apenso", "apenso"), ("apensado", "apenso"), ("incidente", "apenso"),
                      ("reajuiz", "reajuizamento"), ("mesma acao", "mesma_acao"), ("incompet", "mesma_acao"),
                      ("recurso", "recurso"), ("apelacao", "recurso"), ("embargos", "recurso"),
                      ("recursal", "recurso"), ("especial", "recurso"), ("extraordinario", "recurso"))


def tipo_do_vinculo(rotulo):
    """'AGRAVO DE INSTRUMENTO Nº' -> 'agravo'; None se o rótulo não diz (nunca adivinha)."""
    k = chave(rotulo)
    for palavra, tipo in _TIPOS_POR_PALAVRA:
        if palavra in k:
            return tipo
    return None


def interpretar_numeros(texto, onde, avisar_indefinido=True):
    """Primeiro número do texto = principal; os demais = vinculados (o tipo sai do rótulo antes de cada
    número: 'AGRAVO DE INSTRUMENTO Nº ...', 'Apenso: ...').
    Volta (principal | None, [{"numero", "tipo"}], [Aviso]). Se o principal tem dígito errado, o processo
    inteiro é recusado; vinculado com dígito errado é descartado e listado. Com `avisar_indefinido=False`, o
    vinculado sem rótulo fica com tipo None e sem aviso (quem chama resolve por outra fonte)."""
    ocorrencias = achar_numeros(texto)
    avisos = []
    if not ocorrencias:
        return None, [], avisos
    principal = ocorrencias[0]
    if not principal["valido"]:
        outros = [o["numero"] for o in ocorrencias[1:] if o["valido"]]
        avisos.append(aviso("erro", "numero_dv_invalido", onde,
                            f"Número {principal['numero']}: o dígito verificador não confere (provável erro de digitação). "
                            "Processo recusado; confira o número no tribunal.", [principal["numero"], *outros]))
        return None, [], avisos
    vinculados, vistos = [], {principal["numero"]}
    anterior = principal["fim"]
    for o in ocorrencias[1:]:
        rotulo = str(texto)[anterior:o["inicio"]]
        anterior = o["fim"]
        if not o["valido"]:
            avisos.append(aviso("erro", "numero_dv_invalido", onde,
                                f"Número vinculado {o['numero']}: o dígito verificador não confere; descartado.", [o["numero"]]))
            continue
        if o["numero"] in vistos:
            continue
        vistos.add(o["numero"])
        tipo = tipo_do_vinculo(rotulo[-80:])
        if tipo is None and avisar_indefinido:
            avisos.append(aviso("atencao", "vinculo_tipo_indefinido", onde,
                                f"Não ficou claro se {o['numero']} é agravo, apenso ou recurso do principal; "
                                "marcado como 'apenso'. Confira.", [o["numero"]]))
            tipo = "apenso"
        vinculados.append({"numero": o["numero"], "tipo": tipo})
    return principal["numero"], vinculados, avisos


# ---------------------------------------------------------------- datas

MESES = {"janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6, "julho": 7, "agosto": 8,
         "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12}
_MES_RE = "|".join(MESES)
_DATA_NUM = re.compile(r"(?<!\d)(\d{1,2})[/.\-](\d{1,2})[/.\-](\d{4}|\d{2})(?!\d)")
_DATA_ISO = re.compile(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)")
_DATA_EXT = re.compile(r"(?<!\d)(\d{1,2})\s*(?:º|°)?\s+de\s+(" + _MES_RE + r")\s+de\s+(\d{4})(?!\d)", re.I)
EXCEL_MIN, EXCEL_MAX = 18264, 73415       # séries de data plausíveis (anos 1950 a 2100)


def _data_valida(a, m, d):
    try:
        return datetime.date(a, m, d)
    except ValueError:
        return None


def datas_no_texto(texto):
    """Datas válidas no texto (DD/MM/AAAA, DD/MM/AA, AAAA-MM-DD, '18 de junho de 2026'): [(date, inicio, fim)] em ordem."""
    t = str(texto or "")
    achadas = []
    for m in _DATA_NUM.finditer(t):
        d, mes, a = int(m[1]), int(m[2]), m[3]
        ano = int(a) if len(a) == 4 else (2000 + int(a) if int(a) <= 40 else 1900 + int(a))
        dt = _data_valida(ano, mes, d)
        if dt:
            achadas.append((dt, m.start(), m.end()))
    for m in _DATA_ISO.finditer(t):
        dt = _data_valida(int(m[1]), int(m[2]), int(m[3]))
        if dt:
            achadas.append((dt, m.start(), m.end()))
    for m in _DATA_EXT.finditer(unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode()):
        dt = _data_valida(int(m[3]), MESES[m[2].lower()], int(m[1]))
        if dt:
            achadas.append((dt, m.start(), m.end()))
    return sorted(achadas, key=lambda x: x[1])


def converter_data(bruto, epoch=None):
    """-> (ISO | None, problema | None). problema: 'invalida' (não é data) ou 'ambigua' (várias datas diferentes)."""
    if bruto is None or isinstance(bruto, bool):
        return None, ("invalida" if isinstance(bruto, bool) else None)
    if isinstance(bruto, datetime.datetime):
        return bruto.date().isoformat(), None
    if isinstance(bruto, datetime.date):
        return bruto.isoformat(), None
    if isinstance(bruto, (int, float, Decimal)):
        if EXCEL_MIN <= float(bruto) <= EXCEL_MAX:
            from openpyxl.utils.datetime import from_excel
            try:
                return from_excel(float(bruto), epoch=epoch or datetime.datetime(1899, 12, 30)).date().isoformat(), None
            except (ValueError, OverflowError):
                return None, "invalida"
        return None, "invalida"
    texto = limpar_texto(bruto)
    if eh_vazio_logico(texto, amplo=True):
        return None, None
    achadas = {d for d, _, _ in datas_no_texto(texto)}
    if len(achadas) == 1:
        return achadas.pop().isoformat(), None
    if len(achadas) > 1:
        return None, "ambigua"
    return None, "invalida"


# ---------------------------------------------------------------- dinheiro e números

_TOKEN_NUM = re.compile(r"-?\d[\d.,]*")


def _parse_dinheiro_seguro(bruto):
    """ficha.parse_dinheiro sem estourar com NaN, infinito ou valor gigante (Decimal levanta InvalidOperation)."""
    try:
        return ficha.parse_dinheiro(bruto)
    except (InvalidOperation, ValueError, OverflowError):
        return None


def converter_dinheiro(bruto):
    """-> ("1234.56" | None, problema | None). Aceita número, 'R$ 1.234,56', '1.234,56', '1234.56', '(1.234,56)' (negativo)."""
    if bruto is None:
        return None, None
    if isinstance(bruto, bool):
        return None, "invalido"
    if isinstance(bruto, (int, float, Decimal)):
        valor = _parse_dinheiro_seguro(bruto)
        return valor, (None if valor is not None else "invalido")
    texto = limpar_texto(bruto)
    if eh_vazio_logico(texto, amplo=True):
        return None, None
    tokens = _TOKEN_NUM.findall(texto)
    if not tokens:
        return None, "invalido"
    if len({t.rstrip(".,") for t in tokens}) > 1:
        return None, "ambiguo"
    valor = _parse_dinheiro_seguro(tokens[0].rstrip(".,"))
    if valor is not None and texto.startswith("(") and texto.endswith(")") and not valor.startswith("-"):
        valor = "-" + valor
    return valor, (None if valor is not None else "invalido")


def converter_numero(bruto, percentual=False, formato_celula=None):
    """-> (float | None, problema | None). `percentual`: guarda como fração (ver cabeçalho do módulo)."""
    if bruto is None:
        return None, None
    if isinstance(bruto, bool):
        return None, "invalido"
    tem_pct_no_texto = isinstance(bruto, str) and "%" in bruto
    if isinstance(bruto, (int, float, Decimal)):
        n = float(bruto)
    else:
        texto = limpar_texto(bruto)
        if eh_vazio_logico(texto, amplo=True):
            return None, None
        m = _TOKEN_NUM.search(texto)
        if not m:
            return None, "invalido"
        s = m.group(0).rstrip(".,")
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".")
        try:
            n = float(s)
        except ValueError:
            return None, "invalido"
    if n != n or n in (float("inf"), float("-inf")):      # NaN ou infinito não é número de relatório
        return None, "invalido"
    if percentual:
        if tem_pct_no_texto:
            n = n / 100.0
        elif not (formato_celula and "%" in str(formato_celula)) and abs(n) > 1:
            n = n / 100.0
        n = round(n, 6)
    return n, None


_SIM = {"sim", "s", "true", "verdadeiro", "1", "x", "yes", "y"}
_NAO = {"nao", "n", "false", "falso", "0", "no"}


def converter_sim_nao(bruto):
    if bruto is None:
        return None, None
    k = chave(bruto)
    if k in _SIM:
        return "Sim", None
    if k in _NAO:
        return "Não", None
    if eh_vazio_logico(bruto, amplo=True):
        return None, None
    return None, "invalido"


# ---------------------------------------------------------------- vocabulários

def _formas(vocabulario, canonico):
    """Chaves (canônico + sinônimos) de um valor do vocabulário. Se a estrutura do vocabulário mudar,
    cai no próprio canônico."""
    try:
        sinonimos = taxonomia.VOCABULARIOS[vocabulario].get(canonico, ())
    except (AttributeError, KeyError, TypeError):
        sinonimos = ()
    return {chave(canonico), *(chave(s) for s in sinonimos)}


def _candidatos_vocabulario(vocabulario, texto, limite=3):
    try:
        canonicos = list(taxonomia.VOCABULARIOS[vocabulario])
    except (AttributeError, KeyError, TypeError):
        return []
    k = chave(texto)
    por_chave = {}
    for c in canonicos:
        for forma in _formas(vocabulario, c):
            por_chave.setdefault(forma, c)
    achados = []
    for forma in difflib.get_close_matches(k, list(por_chave), n=limite * 2, cutoff=0.5):
        if por_chave[forma] not in achados:
            achados.append(por_chave[forma])
    for forma, c in por_chave.items():          # contidos (um dentro do outro), para rótulos com palavra a mais
        if len(forma) >= 6 and (forma in k or k in forma) and c not in achados:
            achados.append(c)
    return achados[:limite]


_QUALIFICADOR = re.compile(r"^(.*?)\s*[\(\[]\s*([^()\[\]]+?)\s*[\)\]]\s*\.?$")


def separar_qualificador(texto):
    """'CUMPRIMENTO DE SENTENÇA (HONORÁRIOS SUSPENSOS)' -> ('CUMPRIMENTO DE SENTENÇA', 'HONORÁRIOS SUSPENSOS')."""
    t = limpar_texto(texto)
    m = _QUALIFICADOR.match(t)
    if m and m.group(1).strip():
        return m.group(1).strip(), m.group(2).strip()
    return t, None


def normalizar_rotulo(vocabulario, texto, estrito=False):
    """Rótulo solto -> (canônico | None, nivel_de_certeza, candidatos).
    certeza: 'exato' (é o canônico ou sinônimo conhecido), 'aproximado' (o vocabulário aceitou por semelhança) ou
    None. `estrito` (momento atual): só aceita aproximação quando o texto é uma ABREVIAÇÃO do rótulo conhecido
    ('ARQUIVADO' -> 'PROCESSO ARQUIVADO'); texto com palavra a mais ('... DO AGRAVO') não perde detalhe em silêncio."""
    canonico = taxonomia.normalizar(vocabulario, texto)
    if canonico is None:
        return None, None, _candidatos_vocabulario(vocabulario, texto)
    k = chave(texto)
    if k in _formas(vocabulario, canonico):
        return canonico, "exato", []
    if estrito and not any(k and k in forma for forma in _formas(vocabulario, canonico)):
        return None, None, [canonico, *[c for c in _candidatos_vocabulario(vocabulario, texto) if c != canonico]][:3]
    return canonico, "aproximado", [canonico]


# ---------------------------------------------------------------- conversão de campo da ficha

def origem_do_campo(campo, e_formula=False):
    """Colunas de julgamento digitadas por pessoa entram como 'humano'; as demais, 'migrado'. Célula de fórmula
    nunca é 'humano' (ninguém a digitou)."""
    if campo in ficha.CAMPOS_DE_JULGAMENTO and not e_formula:
        return "humano"
    return "migrado"


def converter_campo(campo, bruto, formato_celula=None, epoch=None):
    """Converte o valor bruto de uma célula/trecho para o valor da ficha.
    -> {"valor": valor | None, "avisos": [(nivel, codigo, mensagem, candidatos)], "extras": {...}}
    O valor sai exatamente como `ficha.definir` o guardaria. Vazio e placeholder ("-") viram valor None sem aviso."""
    saida = {"valor": None, "avisos": [], "extras": {}}
    rotulo = ficha.CAMPOS[campo][0]
    _, _, tipo, vocab = ficha.CAMPOS[campo]
    if vazio(bruto):
        return saida
    if tipo == "data":
        valor, problema = converter_data(bruto, epoch)
        if problema:
            motivo = "tem mais de uma data diferente" if problema == "ambigua" else "não é uma data válida"
            saida["avisos"].append(("atencao", "data_invalida", f"{rotulo}: {limpar_texto(bruto)!r} {motivo}; campo deixado vazio.", []))
        saida["valor"] = valor
    elif tipo == "dinheiro":
        valor, problema = converter_dinheiro(bruto)
        if problema:
            motivo = "tem mais de um valor" if problema == "ambiguo" else "não é um valor em reais"
            saida["avisos"].append(("atencao", "valor_invalido", f"{rotulo}: {limpar_texto(bruto)!r} {motivo}; campo deixado vazio.", []))
        saida["valor"] = valor
    elif tipo == "numero":
        valor, problema = converter_numero(bruto, percentual=(campo == "percentual_exito"), formato_celula=formato_celula)
        if problema:
            saida["avisos"].append(("atencao", "valor_invalido", f"{rotulo}: {limpar_texto(bruto)!r} não é um número; campo deixado vazio.", []))
        saida["valor"] = valor
    elif tipo == "sim_nao":
        valor, problema = converter_sim_nao(bruto)
        if problema:
            saida["avisos"].append(("atencao", "valor_invalido", f"{rotulo}: {limpar_texto(bruto)!r} não é Sim nem Não; campo deixado vazio.", []))
        saida["valor"] = valor
    elif vocab:
        texto = limpar_texto(bruto)
        if eh_vazio_logico(texto, amplo=False):
            return saida
        if vocab == "momento_atual":
            base, qualificador = separar_qualificador(texto)
            canonico, certeza, candidatos = normalizar_rotulo("momento_atual", base, estrito=True)
            if canonico is None and qualificador is not None:   # parênteses que fazem parte do rótulo?
                canonico, certeza, candidatos = normalizar_rotulo("momento_atual", texto, estrito=True)
                qualificador = None if canonico else qualificador
            if canonico is None:
                saida["avisos"].append(("atencao", "momento_fora_do_vocabulario",
                                        f"Momento atual {texto!r} não está no vocabulário; campo deixado vazio. "
                                        "Confirme qual dos momentos conhecidos corresponde.", candidatos))
                return saida
            saida["valor"] = canonico
            if qualificador:
                saida["extras"]["momento_qualificador"] = qualificador
                saida["avisos"].append(("info", "momento_com_qualificador",
                                        f"Momento atual {canonico!r} com qualificador ({qualificador}); o qualificador foi guardado à parte.", [qualificador]))
            if certeza == "aproximado":
                saida["avisos"].append(("info", "rotulo_aproximado", f"Momento atual {texto!r} lido como {canonico!r}.", [canonico]))
        else:
            canonico, certeza, candidatos = normalizar_rotulo(vocab, texto)
            if canonico is None:
                saida["avisos"].append(("atencao", "rotulo_fora_do_vocabulario",
                                        f"{rotulo}: {texto!r} não está no vocabulário; campo deixado vazio.", candidatos))
                return saida
            saida["valor"] = canonico
            if certeza == "aproximado":
                saida["avisos"].append(("info", "rotulo_aproximado", f"{rotulo}: {texto!r} lido como {canonico!r}.", [canonico]))
    else:
        if isinstance(bruto, float) and bruto.is_integer():
            bruto = int(bruto)
        texto = re.sub(r"[ \t]+", " ", limpar_texto(bruto))
        if eh_vazio_logico(texto, amplo=False):
            return saida
        saida["valor"] = texto.upper() if campo == "uf" and len(texto) == 2 else texto
    return saida


def montar_campo(campo, valor, origem):
    return {"valor": valor, "origem": origem}


# ---------------------------------------------------------------- texto de andamentos

_DATA = r"(?:\d{1,2}/\d{1,2}/\d{4}|\d{1,2}\s+de\s+(?:" + _MES_RE + r")\s+de\s+\d{4})"
_ABRE = r"(?:Em(?:\s+data\s+de)?|Até(?:\s+o\s+dia)?|No\s+dia|Aos?|Na\s+data\s+de)"
# Início de andamento (ver _inicios): expressão com maiúscula inicial, no começo do texto ou depois de ponto final /
# quebra de linha; "em 14/10/2026" no meio de uma frase (audiência, prazo) NÃO conta.
FECHO = re.compile(r"(?:" + _ABRE + r")\s+(" + _DATA + r")\s*,?\s*sem\s+(?:novas\s+)?"
                   r"(?:atualiza(?:ções|coes|ção|cao)|andamentos?|movimenta(?:ções|coes)|novidades?)\s*\.?\s*$", re.I)
FECHO_INVERTIDO = re.compile(r"Sem\s+(?:novas\s+)?(?:atualiza(?:ções|coes|ção|cao)|andamentos?|movimenta(?:ções|coes)|novidades?)"
                             r"\s+(?:até|ate|em|desde)\s+(" + _DATA + r")\s*\.?\s*$", re.I)


def _data_do_marcador(texto):
    ds = datas_no_texto(texto)
    return ds[0][0] if ds else None


def _inicios(texto):
    """[(inicio, fim_do_marcador, date)] dos marcadores de andamento (maiúscula inicial, começo de frase)."""
    achados = []
    for m in re.finditer(r"(" + _ABRE + r")\s+(" + _DATA + r")", texto):
        antes = texto[:m.start()].rstrip(" \t ")
        if antes and antes[-1] not in ".!?;:)”\"\n" and not texto[:m.start()].endswith("\n"):
            continue
        d = _data_do_marcador(m.group(2))
        achados.append((m.start(), m.end(), d, m.group(2)))
    return achados    # (início do marcador, fim da data, date, texto da data)


def analisar_andamentos(texto):
    """Lê o texto corrido de andamentos ("Em 18/06/2026, foi proferida sentença. Em 20/07/2026, ...").
    -> {"texto": texto sem o fecho final, "andamentos": [{"data": ISO, "texto", "inicio"}], "fecho": ISO | None,
        "ultimo": ISO | None, "avisos": [(nivel, codigo, mensagem)]}.
    `ultimo` = maior data dos andamentos (o fecho 'Em DD/MM/AAAA, sem atualizações.' não conta; datas no meio da
    frase, como prazos e audiências futuras, também não)."""
    t = limpar_texto(texto)
    saida = {"texto": t, "andamentos": [], "fecho": None, "ultimo": None, "avisos": []}
    if not t:
        return saida
    marcas = _inicios(t)
    segmentos = []
    for i, (ini, _fim, d, _bruto) in enumerate(marcas):
        fim = marcas[i + 1][0] if i + 1 < len(marcas) else len(t)
        segmentos.append((ini, fim, d))
    datas, fechos = [], []
    for k, (ini, fim, d) in enumerate(segmentos):
        trecho = t[ini:fim].strip()
        eh_fecho = bool(FECHO.fullmatch(trecho))
        if d is None:
            continue
        if eh_fecho:
            fechos.append((k, ini, d))
            continue
        corpo = re.sub(r"^" + _ABRE + r"\s+" + _DATA + r"\s*,?\s*", "", trecho, count=1)
        saida["andamentos"].append({"data": d.isoformat(), "texto": corpo.strip(), "inicio": ini,
                                    "data_fim": ini + len(re.match(r"(?:" + _ABRE + r")\s+" + _DATA, trecho).group(0))})
        datas.append(d)
    # fecho no fim do texto: sai do texto lido
    corte = None
    if segmentos and fechos and fechos[-1][0] == len(segmentos) - 1:
        corte = fechos[-1][1]
        saida["fecho"] = fechos[-1][2].isoformat()
        fechos = fechos[:-1]
    else:
        m = FECHO_INVERTIDO.search(t)
        if m:
            d = _data_do_marcador(m.group(1))
            corte = m.start()
            saida["fecho"] = d.isoformat() if d else None
    if corte is not None:
        saida["texto"] = t[:corte].rstrip()
    if fechos:
        saida["avisos"].append(("info", "fecho_fora_do_fim",
                                "Há uma frase de 'sem atualizações' no meio do texto; ela foi mantida no histórico e ignorada no cálculo do último andamento."))
    if datas:
        saida["ultimo"] = max(datas).isoformat()
    else:
        todas = [d for d, _, _ in datas_no_texto(saida["texto"])]
        if todas:
            saida["ultimo"] = max(todas).isoformat()
            saida["avisos"].append(("info", "andamentos_sem_marcador",
                                    "O texto de andamentos não usa o padrão 'Em DD/MM/AAAA, ...'; o último andamento foi tomado da maior data do texto."))
    return saida


# ---------------------------------------------------------------- verificação final

def finalizar(rel):
    """Confere o relatório lido: números repetidos entre processos (e entre principal e vinculado) viram aviso;
    garante as chaves do contrato. Devolve o próprio `rel`."""
    por_numero = {}
    for p in rel["processos"]:
        por_numero.setdefault(p["numero"], []).append(("principal", p))
        for v in p["vinculados"]:
            por_numero.setdefault(v["numero"], []).append(("vinculado", p))
    for numero, usos in por_numero.items():
        if len(usos) < 2:
            continue
        onde = [f"{p['origem_no_arquivo'] or '?'} ({papel})" for papel, p in usos]
        principais = [u for u in usos if u[0] == "principal"]
        if len(principais) > 1:
            rel["avisos"].append(aviso("atencao", "numero_repetido", onde[0],
                                       f"O número {numero} aparece como processo principal mais de uma vez "
                                       f"({'; '.join(onde)}). Os dois registros foram mantidos; confirme qual vale "
                                       "(pode ser a mesma ação contada duas vezes).", [numero]))
        else:
            rel["avisos"].append(aviso("atencao", "numero_em_dois_lugares", onde[0],
                                       f"O número {numero} aparece em mais de um lugar ({'; '.join(onde)}), "
                                       "como principal e como vinculado. Confirme como deve ser agrupado.", [numero]))
    for chave_ in ("cliente", "data_base"):
        rel.setdefault(chave_, None)
    for chave_ in ("processos", "colunas_sem_destino", "avisos"):
        rel.setdefault(chave_, [])
    rel.setdefault("parametros", {})
    return rel
