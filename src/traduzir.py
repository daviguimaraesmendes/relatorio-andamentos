"""Parte determinística (sem IA): traduz movimentação, classifica documento e
descobre quem é o autor de uma petição.

Tudo aqui é regra fixa -- nada inventa conteúdo. A IA só entra depois, para
dizer o que o documento diz ("dizendo X").
"""
import re
import sys

from comum import MOVIMENTOS_FILE, config, load_json, normalizar

# "189001119 - Petição (outras) - PFN.pdf" -> id, tipo, descrição, extensão
NOME_DOC = re.compile(r"^\s*(?P<id>\d+)\s+-\s+(?P<tipo>.+?)\s+-\s+(?P<descricao>.*?)(?:\.(?P<ext>pdf|html?))?\s*$", re.I)
DATA_FINAL = re.compile(r"\s*\((\d{2}/\d{2}/\d{4})(?: \d{2}:\d{2}:\d{2})?\)\s*$")

CATEGORIAS = [
    ("decisao", r"senten[cç]a|ac[oó]rd[aã]o|decis[aã]o|despacho|voto|ementa"),
    ("peticao", r"peti[cç][aã]o|contesta[cç][aã]o|r[eé]plica|contra-?raz[oõ]es|contraminuta|recurso|apela[cç][aã]o|"
                r"agravo|embargos|manifesta[cç][aã]o|impugna[cç][aã]o|memoriais|alega[cç][oõ]es|inicial|parecer"),
    ("audiencia", r"audi[eê]ncia|termo de sess[aã]o|ata"),
    ("comunicacao", r"certid[aã]o|intima[cç][aã]o|ato ordinat[oó]rio|mandado|of[ií]cio|aviso|carta|cita[cç][aã]o"),
]


def separar_nome_documento(nome):
    m = NOME_DOC.match(nome)
    if not m:
        return {"id": None, "tipo": nome.strip(), "descricao": "", "ext": None}
    d = m.groupdict()
    d["ext"] = (d["ext"] or "").lower() or None
    return d


def categoria(tipo):
    for nome, padrao in CATEGORIAS:
        if re.search(padrao, tipo, re.I):
            return nome
    return "outro"


def traduzir_movimento(sinal):
    """'Conclusos para decisão (31/08/2026 13:20:05)' -> (frase, relevante, data).
    Movimento que nenhuma regra cobre volta com frase None: vai para revisão
    com alerta, em vez de ganhar uma frase genérica que esconda o que houve."""
    data = None
    m = DATA_FINAL.search(sinal)
    if m:
        data = m.group(1)
        sinal = sinal[: m.start()]
    for regra in load_json(MOVIMENTOS_FILE, {}).get("movimentos", []):
        m = re.search(regra["padrao"], sinal.strip(), re.I)
        if m:
            grupos = {k: (v or "").strip() for k, v in m.groupdict().items()}
            grupos.update({k: v.lower() for k, v in grupos.items() if k in ("tipo", "resultado", "pedido")})
            # "Decorrido prazo de X em 02/09/2026" vale para 02/09, não para o dia em que foi listado
            return regra["frase"].format(**grupos), regra["relevante"], grupos.get("data") or data
    return None, True, data


ASSINADO_POR = re.compile(r"Assinado eletronicamente por:\s*([^\n\-–]+)", re.I)


def autoria(texto, tipo, descricao=""):
    """Quem assinou. 'nos' se o carimbo de assinatura do PJe ou o fecho do
    documento (fim do texto) traz nome ou OAB de advogado do escritório --
    só o fim, porque o nome do escritório pode aparecer citado no meio da
    petição da parte contrária. 'contraria' só com assinatura de terceiro
    identificada; sem isso, 'outro' (vai para a revisão com alerta)."""
    cat = categoria(tipo)
    if cat == "decisao":
        return "juizo"
    if cat == "comunicacao":
        return "cartorio"
    if not texto:
        return "outro"  # sem texto não dá para saber quem assinou; não chutar
    assinantes = [normalizar(n) for n in ASSINADO_POR.findall(texto)]
    onde_procurar = normalizar(texto[-4000:]) + " " + " ".join(assinantes)
    for ident in config().get("identificadores_escritorio", []):
        if re.fullmatch(r"[\d.]+", ident):  # número de OAB: só vale ao lado de "OAB"
            if re.search(r"oab[^0-9]{0,10}" + re.escape(ident) + r"(?!\d)", onde_procurar):
                return "nos"
        elif normalizar(ident) and normalizar(ident) in onde_procurar:
            return "nos"
    alvo = normalizar(f"{tipo} {descricao}")
    if "ministerio publico" in alvo or re.search(r"\bmp\b", alvo):
        return "mp"
    if re.search(r"\bperit|laudo", alvo):
        return "perito"
    if cat == "peticao" and (assinantes or re.search(r"\boab\b", normalizar(texto[-1500:]))):
        return "contraria"
    return "outro"


SUJEITO = {
    "nos": "Apresentamos",
    "contraria": "A parte contrária apresentou",
    "mp": "O Ministério Público apresentou",
    "perito": "O perito apresentou",
}

VERBO_JUIZO = [  # voz das planilhas do escritório: "Em 25/09/2026 foi proferida decisão determinando..."
    (r"senten[cç]a", "Foi proferida sentença"),
    (r"ac[oó]rd[aã]o|voto|ementa", "Foi proferido acórdão"),
    (r"decis[aã]o", "Foi proferida decisão"),
    (r"despacho", "Foi proferido despacho"),
]


def _nome_curto(partes):
    """Primeira parte contrária, em caixa normal, para caber na frase
    ('ESTADO DO CEARA; X' -> 'Estado do Ceara'). O DJEN publica nomes sem
    acento; para corrigir, ajuste 'parte_contraria' na carteira."""
    nome = (partes or "").split(";")[0].strip()
    if nome.isupper():
        nome = " ".join(p.capitalize() for p in nome.lower().split())
        nome = re.sub(r"\b(Do|Da|De|Dos|Das|E)\b", lambda m: m.group(1).lower(), nome)
        nome = re.sub(r"\b(Ltda|S\.?a\.?|Eireli|Me|Epp)\b", lambda m: m.group(1).upper(), nome)
    return nome[:60]


def frase_documento(tipo, descricao, quem, parte_contraria=""):
    """Primeira metade da linha do relatório ('O juiz proferiu decisão'),
    sempre por regra. A IA completa com 'dizendo que...'."""
    rotulo = tipo.strip()
    if descricao and normalizar(descricao) != normalizar(tipo):
        rotulo = f"{tipo.strip()} – {descricao.strip()}"
    if quem == "juizo":
        for padrao, frase in VERBO_JUIZO:
            if re.search(padrao, tipo, re.I):
                return f"{frase}."
        return f"O juízo juntou {rotulo.lower()}."
    if quem == "contraria" and parte_contraria:
        return f"A parte contrária ({_nome_curto(parte_contraria)}) apresentou {rotulo.lower()}."
    if quem in SUJEITO:
        return f"{SUJEITO[quem]} {rotulo.lower()}."
    if quem == "cartorio":
        verbo = "expediu" if re.search(r"ato ordinat|certid|intima|mandado|of[ií]cio|edital", tipo, re.I) else "juntou"
        return f"O cartório {verbo} {rotulo.lower()}."
    return f"Foi juntado ao processo: {rotulo}."


if __name__ == "__main__":
    for linha in sys.argv[1:] or sys.stdin.read().splitlines():
        print(traduzir_movimento(linha), "|", linha)
