"""Leitor de listas de processos (entrada mais simples) -- WS-2. Evolução de `carteira.ler_lista`, mas devolvendo
`RelatorioLido` (CONTRATOS §4), com avisos estruturados em vez de uma lista solta de números recusados.

Aceita:

- texto livre / e-mail (`.txt`, `.md`, `.eml`, colado em arquivo): todo número no padrão CNJ vira um processo, com ou sem
  pontuação, no meio de frases ("Processo nº ..., em grau de recurso"). `origem_no_arquivo` = "linha N";
- `.csv` com separador `,`, `;` ou tabulação (UTF-8 ou Windows-1252);
- `.xlsx` simples ou bagunçado: título e linhas em branco acima do cabeçalho, cabeçalho fora da primeira linha, número
  misturado com texto na célula, várias abas. Se houver cabeçalho com coluna de número, as outras colunas conhecidas
  (cliente, polo, parte contrária, responsável, contato...) são lidas e as demais vão para `colunas_sem_destino`;
  sem cabeçalho, todo número encontrado em qualquer célula é importado (como em `carteira.ler_lista`);
- `.docx` que não é o modelo A mas contém números de processo (lista em texto simples).

Regras: número com dígito verificador errado é RECUSADO e listado (`numero_dv_invalido`, nível erro; uma vez por número);
o mesmo número repetido num texto é lido uma vez (aviso `numero_repetido`, nível info); em planilha/CSV, o mesmo
número em duas linhas fica nas duas, com aviso `numero_repetido` (nível atenção), porque as linhas podem ter dados
diferentes. O cliente não é deduzido do texto: se a lista não tem coluna de cliente, `cliente` fica vazio.
"""
from pathlib import Path

from . import base, docx_a, grade


def _de_texto(texto, rel, rotulo_linha="linha"):
    vistos, invalidos = {}, set()
    for n, linha in enumerate(texto.splitlines(), 1):
        for o in base.achar_numeros(linha):
            onde = f"{rotulo_linha} {n}"
            if not o["valido"]:
                if o["numero"] not in invalidos:
                    invalidos.add(o["numero"])
                    rel["avisos"].append(base.aviso(
                        "erro", "numero_dv_invalido", onde,
                        f"Número {o['numero']}: o dígito verificador não confere (provável erro de digitação). "
                        "Recusado; confira o número no tribunal.", [o["numero"]]))
            elif o["numero"] in vistos:
                if not vistos[o["numero"]]:
                    vistos[o["numero"]] = True
                    rel["avisos"].append(base.aviso("info", "numero_repetido", onde,
                                                    f"O número {o['numero']} aparece mais de uma vez; foi lido uma só vez.", [o["numero"]]))
            else:
                vistos[o["numero"]] = False
                rel["processos"].append(base.processo_lido(o["numero"], origem_no_arquivo=onde))


def _de_grades(grades, mapeamento, rel):
    candidatas = grade.grades_de_processos(grades)
    if candidatas:
        processos, sem_destino, publico, _ = grade.ler_grades(grades, mapeamento, avisos=rel["avisos"], candidatas=candidatas)
        rel["processos"].extend(processos)
        rel["colunas_sem_destino"].extend(sem_destino)
        rel["mapeamento"] = publico
        return
    # sem cabeçalho: varre todas as células, como carteira.ler_lista
    vistos, invalidos = set(), set()
    for g in grades:
        for i, linha in enumerate(g.linhas):
            for v in linha:
                if not isinstance(v, str):
                    continue
                for o in base.achar_numeros(v):
                    onde = f"aba {g.nome!r}, linha {i + 1}"
                    if not o["valido"]:
                        if o["numero"] not in invalidos:
                            invalidos.add(o["numero"])
                            rel["avisos"].append(base.aviso(
                                "erro", "numero_dv_invalido", onde,
                                f"Número {o['numero']}: o dígito verificador não confere. Recusado.", [o["numero"]]))
                    elif o["numero"] not in vistos:
                        vistos.add(o["numero"])
                        rel["processos"].append(base.processo_lido(o["numero"], origem_no_arquivo=onde))


def ler(caminho, mapeamento=None):
    """RelatorioLido (formato "lista"). Nunca levanta exceção para arquivo ruim."""
    caminho = Path(caminho)
    rel = base.novo_relatorio("lista", caminho.name)
    with open(caminho, "rb") as f:
        cabeca = f.read(4096)
    sufixo = caminho.suffix.lower()
    if cabeca[:2] == b"PK":
        if sufixo == ".docx" or b"word/" in cabeca or sufixo not in (".xlsx", ".xlsm"):
            texto, erro = docx_a.texto_simples(caminho)
            if texto is None:
                grades, av = grade.carregar_xlsx(caminho)
                rel["avisos"].extend(av)
                if grades:
                    _de_grades(grades, mapeamento, rel)
                return base.finalizar(rel)
            _de_texto(texto, rel)
        else:
            grades, av = grade.carregar_xlsx(caminho)
            rel["avisos"].extend(av)
            if grades:
                _de_grades(grades, mapeamento, rel)
    elif sufixo in (".csv", ".tsv"):
        grades, av = grade.carregar_csv(caminho)
        rel["avisos"].extend(av)
        if grades:
            _de_grades(grades, mapeamento, rel)
    else:
        if b"\x00" in cabeca:
            rel["avisos"].append(base.aviso("erro", "arquivo_ilegivel", caminho.name,
                                            "O arquivo parece binário; esperava-se texto com números de processo."))
            return base.finalizar(rel)
        dados, erro = grade._ler_bytes(caminho)
        if erro:
            rel["avisos"].append(erro)
            return base.finalizar(rel)
        _de_texto(grade.decodificar_texto(dados), rel)
    if not rel["processos"] and not any(a["nivel"] == "erro" for a in rel["avisos"]):
        rel["avisos"].append(base.aviso("erro", "formato_nao_reconhecido", caminho.name,
                                        "Nenhum número de processo no padrão CNJ foi encontrado no arquivo."))
    return base.finalizar(rel)
