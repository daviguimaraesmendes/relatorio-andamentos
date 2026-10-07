"""Leitor de planilha ou tabela com colunas FORA do padrão (base da tela "Migrar de modelo") -- WS-2.

Funciona com `.xlsx` (todas as abas com cabeçalho e números de processo) e `.csv`. Em vez de exigir os nomes do modelo B,
PROPÕE o mapeamento coluna do arquivo -> campo da ficha, com a confiança de cada escolha, e lista o que não tem destino:

    rel = leitores.ler("planilha-do-cliente.xlsx", formato="tabela_livre")
    rel["mapeamento"]          # [{"aba", "coluna", "campo", "rotulo_campo", "confianca", "aplicado", "candidatos",
                               #   "ambigua", "amostra", "indice"}]
    rel["colunas_sem_destino"] # [{"coluna", "amostra", "aba", "motivo", "candidatos"}]  (nada se perde em silêncio)

Só são lidas sem confirmação as colunas com confiança de 70% ou mais (`aplicado: True`); a tela mostra o resto para o
usuário decidir e chama de novo com o mapeamento corrigido:

    leitores.ler(caminho, formato="tabela_livre",
                 mapeamento={"Requerente": "autores", "Obs.": "observacoes", "Coluna X": None})

`mapeamento` é {cabeçalho como está no arquivo: campo | None} (None = não migrar essa coluna) ou a lista de itens como a
devolvida em `rel["mapeamento"]`. Campos possíveis: as chaves de `ficha.CAMPOS` mais os destinos especiais `numero`,
`andamentos`, `tribunal` e `ativo`; `destinos_possiveis()` lista tudo com rótulos para a tela. Escolha de destino que
não existe vira aviso `mapeamento_invalido` (a escolha automática fica); a mesma escolha para duas colunas, aviso
`coluna_duplicada` (vale a primeira).

Origem dos valores: colunas de julgamento, `humano`; as demais, `migrado` (mesma regra do `xlsx_b`). A coluna de
números pode ser reconhecida pelo CONTEÚDO (números CNJ) quando o cabeçalho não ajuda.
"""
from pathlib import Path

from . import base, grade

destinos_possiveis = grade.destinos_possiveis


def ler(caminho, mapeamento=None):
    """RelatorioLido com `mapeamento` proposto (ou o aplicado, se `mapeamento` foi passado)."""
    caminho = Path(caminho)
    rel = base.novo_relatorio("tabela_livre", caminho.name)
    grades, av = grade.carregar(caminho)
    rel["avisos"].extend(av)
    rel["mapeamento"] = []
    if not grades:
        return base.finalizar(rel)
    candidatas = grade.grades_de_processos(grades)
    if not candidatas:
        rel["avisos"].append(base.aviso("erro", "sem_aba_de_processos", caminho.name,
                                        "Não foi encontrada uma linha de cabeçalho com a coluna do número do processo "
                                        "nem uma coluna com números CNJ."))
        return base.finalizar(rel)
    processos, sem_destino, publico, _ = grade.ler_grades(grades, mapeamento, avisos=rel["avisos"], candidatas=candidatas)
    rel["processos"], rel["colunas_sem_destino"], rel["mapeamento"] = processos, sem_destino, publico
    return base.finalizar(rel)


def propor_mapeamento(caminho):
    """Só o mapeamento proposto (sem tratar os processos): lista como em `rel["mapeamento"]`."""
    return ler(caminho)["mapeamento"]
