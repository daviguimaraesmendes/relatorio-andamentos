"""Parâmetros de redação dos ANDAMENTOS, colhidos de um relatório modelo do escritório, e um verificador de estilo.

    python estilo_andamentos.py --colher relatorio.docx|planilha.xlsx     # mede o estilo de um relatório existente
    python estilo_andamentos.py --avaliar "texto do andamento" [--data-base 18/09/2026]

`colher` usa o leitor de relatórios (`leitores.ler`), mede cada texto de andamentos e imprime SÓ números e termos
genéricos (nada de nome de parte, de processo ou de valor), para calibrar `PARAMETROS` com outros relatórios do
escritório. `avaliar(texto, data_base)` aplica os parâmetros a um texto e devolve avisos (nunca reescreve nada):
serve de régua para o que a IA local escreve e para quem revisa.

Os números de PARAMETROS vêm do relatório modelo de 18/09/2026 (24 processos, 1 cliente, condomínio, TJCE). São a
medida de UM cliente: use `colher` em mais relatórios antes de tratar como regra geral. Detalhes e exemplos
fictícios em docs/fase2/estilo-andamentos.md.
"""
import collections
import re
import statistics
import sys

DATA = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
DATA_EXTENSO = re.compile(r"\b\d{1,2}\s+de\s+(?:janeiro|fevereiro|mar[cç]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro)\s+de\s+\d{4}", re.I)
INICIO_DATADO = re.compile(r"(?:^|[.;]\s+)Em\s+(\d{2})/(\d{2})/(\d{4}),", re.M)
PRIMEIRA_PESSOA = re.compile(r"\b\w+(?:amos|emos|imos)\b", re.I)
PARTICIPIO_DE_ABERTURA = re.compile(r"^\s*(?:Apresentad|Requerid|Deferid|Indeferid|Determinad|Juntad|Expedid|Homologad|Rejeitad|Concedid|"
                                    r"Intimad|Julgad|Ajuizad|Decretad|Ordenad|Pedid|Recolhid|Identificad|Redistribuíd|Proferid)[oa]s?\b", re.I)
VALOR = re.compile(r"R\$\s*[\d.]+(?:,\d{2})?(?:\s*mil)?")
PERCENTUAL = re.compile(r"\d+(?:,\d+)?\s?%")
PROCESSO_CITADO = re.compile(r"\bprocesso\s+n[º°o]", re.I)
LEI_CITADA = re.compile(r"\b(?:Lei|Portaria|Resolução|Provimento)\s+(?:Conjunta\s+)?n[º°o]", re.I)
FECHO = re.compile(r"Em\s+(\d{2}/\d{2}/\d{4}),\s+sem\s+atualiza[cç][õo]es\.?\s*$", re.I)
VAGO = re.compile(r"analisando o pedido|dando andamento ao processo|apreciando a quest|seguindo seu curso|aguardando os ulteriores", re.I)
TERCEIRA_PESSOA_DO_ESCRITORIO = re.compile(r"\b(?:o|nosso)\s+escrit[oó]rio\b|\bos\s+advogados\s+do\s+(?:condom[ií]nio|cliente)\b", re.I)

# Medidas do relatório modelo (set/2026). `faixa` é o intervalo que cobre os textos reais sem os extremos.
PARAMETROS = {
    "palavras": {"minimo": 58, "mediana": 87, "media": 97, "maximo": 181, "faixa": (50, 200)},
    "datas_por_texto": {"media": 4.7},
    "oracoes_por_texto": {"media": 6.9},           # separadas por ponto ou ponto e vírgula
    "formato_da_data": "DD/MM/AAAA",              # nunca por extenso; mês/ano ("11/2025") só para vários atos do mesmo mês
    "estrutura": ("abertura sem data (o que foi pedido e as tutelas)", "atos datados em ordem cronológica",
                  "fecho 'Em <data-base>, sem atualizações.' quando nada mudou desde o último ato"),
    "voz": {"juizo_e_partes": "particípio/passiva ('Deferida a tutela...', 'foi proferida sentença...', 'a Mistral apelou')",
            "escritorio": "primeira pessoa do plural ('apresentamos contrarrazões', 'requeremos', 'informamos', 'comunicamos')",
            "cliente": "terceira pessoa, pelo nome curto ('o Condomínio')"},
    "dados_concretos": ("valores 'R$ 1.979,91'", "percentuais", "números de unidades e de processos relacionados ('processo nº ...')",
                        "prazos ('no prazo de 3 dias, sob pena de penhora')", "norma só quando decide o caso ('Lei nº ...')"),
}


def _oracoes(texto):
    return [o for o in re.split(r"[.;]\s+", texto.strip()) if o.strip()]


def metricas(texto):
    """Números de UM texto de andamentos (sem o fecho)."""
    sem_fecho = FECHO.sub("", texto.strip()).strip()
    datas = DATA.findall(sem_fecho)
    oracoes = _oracoes(sem_fecho)
    primeira = oracoes[0] if oracoes else ""
    return {
        "palavras": len(sem_fecho.split()), "datas": len(datas), "oracoes": len(oracoes),
        "abertura_sem_data": bool(primeira) and not DATA.search(primeira),
        "abertura_participial": bool(PARTICIPIO_DE_ABERTURA.match(primeira)),
        "primeira_pessoa_plural": len(PRIMEIRA_PESSOA.findall(sem_fecho)),
        "valores": len(VALOR.findall(sem_fecho)), "percentuais": len(PERCENTUAL.findall(sem_fecho)),
        "processos_citados": len(PROCESSO_CITADO.findall(sem_fecho)), "normas_citadas": len(LEI_CITADA.findall(sem_fecho)),
        "atos_datados": len(INICIO_DATADO.findall(sem_fecho)),
    }


def avaliar(texto, data_base=None):
    """Avisos de estilo para um texto de andamentos: [{"codigo", "mensagem"}]. Vazio = dentro do padrão.
    `data_base` ('DD/MM/AAAA'): confere o fecho 'Em <data-base>, sem atualizações.' se houver."""
    avisos = []

    def av(codigo, mensagem):
        avisos.append({"codigo": codigo, "mensagem": mensagem})
    texto = (texto or "").strip()
    if not texto:
        return [{"codigo": "estilo_vazio", "mensagem": "Texto de andamentos vazio."}]
    m = metricas(texto)
    faixa = PARAMETROS["palavras"]["faixa"]
    if m["palavras"] < faixa[0]:
        av("estilo_curto", f"Texto curto ({m['palavras']} palavras; o padrão do escritório fica entre {faixa[0]} e {faixa[1]}): faltam o contexto, o motivo ou os valores?")
    elif m["palavras"] > faixa[1]:
        av("estilo_longo", f"Texto longo ({m['palavras']} palavras; o padrão fica entre {faixa[0]} e {faixa[1]}): resumir o que for repetição.")
    if DATA_EXTENSO.search(texto):
        av("estilo_data_por_extenso", "Data por extenso: o padrão é DD/MM/AAAA.")
    if m["datas"] == 0:
        av("estilo_sem_data", "Nenhuma data: os atos são narrados com a data ('Em DD/MM/AAAA, ...').")
    datas = [(int(a), int(b), int(c)) for a, b, c in INICIO_DATADO.findall(texto)]
    ordenadas = [(c, b, a) for a, b, c in datas]
    if ordenadas != sorted(ordenadas):
        av("estilo_fora_de_ordem", "Os atos datados não estão em ordem cronológica.")
    if TERCEIRA_PESSOA_DO_ESCRITORIO.search(texto):
        av("estilo_voz_do_escritorio", "O escritório aparece em terceira pessoa; o padrão é a primeira do plural ('apresentamos', 'requeremos').")
    if VAGO.search(texto):
        av("estilo_frase_vaga", "Frase vaga ('analisando o pedido', 'dando andamento'): dizer o que foi decidido ou pedido.")
    fecho = FECHO.search(texto)
    if fecho and data_base and fecho.group(1) != data_base:
        av("estilo_fecho_data_base", f"O fecho diz {fecho.group(1)}, mas a data-base é {data_base}.")
    return avisos


def colher(caminho):
    """Mede o estilo de um relatório (`.docx` modelo A ou `.xlsx` modelo B) e devolve agregados SEM dado identificável."""
    import leitores
    lido = leitores.ler(caminho)
    textos = [(p.get("andamentos_texto") or "").strip() for p in lido["processos"]]
    textos = [t for t in textos if t]
    ms = [metricas(t) for t in textos]
    if not ms:
        return {"textos": 0}

    def resumo(chave):
        valores = [m[chave] for m in ms]
        return {"minimo": min(valores), "mediana": statistics.median(valores), "media": round(statistics.mean(valores), 1), "maximo": max(valores)}
    abertura = collections.Counter()
    for t in textos:
        primeira = (_oracoes(t) or [""])[0]
        abertura[(re.match(r"\s*(\w+)", primeira) or [None, ""])[1]] += 1
    return {"textos": len(ms), "palavras": resumo("palavras"), "datas": resumo("datas"), "oracoes": resumo("oracoes"),
            "com_fecho": sum(1 for p in lido["processos"] if p.get("fecho")),
            "abertura_sem_data": sum(m["abertura_sem_data"] for m in ms), "abertura_participial": sum(m["abertura_participial"] for m in ms),
            "verbos_na_primeira_pessoa_do_plural": sum(m["primeira_pessoa_plural"] for m in ms),
            "textos_com_valor_em_reais": sum(1 for m in ms if m["valores"]), "textos_com_percentual": sum(1 for m in ms if m["percentuais"]),
            "textos_que_citam_processo": sum(1 for m in ms if m["processos_citados"]), "textos_que_citam_norma": sum(1 for m in ms if m["normas_citadas"]),
            "primeiras_palavras": abertura.most_common(8),
            "fora_do_padrao": collections.Counter(a["codigo"] for t in textos for a in avaliar(t)).most_common()}


def main():
    a = sys.argv[1:]
    if "--colher" in a:
        import json
        print(json.dumps(colher(a[a.index("--colher") + 1]), ensure_ascii=False, indent=1))
    elif "--avaliar" in a:
        base = a[a.index("--data-base") + 1] if "--data-base" in a else None
        for aviso in avaliar(a[a.index("--avaliar") + 1], base) or [{"codigo": "ok", "mensagem": "Dentro do padrão."}]:
            print(f"{aviso['codigo']}: {aviso['mensagem']}")
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
