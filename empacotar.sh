#!/bin/bash
# Gera dist/relatorio-andamentos.zip para levar a outra máquina ou publicar no Hub.
# NUNCA inclui dados de clientes: projetos/, ensaio/, data/, diagnósticos, ambiente Python.
set -e
cd "$(dirname "$0")"
rm -rf dist/relatorio-andamentos dist/relatorio-andamentos.zip && mkdir -p dist/relatorio-andamentos
rsync -a \
  --exclude '.venv' --exclude 'projetos' --exclude 'ensaio' --exclude 'data' --exclude 'dist' \
  --exclude '__pycache__' --exclude '*.pyc' --exclude '.DS_Store' --exclude '*.log' --exclude 'hub' \
  --exclude 'revisar.command' --exclude 'cadastro.command' --exclude 'config.json' \
  ./ dist/relatorio-andamentos/
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
# conferência: nada de cliente pode ter entrado no pacote
# (nomes dos clientes cadastrados neste Mac + qualquer número de processo; só o modelo 0000000-00... e os
# números sintéticos dos testes, 1234567-... a 1234570-..., são permitidos)
NOMES=$(cat projetos/*/clientes.json 2>/dev/null | python3 -c "import json,sys,re
txt=sys.stdin.read(); objs=re.findall(r'\"nome\": \"([^\"]+)\"', txt)
print('|'.join(re.escape(n.split()[0]) for n in objs if len(n.split()[0]) > 3))")
PADRAO="\b[0-9]{7}-[0-9]{2}\.[0-9]{4}\.[0-9]\.[0-9]{2}\.[0-9]{4}\b${NOMES:+|$NOMES}"
ACHADOS=$(grep -rIn -E "$PADRAO" dist/relatorio-andamentos --exclude=empacotar.sh 2>/dev/null | grep -v -E "0000000-00\.0000\.0\.00\.0000|9999999-99\.9999\.9\.99\.9999|123456[7-9]-|1234570-" || true)
if [ -n "$ACHADOS" ]; then
  echo "$ACHADOS" | cut -c1-200
  echo "ATENÇÃO: o pacote contém nome de cliente ou número de processo (arquivos acima). Revise antes de publicar."
  exit 1
fi
(cd dist && zip -qr relatorio-andamentos.zip relatorio-andamentos)
echo "Pacote: dist/relatorio-andamentos.zip ($(du -h dist/relatorio-andamentos.zip | cut -f1))"
