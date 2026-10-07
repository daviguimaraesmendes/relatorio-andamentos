#!/bin/bash
# Gera dist/relatorio-andamentos.zip para levar a outra máquina ou publicar no Hub.
# NUNCA inclui dados de clientes: projetos/, ensaio/, data/, diagnósticos, ambiente Python.
#
# O que entra: o código (src/, inclusive src/modelos/ com os modelos sanitizados), os testes, a documentação do
# usuário (README.md, docs/), os instaladores e os arquivos de configuração de exemplo.
# O que NÃO entra: dados e ambiente (projetos/, ensaio/, data/, .venv, dist/), os protótipos (spikes/), pastas de
# ferramentas (.git, .claude), arquivos pessoais (config.json, revisar.command, cadastro.command), os documentos
# internos de coordenação da Fase 2 (docs/fase2/BRIEFING-AGENTES.md e WORKSTREAMS.md) e arquivos de teste
# grandes (tests/fixtures com mais de 1 MB).
#
# Depois de copiar, o script confere o pacote (mesma regra do tests/test_confidencialidade.py): número de processo
# fora do modelo (0000000-00... e 9999999-99...) e dos sintéticos dos testes (1234567-... a 1234570-...), nome de
# cliente cadastrado neste computador, CPF/CNPJ/e-mail reais, segredos, certificados, referência externa em HTML
# de modelo. O texto dentro de .docx/.xlsx também é lido. Se achar algo, recusa gerar o pacote.
# Só precisa de bash e python3 (a cópia e o .zip são feitos pelo próprio Python).
set -e
cd "$(dirname "$0")"
rm -rf dist/relatorio-andamentos dist/relatorio-andamentos.zip && mkdir -p dist/relatorio-andamentos

# 1) copia o que deve ir no pacote
python3 - <<'PY'
import fnmatch
import shutil
from pathlib import Path

DESTINO = Path("dist/relatorio-andamentos")
NA_RAIZ = {".venv", "venv", "projetos", "ensaio", "data", "dist", "hub", "spikes", ".claude", ".git"}
ARQUIVOS_NA_RAIZ = {"config.json", "revisar.command", "cadastro.command"}
EM_QUALQUER_LUGAR = ("__pycache__", ".pytest_cache", ".DS_Store", "*.pyc", "*.log")
CAMINHOS = {"docs/fase2/BRIEFING-AGENTES.md", "docs/fase2/WORKSTREAMS.md"}


def ignorar(pasta, nomes):
    pasta = Path(pasta)
    rel = pasta.relative_to(".") if pasta != Path(".") else Path(".")
    fora = set()
    for nome in nomes:
        caminho = (rel / nome).as_posix()
        if rel == Path(".") and (nome in NA_RAIZ or nome in ARQUIVOS_NA_RAIZ):
            fora.add(nome)
        elif caminho in CAMINHOS or any(fnmatch.fnmatch(nome, p) for p in EM_QUALQUER_LUGAR):
            fora.add(nome)
    return fora


DESTINO.mkdir(parents=True, exist_ok=True)
for item in sorted(Path(".").iterdir()):
    if item.name in NA_RAIZ or item.name in ARQUIVOS_NA_RAIZ or any(fnmatch.fnmatch(item.name, p) for p in EM_QUALQUER_LUGAR):
        continue
    if item.is_dir():
        shutil.copytree(item, DESTINO / item.name, symlinks=True, ignore=ignorar)
    else:
        shutil.copy2(item, DESTINO / item.name, follow_symlinks=False)

# arquivos de teste grandes ficam de fora
for grande in sorted((DESTINO / "tests" / "fixtures").rglob("*")) if (DESTINO / "tests" / "fixtures").exists() else []:
    if grande.is_file() and grande.stat().st_size > 1_000_000:
        print(f"  fora do pacote (maior que 1 MB): {grande.relative_to(DESTINO)}")
        grande.unlink()
PY
mkdir -p dist/relatorio-andamentos/projetos
# identificadores do escritório e revisor ficam de fora: cada máquina configura os seus
python3 - <<'PY'
import json
from pathlib import Path
p = Path("dist/relatorio-andamentos/config.exemplo.json")
d = json.loads(p.read_text())
d.update(identificadores_escritorio=[], revisor="")
d.pop("jusbr_autologin", None)
p.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n")
PY

# 2) o pacote tem de ao menos compilar (erro de sintaxe num módulo novo aparece aqui, não na máquina do usuário)
python3 - <<'PY'
import sys
from pathlib import Path
erros = []
for p in sorted(Path("dist/relatorio-andamentos").rglob("*.py")):
    try:
        compile(p.read_bytes(), str(p), "exec")
    except SyntaxError as e:
        erros.append(f"  {p.relative_to('dist/relatorio-andamentos')}:{e.lineno}: {e.msg}")
if erros:
    print("\n".join(erros))
    print("ATENÇÃO: há arquivo .py com erro de sintaxe no pacote (acima).")
    sys.exit(1)
PY

# 3) conferência de confidencialidade (nada de cliente, segredo ou domínio externo pode ter entrado no pacote).
# Os nomes dos clientes cadastrados NESTE Mac (projetos/*/clientes.json, config.json) vêm da raiz do repositório.
# Nome de empresa "suspeito" por heurística só avisa (o teste do repositório é que o barra).
if ! python3 tests/confidencialidade_regras.py dist/relatorio-andamentos --raiz . --sem-heuristica; then
  echo "ATENÇÃO: o pacote contém nome de cliente, número de processo, segredo ou referência externa (itens acima). Revise antes de publicar."
  rm -rf dist/relatorio-andamentos
  exit 1
fi

# 4) o .zip
python3 - <<'PY'
import shutil
shutil.make_archive("dist/relatorio-andamentos", "zip", root_dir="dist", base_dir="relatorio-andamentos")
PY
echo "Pacote: dist/relatorio-andamentos.zip ($(du -h dist/relatorio-andamentos.zip | cut -f1))"
