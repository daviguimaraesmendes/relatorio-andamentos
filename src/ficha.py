"""Ficha v2: o registro único de cada processo, de onde saem os três entregáveis
(texto, planilha e dashboard). Substitui o item "magro" da carteira.json da
Fase 1 (número, tribunal, cliente, polo, parte contrária, responsável) sem
quebrá-lo: os campos antigos continuam planos, no mesmo arquivo, e o resto vai
em "campos", cada um com a sua ORIGEM.

    {"v": 2, "numero": "0000000-00.0000.0.00.0000", "tribunal": "TJCE", "cliente": "...",
     "polo_cliente": "passivo", "parte_contraria": "...", "responsavel": "...", "ativo": true,
     "vinculados": [{"numero": "...", "tipo": "agravo"}],
     "linha_de_base": {"data_base": "2026-09-18", "andamentos_texto": "...", "arquivo": "..."},
     "campos": {"vara": {"valor": "...", "origem": "coletado", "em": "2026-10-07T10:00:00",
                         "evidencia": "capa do processo, jus.br"}, ...}}

Origem de cada campo e quem vence (maior prioridade nunca é sobrescrita por menor):

    humano (5)  digitado/aprovado por pessoa, inclusive o que já estava lançado à mão
                num relatório migrado nas colunas de julgamento
    coletado (4) lido do tribunal/DJEN
    migrado (3) lido de um relatório antigo (texto de andamentos, colunas objetivas)
    derivado (2) calculado de outros campos por regra (ex.: ativo a partir do momento atual)
    sugerido (1) proposta automática dos campos de julgamento (julgamento.py); só vira
                definitiva quando uma pessoa aprova (passa a "humano")

Datas ficam em ISO (AAAA-MM-DD); dinheiro, em texto decimal com ponto e 2 casas
("1234.56"), para não ter erro de ponto flutuante. Use dinheiro() e data() para ler.
"""
import datetime
import re
from decimal import Decimal, InvalidOperation

import carteira as cart
import comum
import taxonomia

VERSAO = 2
PRIORIDADE = {"humano": 5, "coletado": 4, "migrado": 3, "derivado": 2, "sugerido": 1}

# Campos que a Fase 1 já guarda planos na carteira.json (continuam espelhados, para o código antigo).
PLANOS = ("cliente", "polo_cliente", "parte_contraria", "responsavel", "contato", "apelido")

# nome: (rótulo, grupo, tipo, vocabulário ou None)   tipo: texto | data | dinheiro | numero | sim_nao | lista
CAMPOS = {
    # identificação e gestão
    "cliente": ("Cliente", "gestao", "texto", None),
    "apelido": ("Apelido do processo", "gestao", "texto", None),
    "responsavel": ("Responsável", "gestao", "texto", None),
    "contato": ("Contato", "gestao", "texto", None),
    "observacoes": ("Observações", "gestao", "texto", None),
    # partes
    "polo_cliente": ("Polo do cliente", "partes", "texto", "polo"),
    "autores": ("Autor(es)", "partes", "texto", None),
    "reus": ("Réu(s)", "partes", "texto", None),
    "parte_contraria": ("Parte contrária", "partes", "texto", None),
    "outras_partes": ("Outra(s) parte(s)", "partes", "texto", None),
    "terceirizado": ("Reclamante terceirizado?", "partes", "sim_nao", None),
    # capa
    "vara": ("Vara / Juízo", "capa", "texto", None),
    "municipio": ("Município", "capa", "texto", None),
    "uf": ("UF", "capa", "texto", None),
    "data_ajuizamento": ("Data do ajuizamento", "capa", "data", None),
    "data_citacao": ("Data de citação", "capa", "data", None),
    "classe": ("Classe", "capa", "texto", None),
    "assunto": ("Assunto", "capa", "texto", None),
    "area": ("Área do direito", "capa", "texto", "area"),
    "materia_principal": ("Matéria principal", "capa", "texto", None),
    "objeto": ("Objeto", "capa", "texto", None),
    "valor_causa": ("Valor da causa", "capa", "dinheiro", None),
    # situação
    "momento_atual": ("Momento atual do processo", "situacao", "texto", "momento_atual"),
    "situacao": ("Situação", "situacao", "texto", "situacao"),
    "fase": ("Fase", "situacao", "texto", "fase"),
    "ultimo_andamento": ("Data do último andamento", "situacao", "data", None),
    "houve_recurso": ("Houve recurso da empresa?", "situacao", "sim_nao", None),
    # julgamento
    "resultado": ("Resultado", "julgamento", "texto", "resultado"),
    "probabilidade": ("Probabilidade (do resultado)", "julgamento", "texto", "probabilidade"),
    "valor_arbitrado": ("Valor arbitrado em juízo", "julgamento", "dinheiro", None),
    "valor_estimado": ("Valor estimado", "julgamento", "dinheiro", None),
    "valor_execucao": ("Valor da execução", "julgamento", "dinheiro", None),
    "valor_acordo": ("Valor do acordo", "julgamento", "dinheiro", None),
    "valor_economizado": ("Valor economizado", "julgamento", "dinheiro", None),
    "custas": ("Custas processuais", "julgamento", "dinheiro", None),
    "depositos_recursais": ("Depósitos recursais", "julgamento", "dinheiro", None),
    "garantias": ("Garantias processuais", "julgamento", "dinheiro", None),
    "data_transito": ("Data do trânsito em julgado", "julgamento", "data", None),
    "taxa_resolucao_dias": ("Taxa de resolução (dias)", "julgamento", "numero", None),
    "percentual_exito": ("Percentual de êxito", "julgamento", "numero", None),
}
# O que é "julgamento humano": o leitor de relatórios grava estes campos com origem "humano"
# (alguém os digitou no relatório antigo) e julgamento.py só os sugere quando estão vazios.
CAMPOS_DE_JULGAMENTO = tuple(n for n, c in CAMPOS.items() if c[1] == "julgamento")


def agora():
    return datetime.datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- conversões

def data(valor):
    """datetime.date de um valor ISO (ou None)."""
    if not valor:
        return None
    try:
        return datetime.date.fromisoformat(str(valor)[:10])
    except ValueError:
        return None


def data_br(valor):
    d = data(valor)
    return d.strftime("%d/%m/%Y") if d else ""


def parse_data(texto):
    """'18/09/2026', '2026-09-18' ou date/datetime -> 'AAAA-MM-DD'; None se não der."""
    if isinstance(texto, datetime.datetime):
        return texto.date().isoformat()
    if isinstance(texto, datetime.date):
        return texto.isoformat()
    s = str(texto or "").strip()
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    try:
        if m:
            return datetime.date(int(m[3]), int(m[2]), int(m[1])).isoformat()
        if re.match(r"\d{4}-\d{2}-\d{2}", s):
            return datetime.date.fromisoformat(s[:10]).isoformat()
    except ValueError:
        pass
    return None


def parse_dinheiro(texto):
    """'R$ 1.234,56', '1,234.56', 1234.5, Decimal -> '1234.56'; None se não der."""
    if texto is None or texto == "":
        return None
    if isinstance(texto, (int, float, Decimal)):
        numero = Decimal(str(texto))
    else:
        s = re.sub(r"[^0-9.,-]", "", str(texto))
        if not re.search(r"\d", s):
            return None
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
        elif "," in s:
            s = s.replace(",", ".")
        elif s.count(".") > 1 or re.search(r"\.\d{3}$", s):
            s = s.replace(".", "")
        try:
            numero = Decimal(s)
        except InvalidOperation:
            return None
    return f"{numero.quantize(Decimal('0.01')):.2f}"


def dinheiro(valor):
    """Decimal de um valor monetário da ficha (ou None)."""
    try:
        return Decimal(valor) if valor not in (None, "") else None
    except InvalidOperation:
        return None


def dinheiro_br(valor):
    d = dinheiro(valor)
    if d is None:
        return ""
    inteiro, frac = f"{d:.2f}".split(".")
    sinal = "-" if inteiro.startswith("-") else ""
    inteiro = inteiro.lstrip("-")
    grupos = []
    while inteiro:
        grupos.insert(0, inteiro[-3:])
        inteiro = inteiro[:-3]
    return f"R$ {sinal}{'.'.join(grupos) or '0'},{frac}"


# ---------------------------------------------------------------- criação e acesso

def nova_ficha(numero, **campos):
    """Ficha vazia; campos opcionais entram com origem 'migrado' (use definir() para outra origem)."""
    numero_ok, tribunal = _numero_e_tribunal(numero)
    ficha = {"v": VERSAO, "numero": numero_ok, "tribunal": tribunal, "ativo": True, "vinculados": [],
             "linha_de_base": None, "campos": {}}
    for nome, valor in campos.items():
        definir(ficha, nome, valor, "migrado")
    return ficha


def _numero_e_tribunal(numero):
    validos, _ = cart.numeros_no_texto(str(numero))
    if validos:
        return validos[0]
    return str(numero).strip(), ""


def de_carteira_v1(item):
    """Item da carteira.json da Fase 1 -> ficha v2 (sem perda; campos antigos ficam planos)."""
    if item.get("v") == VERSAO:
        return item
    ficha = dict(item)
    ficha.update(v=VERSAO, vinculados=item.get("vinculados", []), linha_de_base=item.get("linha_de_base"),
                 campos=dict(item.get("campos", {})))
    ficha.setdefault("ativo", True)
    for nome in PLANOS:
        if item.get(nome) and nome not in ficha["campos"]:
            ficha["campos"][nome] = {"valor": item[nome], "origem": "migrado", "em": item.get("incluido_em") or agora()}
    return ficha


def obter(ficha, nome, padrao=None):
    """Valor atual do campo (campos[nome] ou, para os planos antigos, a chave plana)."""
    c = ficha.get("campos", {}).get(nome)
    if c is not None and c.get("valor") not in (None, ""):
        return c["valor"]
    if nome in PLANOS and ficha.get(nome) not in (None, ""):
        return ficha[nome]
    return padrao


def origem(ficha, nome):
    c = ficha.get("campos", {}).get(nome)
    if c and c.get("valor") not in (None, ""):
        return c.get("origem")
    return "migrado" if nome in PLANOS and ficha.get(nome) else None


def definir(ficha, nome, valor, origem_nova, evidencia=None, forcar=False):
    """Grava um campo respeitando a prioridade das origens. Volta True se gravou.

    - valor vazio nunca apaga um campo existente (só `limpar` apaga);
    - o valor é normalizado pelo tipo do campo e, quando o campo tem vocabulário,
      pelo vocabulário (rótulo desconhecido NÃO é gravado: volta False);
    - origem de prioridade menor não sobrescreve a maior; igual só sobrescreve se
      o valor já estiver vazio ou `forcar` (ex.: nova coleta do tribunal substitui a anterior).
    """
    if nome not in CAMPOS:
        raise KeyError(f"Campo desconhecido: {nome}")
    if origem_nova not in PRIORIDADE:
        raise ValueError(f"Origem desconhecida: {origem_nova}")
    _, _, tipo, vocab = CAMPOS[nome]
    valor = _normalizar_valor(tipo, vocab, valor)
    if valor in (None, ""):
        return False
    atual_origem, atual = origem(ficha, nome), obter(ficha, nome)
    if atual not in (None, "") and atual_origem:
        pa, pn = PRIORIDADE[atual_origem], PRIORIDADE[origem_nova]
        if pn < pa or (pn == pa and (atual == valor or (not forcar and origem_nova != "humano"))):
            return False  # humano novo sobre humano antigo vale (é o mais recente)
    registro = {"valor": valor, "origem": origem_nova, "em": agora()}
    if evidencia:
        registro["evidencia"] = evidencia
    ficha.setdefault("campos", {})[nome] = registro
    if nome in PLANOS:
        ficha[nome] = valor  # espelho para o código da Fase 1
    return True


def limpar(ficha, nome):
    ficha.get("campos", {}).pop(nome, None)
    if nome in PLANOS:
        ficha[nome] = ""


def _normalizar_valor(tipo, vocab, valor):
    if valor is None or valor == "":
        return None
    if tipo == "data":
        return parse_data(valor)
    if tipo == "dinheiro":
        return parse_dinheiro(valor)
    if tipo == "numero":
        try:
            return float(str(valor).replace(",", ".").replace("%", "").strip())
        except ValueError:
            return None
    if tipo == "sim_nao":
        n = str(valor).strip().lower()
        return {"sim": "Sim", "s": "Sim", "true": "Sim", "1": "Sim", "nao": "Não", "não": "Não", "n": "Não",
                "false": "Não", "0": "Não"}.get(n)
    texto = str(valor).strip()
    if vocab == "momento_atual" and texto.upper() in taxonomia.MOMENTO_ATUAL:
        return texto.upper()
    return taxonomia.normalizar(vocab, texto) if vocab else texto


# ---------------------------------------------------------------- vínculos

def vincular(ficha, numero, tipo):
    """Registra processo vinculado (recurso, agravo, apenso, reajuizamento, mesma ação)."""
    tipo = taxonomia.normalizar("tipo_vinculo", tipo) or tipo
    num, _ = _numero_e_tribunal(numero)
    if num != ficha["numero"] and all(v["numero"] != num for v in ficha["vinculados"]):
        ficha["vinculados"].append({"numero": num, "tipo": tipo})
    return ficha


def todos_os_numeros(ficha):
    """Número principal + vinculados (o relatório trata o conjunto como uma linha)."""
    return [ficha["numero"], *[v["numero"] for v in ficha.get("vinculados", [])]]


# ---------------------------------------------------------------- validação

def validar(ficha):
    """Lista de problemas (texto); vazia = ficha coerente."""
    problemas = []
    validos, invalidos = cart.numeros_no_texto(ficha.get("numero", ""))
    if not validos:
        problemas.append(f"Número CNJ inválido: {ficha.get('numero')!r}")
    for nome, c in ficha.get("campos", {}).items():
        if nome not in CAMPOS:
            problemas.append(f"Campo desconhecido: {nome}")
            continue
        if c.get("origem") not in PRIORIDADE:
            problemas.append(f"{nome}: origem inválida")
        _, _, tipo, vocab = CAMPOS[nome]
        v = c.get("valor")
        if tipo == "data" and not data(v):
            problemas.append(f"{nome}: data inválida ({v!r})")
        if tipo == "dinheiro" and dinheiro(v) is None:
            problemas.append(f"{nome}: valor monetário inválido ({v!r})")
        if vocab and vocab != "momento_atual" and isinstance(v, str) and taxonomia.normalizar(vocab, v) != v:
            problemas.append(f"{nome}: fora do vocabulário ({v!r})")
    ativo, momento = ficha.get("ativo", True), obter(ficha, "momento_atual")
    if momento and taxonomia.momento_ativo(momento) is not None and taxonomia.momento_ativo(momento) != ativo:
        problemas.append(f"'ativo' ({ativo}) conflita com o momento atual ({momento})")
    return problemas


# ---------------------------------------------------------------- arquivo

def carregar(todas=False):
    """Fichas v2 do relatório ativo (converte itens da Fase 1 ao ler; o arquivo só muda ao salvar)."""
    itens = [de_carteira_v1(p) for p in comum.load_json(comum.CARTEIRA_FILE, [])]
    return itens if todas else [f for f in itens if f.get("ativo", True)]


def salvar(fichas):
    comum.save_json(comum.CARTEIRA_FILE, fichas)
