"""Planilha do mês: gera a planilha nova a partir da referência (/planilha) e mostra o
arquivo no gerenciador de arquivos (/mostrar)."""
import datetime
import html
import re
import subprocess
from pathlib import Path

from flask import abort, redirect, request

import comum
from comum import eventos
from painel.base import WINDOWS, _dentro, _ir, _msg


def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"

    @app.route("/planilha", methods=["GET", "POST"])
    def planilha_mes():
        import planilha
        import tempfile
        proj = comum.projeto()
        aprovados = sum(e["status"] == "aprovado" for e in eventos())
        if request.method == "POST":
            token_ok()
            arquivo = request.files.get("modelo")
            with tempfile.TemporaryDirectory() as tmp:
                if arquivo and arquivo.filename:
                    if not arquivo.filename.lower().endswith(".xlsx"):
                        return _ir("/planilha", "Envie uma planilha .xlsx.")
                    modelo = Path(tmp) / "modelo.xlsx"
                    arquivo.save(modelo)
                    nome_base = Path(arquivo.filename).stem
                elif proj.get("planilha_modelo") and Path(proj["planilha_modelo"]).exists():
                    modelo = Path(proj["planilha_modelo"])
                    nome_base = modelo.stem
                else:
                    return _ir("/planilha", "Envie a planilha do relatório anterior (ou indique-a em Configuração).")
                nome_base = re.sub(r"\s*-\s*atualizada$", "", re.sub(r"^\d{4}-\d{2}-\d{2} - ", "", nome_base))
                nome = re.sub(r"[^\w .-]", "", nome_base)[:80] or "relatorio"
                destino = comum.RELATORIOS_DIR / "planilhas" / f"{datetime.date.today():%Y-%m-%d} - {nome}.xlsx"
                try:
                    feitos, fora = planilha.gerar(modelo, destino, sem_novidade=bool(request.form.get("sem_novidade")))
                except Exception as erro:  # planilha fora do modelo da aba "Processos" (ex.: de contingências)
                    return _ir("/planilha", f"Não consegui gerar a partir desta planilha: {erro}\n"
                                            "Se ela não segue o modelo da aba Processos, use \"Atualizar por arquivo\" "
                                            "(/fluxo/atualizar) ou \"Migrar de modelo\" (/migracao): lá as colunas são mapeadas.")
            proj.update(planilha_modelo=str(destino), ultimo_relatorio=datetime.date.today().isoformat())
            comum.salvar_projeto(proj)
            msg = f"Planilha gerada: {len(feitos)} processo(s) atualizado(s). Ela passa a ser a referência do próximo mês."
            if fora:
                msg += f"\nAprovados sem linha na planilha (continuam aprovados): {', '.join(fora)}"
            return _ir("/planilha", msg)
        arquivos = sorted((comum.RELATORIOS_DIR / "planilhas").glob("*.xlsx"), reverse=True) \
            if (comum.RELATORIOS_DIR / "planilhas").exists() else []
        modelo = proj.get("planilha_modelo", "")
        h = [cabecalho("planilha"), "<h1>Planilha do mês</h1>", _msg(),
             f"<form class='caixa' method='post' enctype='multipart/form-data'>{oculto}"
             f"<p><b>{aprovados}</b> andamento(s) aprovado(s) para entrar na planilha.</p>"
             f"<p class='dica'>Referência atual: {html.escape(Path(modelo).name) if modelo else 'nenhuma'}"
             f"{'' if not modelo or Path(modelo).exists() else ' (arquivo não encontrado)'}. "
             "A planilha nova é uma cópia dela com os andamentos aprovados acrescentados na coluna Andamentos da aba "
             "Processos; gráficos, tabelas dinâmicas e o resto ficam iguais.</p>"
             "<p>Usar outra planilha como referência: <input type='file' name='modelo' accept='.xlsx'></p>"
             "<p><label><input type='checkbox' name='sem_novidade' value='1' checked> renovar \"Até DD/MM/AAAA sem atualizações\" "
             "nos processos sem andamento aprovado</label></p><button class='principal'>Gerar planilha</button></form>",
             "<h2>Planilhas geradas</h2><ul>"]
        for a in arquivos:
            rel = html.escape(str(a.relative_to(comum.RELATORIOS_DIR)))
            h.append(f"<li><a href='/relatorio?p={rel}'>{html.escape(a.name)}</a> "
                     f"<form style='display:inline' method='post' action='/mostrar'>{oculto}<input type='hidden' name='p' value='{rel}'>"
                     "<button>Mostrar no Finder</button></form></li>")
        h.append("</ul>" if arquivos else "<li class='dica'>Nenhuma ainda.</li></ul>")
        return "".join(h)

    @app.post("/mostrar")
    def mostrar():
        token_ok()
        caminho = comum.RELATORIOS_DIR / request.form.get("p", "")
        if not _dentro(comum.RELATORIOS_DIR, caminho) or not caminho.is_file():
            abort(404)
        if WINDOWS:
            subprocess.run(["explorer", f"/select,{caminho}"], check=False)
        else:
            subprocess.run(["open", "-R", str(caminho)], check=False)
        return redirect("/planilha")
