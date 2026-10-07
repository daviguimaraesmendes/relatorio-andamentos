"""Leitor do modelo B (relatório em planilha `.xlsx`, ~29 colunas por processo) -- WS-2.

O que lê:

- TODAS as abas de processos (ex.: ativos e arquivados; trabalhistas e cíveis). A aba é reconhecida pelo CABEÇALHO
  (uma linha que casa com a coluna de número do processo e com outras colunas conhecidas), nunca pelo nome da aba;
  títulos e linhas em branco acima do cabeçalho são pulados.
- Cada coluna é ligada a um campo da ficha por semelhança do cabeçalho (acento, caixa, pontuação, abreviação, sinônimo;
  ver `grade.py`). Coluna ambígua, repetida ou de baixa confiança NÃO é lida: vai para `colunas_sem_destino` com aviso.
  O mapeamento usado sai em `RelatorioLido["mapeamento"]` (chave aditiva).
- Origem: colunas de julgamento digitadas (`ficha.CAMPOS_DE_JULGAMENTO`: probabilidade, valores estimado/arbitrado/
  execução/acordo, custas, depósitos, garantias, resultado, êxito, trânsito...) entram como `humano`; as demais,
  `migrado`. Célula de FÓRMULA nunca é `humano`. Células de fórmula: vale o valor em cache; sem cache, avisa
  (`formula_sem_valor`; só `info` nas colunas calculadas Ativo, Valor Economizado e Taxa de resolução).
- Valores: dinheiro em texto BR, número ou formato de moeda; datas em texto (DD/MM/AAAA, DD/MM/AA, AAAA-MM-DD, por
  extenso), data do Excel ou número de série; sim/não; porcentagem como fração (ver `base.py`).
- Linhas-marcador ("--- ARQUIVADOS ---") e totais são ignoradas (e listadas em `linhas_ignoradas`); linha com dados e
  sem número válido é recusada e avisada; número com dígito errado é recusado e listado; mesmo número em duas linhas
  ou abas: os dois registros ficam, com aviso `numero_repetido`.
- Várias numerações na mesma célula ("principal; agravo ...; apenso ...") viram principal + vinculados (tipo pelo
  rótulo antes do número).
- Aba de parâmetros (procurada pelo conteúdo, de preferência a de nome "Parâmetros"): `headcount` (nº de funcionários),
  `data_referencia` (também vira `data_base`), `empresas_do_grupo` (lista), `fator_correcao`, e `cliente` (também
  `RelatorioLido["cliente"]`); o que não é reconhecido vai em `parametros["outros"]`. Abas de indicadores, dashboard,
  histórico e quadros são ignoradas com um aviso `aba_ignorada`; fórmulas e gráficos não são lidos.
- `andamentos_texto` é o conteúdo da coluna de andamentos sem a frase final "Até/Em DD/MM/AAAA sem atualizações."
  (a data dela vai em `fecho`); `ultimo_andamento` = maior data dos andamentos (regras em `base.analisar_andamentos`).

Limites: só cabeçalho de uma linha; tabela dinâmica e abas de gráfico não são lidas; planilha protegida por senha e
`.xls` antigo voltam como `arquivo_ilegivel`. Testado só com planilhas fictícias geradas por openpyxl, pelo protótipo
do spike S1 e pelo LibreOffice; arquivos reais do Excel/Google Sheets exportados à mão podem trazer variações novas.
"""
from pathlib import Path

from . import base, grade

ABAS_AUXILIARES = ("indicador", "dashboard", "dinamica", "historico", "campos nao migrados", "grafico", "esboco",
                   "quadro", "resumo", "sumario", "capa")
ROTULOS_PARAMETRO = {
    "headcount": ("headcount", "numero de funcionarios", "funcionarios", "numero de empregados", "empregados",
                  "colaboradores", "numero de colaboradores", "quantidade de funcionarios", "total de funcionarios",
                  "numero de funcionarios do grupo"),
    "data_referencia": ("data de referencia", "data referencia", "data base", "data de corte", "data da base",
                        "referencia"),
    "empresas_do_grupo": ("empresas do grupo", "empresas do grupo economico", "grupo economico", "razoes sociais do grupo",
                          "empresas"),
    "fator_correcao": ("fator de correcao", "fator correcao", "indice de correcao", "fator de atualizacao"),
    "cliente": ("cliente", "nome do cliente", "razao social", "contratante"),
}
CABECALHOS_DE_PARAMETROS = {"parametro", "parametros", "item", "campo", "descricao"}


def _nome_de_aba_auxiliar(nome):
    k = base.chave(nome)
    return any(t in k for t in ABAS_AUXILIARES)


def _qual_parametro(rotulo):
    k = base.chave(rotulo)
    for chave_p, formas in ROTULOS_PARAMETRO.items():
        if k in formas:
            return chave_p
    for chave_p, formas in ROTULOS_PARAMETRO.items():
        if any(len(f) >= 8 and f in k for f in formas):
            return chave_p
    return None


def _lista_de_empresas(valores):
    saida = []
    for v in valores:
        for parte in str(v).replace("\r", "\n").replace("|", ";").replace("\n", ";").split(";"):
            if parte.strip() and parte.strip() not in saida:
                saida.append(parte.strip())
    return saida


def _ler_parametros(g, avisos, parametros, listar_outros):
    """Varre uma aba de parâmetros: rótulo na primeira célula preenchida da linha, valor(es) logo à direita."""
    achados = {}
    linhas = g.linhas
    i = 0
    while i < len(linhas):
        celulas = [(j, v) for j, v in enumerate(linhas[i]) if not base.vazio(v)]
        i += 1
        if not celulas or not isinstance(celulas[0][1], str):
            continue
        j0, rotulo = celulas[0]
        valores = []
        for j, v in celulas[1:]:
            if j != j0 + 1 + len(valores):       # só a sequência contígua à direita do rótulo
                break
            valores.append(v)
        if base.chave(rotulo) in CABECALHOS_DE_PARAMETROS and (not valores or base.chave(valores[0]) in ("valor", "descricao")):
            continue
        parametro = _qual_parametro(rotulo)
        onde = f"aba {g.nome!r}, linha {i}"
        if parametro is None:
            if listar_outros and valores:
                parametros.setdefault("outros", {})[base.limpar_texto(rotulo)] = base.limpar_texto(
                    valores[0].isoformat() if hasattr(valores[0], "isoformat") else valores[0])
            continue
        if parametro in achados:
            continue
        if parametro == "empresas_do_grupo":
            if not valores:                       # lista na vertical, logo abaixo do rótulo
                j_lista = j0
                while i < len(linhas):
                    resto = [(j, v) for j, v in enumerate(linhas[i]) if not base.vazio(v)]
                    if len(resto) == 1 and resto[0][0] in (j0, j0 + 1) and isinstance(resto[0][1], str) \
                            and _qual_parametro(resto[0][1]) is None:
                        valores.append(resto[0][1])
                        i += 1
                    else:
                        break
            achados[parametro] = _lista_de_empresas(valores)
            continue
        if not valores:
            continue
        bruto = valores[0]
        if parametro == "headcount":
            n, problema = base.converter_numero(bruto)
            if n is None or problema:
                avisos.append(base.aviso("atencao", "parametro_invalido", onde,
                                         f"Número de funcionários {base.limpar_texto(bruto)!r} não é um número; ignorado."))
                continue
            achados[parametro] = int(round(n))
        elif parametro == "data_referencia":
            d, problema = base.converter_data(bruto, g.epoch)
            if d is None:
                avisos.append(base.aviso("atencao", "parametro_invalido", onde,
                                         f"Data de referência {base.limpar_texto(bruto)!r} não é uma data válida; ignorada."))
                continue
            achados[parametro] = d
        elif parametro == "fator_correcao":
            n, problema = base.converter_numero(bruto)
            if n is None:
                avisos.append(base.aviso("atencao", "parametro_invalido", onde,
                                         f"Fator de correção {base.limpar_texto(bruto)!r} não é um número; ignorado."))
                continue
            achados[parametro] = n
        else:
            achados[parametro] = base.limpar_texto(bruto)
    return achados


def _parametros(grades, avisos):
    """Procura os parâmetros nas abas que não são de processos. -> (parametros, abas_lidas)"""
    parametros, lidas = {}, []
    candidatas = [g for g in grades if not _nome_de_aba_auxiliar(g.nome)]
    candidatas.sort(key=lambda g: "param" not in base.chave(g.nome))      # a aba "Parâmetros" primeiro
    for g in candidatas:
        achados = _ler_parametros(g, avisos, parametros, listar_outros="param" in base.chave(g.nome))
        if achados:
            lidas.append(id(g))
            for k, v in achados.items():
                parametros.setdefault(k, v)
        elif "param" in base.chave(g.nome):
            lidas.append(id(g))
    return parametros, lidas


def ler(caminho, mapeamento=None):
    """RelatorioLido do modelo B. Nunca levanta exceção para arquivo ruim (aviso `arquivo_ilegivel`)."""
    caminho = Path(caminho)
    rel = base.novo_relatorio("xlsx_b", caminho.name)
    grades, av = grade.carregar_xlsx(caminho)
    rel["avisos"].extend(av)
    if not grades:
        return base.finalizar(rel)
    candidatas = grade.grades_de_processos(grades)
    ids_processos = {id(g) for g, _, _ in candidatas}
    outras = [g for g in grades if id(g) not in ids_processos]
    parametros, lidas = _parametros(outras, rel["avisos"])
    rel["parametros"] = parametros
    rel["cliente"] = parametros.get("cliente")
    rel["data_base"] = parametros.get("data_referencia")
    if not candidatas:
        rel["avisos"].append(base.aviso("erro", "sem_aba_de_processos", caminho.name,
                                        "Nenhuma aba tem uma linha de cabeçalho com a coluna do número do processo e números CNJ abaixo dela."))
        return base.finalizar(rel)
    processos, sem_destino, publico, _ = grade.ler_grades(
        grades, mapeamento, cliente_padrao=rel["cliente"], avisos=rel["avisos"], candidatas=candidatas,
        lidas_de_outro_modo=lidas)
    rel["processos"], rel["colunas_sem_destino"], rel["mapeamento"] = processos, sem_destino, publico
    if rel["data_base"] is None:
        rel["avisos"].append(base.aviso("info", "data_base_ausente", caminho.name,
                                        "A planilha não tem 'Data de referência' nos parâmetros; a data-base ficou em branco."))
    return base.finalizar(rel)
