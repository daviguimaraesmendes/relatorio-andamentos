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
os.environ["RELATORIO_VERSAO"] = "teste"   # o cabeçalho do painel não muda a cada versão
os.environ["RELATORIO_DATA"] = str(TMP / "data")
os.environ["RELATORIO_CARTEIRA"] = str(TMP / "carteira.json")
os.environ["RELATORIO_CLIENTES"] = str(TMP / "clientes.json")
os.environ["RELATORIO_PROJETOS"] = str(TMP / "projetos")  # comum.criar_projeto nunca toca o projetos/ real
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import comum  # noqa: E402

for caminho in (comum.DATA, comum.CARTEIRA_FILE, comum.CLIENTES_FILE, comum.PROJETOS_DIR, comum.ATUAL_FILE):
    if not str(Path(caminho).resolve()).startswith(str(TMP.resolve())):
        raise SystemExit(f"TESTE ABORTADO: {caminho} aponta para fora da pasta temporária.")

# O cofre do sistema (Keychain, Gerenciador de Credenciais) REAL nunca é lido nem gravado pelos testes: um cofre em
# memória o substitui. Sem isso, um teste rodando no computador de quem já cadastrou as credenciais (CPF, senha do
# PDPJ, certificado) as leria de verdade, e poderia até tentar um login.
try:
    import keyring
    from keyring.backend import KeyringBackend

    class CofreEmMemoria(KeyringBackend):
        priority = 100

        def __init__(self):
            super().__init__()
            self._dados = {}

        def get_password(self, servico, usuario):
            return self._dados.get((servico, usuario))

        def set_password(self, servico, usuario, senha):
            self._dados[(servico, usuario)] = senha

        def delete_password(self, servico, usuario):
            self._dados.pop((servico, usuario), None)

    keyring.set_keyring(CofreEmMemoria())
except ImportError:  # sem keyring instalado não há cofre real para proteger
    pass
