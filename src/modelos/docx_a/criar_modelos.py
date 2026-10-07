"""Recria os modelos sanitizados do relatório em texto (modelo A): `modelo_a.docx` e `modelo_compacto.docx`.

Os modelos NÃO têm nome de cliente, número de processo (só o de exemplo `0000000-00.0000.0.00.0000`, que o
`empacotar.sh` permite), valor nem texto de processo: só marcadores ("(assunto)", "01/01/2000", "MOMENTO ATUAL"),
UMA linha-modelo no quadro-resumo e UM bloco-modelo. O escritor (`escritores/docx_a.py`) abre o modelo, insere os
processos clonando o bloco e a linha de exemplo e tira os dois exemplos no fim.

Estilos:
    a          o layout do modelo de referência (Arial 11, cabeçalhos cinza, uma informação por linha)
    compacto   Arial 9, margens estreitas, três pares rótulo/valor por linha (mais processos por página)

Os arquivos são determinísticos (sem data de gravação): rodar de novo não muda os bytes do `word/document.xml`.
O escritório pode editar o modelo no Word/Google Docs (fonte, cores, logotipo no cabeçalho), desde que mantenha os
rótulos, o título "PROCESSO Nº ... [ MOMENTO ]" e o quadro de 4 colunas.

Uso (precisa de python-docx, só para montar o esqueleto do pacote):
    python3 src/modelos/docx_a/criar_modelos.py
"""
import sys
from pathlib import Path

PASTA = Path(__file__).resolve().parent
sys.path.insert(0, str(PASTA.parent.parent))      # src/

from escritores import docx_a  # noqa: E402


def main():
    for estilo in docx_a.ESTILOS:
        destino = PASTA / f"modelo_{estilo}.docx"
        docx_a.criar_modelo(estilo, destino)
        print(destino)


if __name__ == "__main__":
    main()
