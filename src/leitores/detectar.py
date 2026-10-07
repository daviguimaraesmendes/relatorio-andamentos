"""Detecção do formato de um relatório existente -- WS-2.

    detectar(caminho) -> "docx_a" | "xlsx_b" | "lista" | "tabela_livre" | "desconhecido"
    diagnosticar(caminho) -> (formato, aviso | None)     # o aviso explica por que é "desconhecido"

A decisão olha o CONTEÚDO, não a extensão (um `.xlsx` renomeado de `.zip` ou um `.docx` corrompido não enganam):

    .docx com blocos de processo (modelo A)                      -> docx_a
    .docx qualquer outro, com números de processo no texto       -> lista
    .xlsx com cabeçalho que tem >= 10 colunas do modelo B        -> xlsx_b
    .xlsx/.csv com cabeçalho com `numero` e >= 2 campos de      -> tabela_livre
        relatório (fora de cliente/polo/parte contrária/...)
    .xlsx/.csv com coluna de números (com ou sem cabeçalho)      -> lista
    texto (.txt, .md, .eml...) com números CNJ                   -> lista
    PDF, .doc/.xls antigos, .ods/.odt, imagem, binário, vazio,
    arquivo corrompido, texto sem número de processo             -> desconhecido (com aviso claro)

Nunca levanta exceção por causa do arquivo.
"""
import zipfile
from pathlib import Path

from . import base, docx_a, grade

FORMATOS = ("docx_a", "xlsx_b", "lista", "tabela_livre")


def _dica(caminho, motivo, codigo="formato_nao_reconhecido", nivel="erro"):
    return "desconhecido", base.aviso(nivel, codigo, Path(caminho).name, motivo)


def diagnosticar(caminho):
    """-> (formato, aviso | None). `aviso` só vem quando o formato é "desconhecido"."""
    caminho = Path(caminho)
    nome = caminho.name
    if not caminho.exists():
        return _dica(caminho, f"O arquivo {nome!r} não existe.", "arquivo_inexistente")
    if not caminho.is_file():
        return _dica(caminho, f"{nome!r} não é um arquivo.", "arquivo_ilegivel")
    try:
        tamanho = caminho.stat().st_size
        with open(caminho, "rb") as f:
            cabeca = f.read(8192)
    except OSError as e:
        return _dica(caminho, f"Não foi possível ler o arquivo ({type(e).__name__}).", "arquivo_ilegivel")
    if tamanho == 0:
        return _dica(caminho, "O arquivo está vazio.", "arquivo_ilegivel")
    if cabeca[:2] == b"PK":
        try:
            with zipfile.ZipFile(str(caminho)) as z:
                nomes = set(z.namelist())
                mimetype = z.read("mimetype").decode("ascii", "ignore") if "mimetype" in nomes else ""
        except Exception as e:      # noqa: BLE001 -- zip quebrado
            return _dica(caminho, f"O arquivo está corrompido ou incompleto ({type(e).__name__}).", "arquivo_ilegivel")
        if "word/document.xml" in nomes:
            return _detectar_docx(caminho)
        if "xl/workbook.xml" in nomes:
            return _detectar_planilha(caminho, xlsx=True)
        if "opendocument" in mimetype:
            return _dica(caminho, "Arquivo do LibreOffice/OpenOffice (.ods/.odt). Abra e salve como .xlsx ou .docx.")
        return _dica(caminho, "Arquivo compactado que não é um documento Word nem uma planilha Excel.")
    if cabeca[:4] == b"%PDF":
        return _dica(caminho, "PDF não é lido como relatório. Use o .docx ou .xlsx do relatório, ou cole os números dos processos em um texto.")
    if cabeca[:4] == b"\xd0\xcf\x11\xe0":
        return _dica(caminho, "Formato antigo do Office (.doc/.xls). Abra e salve como .docx ou .xlsx.")
    if b"\x00" in cabeca or cabeca[:3] in (b"\x89PN", b"\xff\xd8\xff", b"GIF"):
        return _dica(caminho, "Arquivo binário (imagem ou outro formato) que não é um relatório.")
    if caminho.suffix.lower() in (".csv", ".tsv"):
        return _detectar_planilha(caminho, xlsx=False)
    try:
        dados = caminho.read_bytes()
    except OSError as e:
        return _dica(caminho, f"Não foi possível ler o arquivo ({type(e).__name__}).", "arquivo_ilegivel")
    if base.achar_numeros(grade.decodificar_texto(dados)):
        return "lista", None
    return _dica(caminho, "O texto não tem nenhum número de processo no padrão CNJ (NNNNNNN-DD.AAAA.J.TR.OOOO).")


def _detectar_docx(caminho):
    eh_a, erro = docx_a.reconhecer(caminho)
    if erro:
        return "desconhecido", erro
    if eh_a:
        return "docx_a", None
    texto, erro = docx_a.texto_simples(caminho)
    if texto and base.achar_numeros(texto):
        return "lista", None
    return _dica(caminho, "O documento Word não segue o modelo A (tabelas de processo com título 'PROCESSO Nº ...') "
                          "e não tem números de processo no texto.")


def _detectar_planilha(caminho, xlsx):
    if xlsx:
        grades, avisos = grade.carregar_xlsx(caminho, max_linhas=80)
    else:
        grades, avisos = grade.carregar_csv(caminho)
    if not grades:
        return "desconhecido", (avisos[0] if avisos else base.aviso("erro", "arquivo_ilegivel", Path(caminho).name,
                                                                      "A planilha não pôde ser lida."))
    formato = grade.classificar_grades(grades)
    if formato:
        return formato, None
    return _dica(caminho, "A planilha não tem coluna de número de processo nem números no padrão CNJ.")


def detectar(caminho):
    """Formato do arquivo: "docx_a", "xlsx_b", "lista", "tabela_livre" ou "desconhecido"."""
    return diagnosticar(caminho)[0]
