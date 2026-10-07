"""Importado ANTES de qualquer módulo da ferramenta em todos os testes.
Aponta dados, carteira e clientes para uma pasta temporária e PARA tudo se
algum caminho ainda apontar para os arquivos reais (em 03/10/2026 um teste
gravou em clientes.json e carteira.json reais; isto impede que se repita)."""
import os
import sys
import tempfile
from pathlib import Path

if "RELATORIO_TESTE_TMP" not in os.environ:
    os.environ["RELATORIO_TESTE_TMP"] = tempfile.mkdtemp(prefix="relatorio-teste-")
TMP = Path(os.environ["RELATORIO_TESTE_TMP"])
os.environ["RELATORIO_DATA"] = str(TMP / "data")
os.environ["RELATORIO_CARTEIRA"] = str(TMP / "carteira.json")
os.environ["RELATORIO_CLIENTES"] = str(TMP / "clientes.json")
os.environ["RELATORIO_PROJETOS"] = str(TMP / "projetos")  # comum.criar_projeto nunca toca o projetos/ real
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import comum  # noqa: E402

for caminho in (comum.DATA, comum.CARTEIRA_FILE, comum.CLIENTES_FILE, comum.PROJETOS_DIR, comum.ATUAL_FILE):
    if not str(Path(caminho).resolve()).startswith(str(TMP.resolve())):
        raise SystemExit(f"TESTE ABORTADO: {caminho} aponta para fora da pasta temporária.")
