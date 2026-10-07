"""Vocabulários controlados dos relatórios e normalização de rótulos soltos.

Os relatórios do escritório escrevem a mesma coisa de jeitos diferentes
("Reversão Justa Causa", "Reversão da justa causa.", "Parcialmente procedente.").
Cada vocabulário abaixo tem os valores canônicos e, por valor, sinônimos
conhecidos. normalizar(vocabulario, texto) devolve o canônico ou None: nunca
adivinha quando há mais de um candidato.

Os vocabulários são o ponto de partida (Etapa 0); o WS-1 os amplia e permite
editar os sinônimos pelo painel.
"""
from comum import normalizar as _norm


def _chave(texto):
    """Comparação tolerante: sem acento, sem pontuação final, sem espaços sobrando."""
    return _norm(str(texto or "")).strip(" .;:,-–—")


# canônico -> sinônimos (além do próprio canônico)
POLO = {"ativo": ("autor", "autora", "requerente", "exequente", "reclamante", "apelante", "impetrante"),
        "passivo": ("reu", "re", "requerido", "requerida", "executado", "executada", "reclamado", "reclamada",
                    "apelado", "apelada", "impetrado")}

SITUACAO = {"Ativo": ("em andamento", "tramitando"),
            "Encerrado": ("arquivado", "baixado", "baixa definitiva", "finalizado"),
            "Suspenso": ("sobrestado",)}

FASE = {"Conhecimento": (),
        "Recurso": ("recursal", "2o grau", "segundo grau"),
        "Execução": ("execucao", "cumprimento de sentenca", "cumprimento")}

RESULTADO = {"Procedente": ("procedencia", "condenacao"),
             "Parcialmente procedente": ("parcial procedencia", "procedencia parcial", "parcialmente procedente"),
             "Improcedente": ("improcedencia",),
             "Acordo": ("transacao", "homologado acordo", "acordo homologado"),
             "Extinto sem resolução de mérito": ("extinto", "extinta", "extincao", "extinto sem merito",
                                                 "sem resolucao de merito"),
             "Arquivado / desistência": ("desistencia", "arquivamento", "arquivado"),
             "Incompetência declarada": ("incompetencia", "incompetencia territorial declarada",
                                         "incompetencia territorial")}

PROBABILIDADE = {"Possível": ("possivel",), "Provável": ("provavel",), "Remota": ("remoto", "remota")}

AREA = {"Trabalhista": ("trabalho", "direito do trabalho"),
        "Cível": ("civel", "civil", "direito civil"),
        "Consumidor": ("consumo", "direito do consumidor"),
        "Tributário": ("tributario", "fiscal", "direito tributario"),
        "Administrativo": ("direito administrativo",),
        "Ambiental": ("direito ambiental",),
        "Empresarial": ("direito empresarial", "societario"),
        "Imobiliário": ("imobiliario", "direito imobiliario"),
        "Contratual": ("direito contratual",),
        "Processual": ("direito processual",),
        "Previdenciário": ("previdenciario", "direito previdenciario")}

TIPO_VINCULO = {"recurso": ("apelacao", "recurso especial", "recurso extraordinario"),
                "agravo": ("agravo de instrumento",),
                "apenso": ("apensado", "incidente"),
                "reajuizamento": ("reajuizada", "reajuizado"),
                "mesma_acao": ("mesma acao", "remetida por incompetencia")}

# "Momento atual do processo" (quadro-resumo do modelo A). categoria: onde o processo está.
# ativo=False: o processo não conta como ativo nos indicadores.
MOMENTO_ATUAL = {
    "AGUARDANDO CITAÇÃO": ("conhecimento", True),
    "AGUARDANDO CITAÇÃO DO RÉU": ("conhecimento", True),
    "AGUARDANDO CITAÇÃO DOS EXECUTADOS": ("execução", True),
    "AGUARDANDO CITAÇÃO POR EDITAL": ("conhecimento", True),
    "AGUARDANDO INTIMAÇÃO DO RÉU": ("conhecimento", True),
    "AGUARDANDO CONTESTAÇÃO": ("conhecimento", True),
    "AGUARDANDO RÉPLICA": ("conhecimento", True),
    "AGUARDANDO AUDIÊNCIA": ("conhecimento", True),
    "AGUARDANDO PROVA PERICIAL": ("conhecimento", True),
    "AGUARDANDO SENTENÇA": ("conhecimento", True),
    "AGUARDANDO JULGAMENTO EM 1º GRAU": ("conhecimento", True),
    "AGUARDANDO JULGAMENTO": ("conhecimento", True),
    "CONCLUSOS PARA DECISÃO": ("conhecimento", True),
    "AGUARDANDO JULGAMENTO DA APELAÇÃO": ("recurso", True),
    "AGUARDANDO JULGAMENTO DO RECURSO": ("recurso", True),
    "AGUARDA-SE JULGAMENTO DO AGRAVO DE INSTRUMENTO": ("recurso", True),
    "CUMPRIMENTO DE SENTENÇA": ("execução", True),
    "AGUARDANDO CONVERSÃO EM PENHORA": ("execução", True),
    "AGUARDANDO PAGAMENTO": ("execução", True),
    "AGUARDANDO PARCELAMENTO DAS CUSTAS": ("conhecimento", True),
    "AGUARDANDO MANIFESTAÇÃO DE TERCEIROS": ("conhecimento", True),
    "AGUARDANDO SUBSTITUIÇÃO PROCESSUAL": ("conhecimento", True),
    "SUSPENSO": ("suspenso", True),
    "TRÂNSITO EM JULGADO": ("encerrado", False),
    "PROCESSO ARQUIVADO": ("encerrado", False),
    "ACORDO HOMOLOGADO": ("encerrado", False),
    "EXTINTO SEM RESOLUÇÃO DE MÉRITO": ("encerrado", False),
}

# Matérias dos pedidos (ponto de partida; WS-1/WS-16 ampliam). valor: (tema, classe, entra nos rankings)
MATERIA = {
    "Horas extras e reflexos": ("Jornada", "Mérito", True),
    "Intervalo intra/interjornada": ("Jornada", "Mérito", True),
    "Repouso semanal / feriados": ("Jornada", "Mérito", True),
    "Adicional noturno": ("Jornada", "Mérito", True),
    "Tempo de espera": ("Jornada", "Mérito", True),
    "Controle de jornada": ("Jornada", "Processual", False),
    "Adicional de insalubridade": ("Saúde e segurança", "Mérito", True),
    "Adicional de periculosidade": ("Saúde e segurança", "Mérito", True),
    "Dano material / pensionamento": ("Saúde e segurança", "Mérito", True),
    "Dano estético": ("Saúde e segurança", "Mérito", True),
    "Doença ocupacional / acidente (declaratório)": ("Saúde e segurança", "Mérito", True),
    "Estabilidade (indenização)": ("Estabilidades e afastamentos", "Mérito", True),
    "Limbo previdenciário": ("Estabilidades e afastamentos", "Mérito", True),
    "Salário-maternidade (indenização)": ("Estabilidades e afastamentos", "Mérito", True),
    "Acúmulo / desvio de função": ("Remuneração e benefícios", "Mérito", True),
    "Dano moral": ("Dano moral", "Mérito", True),
    "Honorários advocatícios": ("Acessórios", "Acessório", False),
    "Encargos (INSS/IR/custas) no valor da causa": ("Acessórios", "Acessório", False),
    "Consignação de verbas rescisórias": ("Acessórios", "Processual", False),
    "Outros": ("Acessórios", "Acessório", False),
}
MATERIA_SINONIMOS = {
    "Horas extras e reflexos": ("horas extras", "horas extra", "hora extra", "sobrejornada"),
    "Intervalo intra/interjornada": ("intervalo intrajornada", "intervalo interjornada", "intrajornada", "interjornada"),
    "Adicional de insalubridade": ("insalubridade",),
    "Adicional de periculosidade": ("periculosidade",),
    "Acúmulo / desvio de função": ("acumulo de funcao", "acumulo de funcoes", "desvio de funcao", "plus salarial"),
    "Dano moral": ("danos morais", "indenizacao por dano moral"),
    "Estabilidade (indenização)": ("estabilidade", "gestante"),
}

VOCABULARIOS = {
    "polo": POLO, "situacao": SITUACAO, "fase": FASE, "resultado": RESULTADO, "probabilidade": PROBABILIDADE,
    "area": AREA, "tipo_vinculo": TIPO_VINCULO,
    "momento_atual": {k: () for k in MOMENTO_ATUAL},
    "materia": {k: MATERIA_SINONIMOS.get(k, ()) for k in MATERIA},
}


def _indice(vocabulario):
    indice = {}
    for canonico, sinonimos in vocabulario.items():
        for forma in (canonico, *sinonimos):
            indice.setdefault(_chave(forma), set()).add(canonico)
    return indice


_INDICES = {}


def normalizar(nome_vocabulario, texto):
    """Valor canônico do vocabulário para um rótulo solto, ou None.

    1) igualdade depois de tirar acento, caixa e pontuação final;
    2) o rótulo contém, ou está contido em, exatamente UM valor/sinônimo
       (com pelo menos 6 letras, para não casar sigla solta);
    3) ambíguo ou desconhecido: None (quem chama decide: avisar e deixar vazio).
    """
    chave = _chave(texto)
    if not chave:
        return None
    if nome_vocabulario not in _INDICES:
        _INDICES[nome_vocabulario] = _indice(VOCABULARIOS[nome_vocabulario])
    indice = _INDICES[nome_vocabulario]
    if chave in indice:
        achados = indice[chave]
        return next(iter(achados)) if len(achados) == 1 else None
    candidatos = {c for forma, cs in indice.items() if len(forma) >= 6 and (forma in chave or chave in forma)
                  for c in cs}
    return next(iter(candidatos)) if len(candidatos) == 1 else None


def momento_ativo(momento):
    """True/False se o momento atual conta como processo ativo; None se desconhecido."""
    dados = MOMENTO_ATUAL.get(momento)
    return dados[1] if dados else None


def categoria_do_momento(momento):
    dados = MOMENTO_ATUAL.get(momento)
    return dados[0] if dados else None
