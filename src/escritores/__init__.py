"""Escritores dos entregáveis da Fase 2 (CONTRATOS.md, seção 5).

    escritores.docx_a      relatório em texto (.docx, modelo A)          WS-6
    escritores.xlsx_b      relatório em planilha (.xlsx, modelo B)       WS-7
    escritores.dashboard   painel autônomo (.html, modelo C)             WS-8

Todos expõem `gravar(molde, estado, destino, **opcoes) -> Resultado` (o do dashboard recebe o `.xlsx` no lugar do
molde). Os submódulos só são importados quando usados (`from escritores import docx_a` ou `escritores.docx_a`),
para que a falta ou o defeito de um escritor não derrube os outros; cada workstream só acrescenta o seu módulo.
"""
import importlib

_MODULOS = ("docx_a", "xlsx_b", "dashboard")


def __getattr__(nome):
    if nome in _MODULOS:
        return importlib.import_module(f"{__name__}.{nome}")
    raise AttributeError(f"module {__name__!r} has no attribute {nome!r}")
