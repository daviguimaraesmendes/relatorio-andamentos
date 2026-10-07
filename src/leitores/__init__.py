"""Leitores de relatórios existentes (migração) -- WS-2 da Fase 2. Interface de CONTRATOS §4:

    import leitores
    leitores.detectar(caminho)                          -> "docx_a" | "xlsx_b" | "lista" | "tabela_livre" | "desconhecido"
    leitores.ler(caminho, formato=None, mapeamento=None) -> RelatorioLido (dict)
    leitores.diagnosticar(caminho)                      -> (formato, aviso | None)   # por que é "desconhecido"
    leitores.destinos_possiveis()                       -> campos para a tela de mapeamento
    leitores.FORMATOS

`ler` NUNCA levanta exceção por causa do arquivo (inexistente, corrompido, de formato desconhecido): devolve um
RelatorioLido sem processos e com aviso de nível `erro` (`arquivo_inexistente`, `arquivo_ilegivel`,
`formato_nao_reconhecido`...). Ambiguidade, número com dígito errado, repetição, rótulo fora do vocabulário, data ou
valor ilegível viram avisos com `codigo` estável (lista em `base.py`); nada se perde em silêncio (colunas sem destino
ficam em `colunas_sem_destino`).

Módulos:

    detectar      reconhece o formato pelo conteúdo
    docx_a        modelo A (.docx do Google Docs): quadro-resumo + um bloco por processo
    xlsx_b        modelo B (.xlsx de ~29 colunas): todas as abas de processos, parâmetros, fórmulas em cache
    lista         texto/e-mail, .csv, .xlsx simples ou bagunçado, .docx de lista
    tabela_livre  planilha com colunas fora do padrão: mapeamento proposto e corrigível pelo usuário
    grade         planilhas e CSV como grades; mapeador de cabeçalhos; extração de linhas
    base          avisos, números CNJ, conversão de valores, análise do texto de andamentos

Chaves ADITIVAS que os leitores acrescentam ao contrato (nunca obrigatórias): em `RelatorioLido`, `mapeamento`
(planilhas); em `ProcessoLido`, `ativo`, `fecho` (data ISO da frase "sem atualizações" retirada do texto),
`andamentos` (frases datadas) e `momento_qualificador`.
"""
from pathlib import Path

from . import base, docx_a, grade, lista, tabela_livre, xlsx_b
from .detectar import FORMATOS, diagnosticar
from .detectar import detectar as detectar          # noqa: F401  (a função tem o nome do módulo, como pede o contrato)
from .grade import destinos_possiveis

_LEITORES = {"docx_a": docx_a, "xlsx_b": xlsx_b, "lista": lista, "tabela_livre": tabela_livre}


def ler(caminho, formato=None, mapeamento=None):
    """RelatorioLido do arquivo. `formato` força um leitor (padrão: detecta). `mapeamento` só vale para planilhas
    (xlsx_b, tabela_livre, lista): {cabeçalho: campo | None} (ver `tabela_livre`)."""
    caminho = Path(caminho)
    if formato is None:
        formato, motivo = diagnosticar(caminho)
        if formato == "desconhecido":
            rel = base.novo_relatorio("desconhecido", caminho.name)
            rel["avisos"].append(motivo or base.aviso("erro", "formato_nao_reconhecido", caminho.name,
                                                      "Não foi possível reconhecer o formato do arquivo."))
            return base.finalizar(rel)
    if formato not in _LEITORES:
        rel = base.novo_relatorio("desconhecido", caminho.name)
        rel["avisos"].append(base.aviso("erro", "formato_nao_reconhecido", caminho.name,
                                        f"Formato {formato!r} desconhecido; use um de {', '.join(FORMATOS)}."))
        return base.finalizar(rel)
    if not caminho.exists() or not caminho.is_file():
        rel = base.novo_relatorio(formato, caminho.name)
        rel["avisos"].append(base.aviso("erro", "arquivo_inexistente", caminho.name, f"O arquivo {caminho.name!r} não existe."))
        return base.finalizar(rel)
    return _LEITORES[formato].ler(caminho, mapeamento=mapeamento)
