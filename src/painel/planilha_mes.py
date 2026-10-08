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
from painel.base import WINDOWS, _dentro, _ir, _msg, ajuda


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
                    return _ir("/planilha", "Envie a planilha do relatório anterior (ou indique-a em Configuração). "
                                            "Ela é a base da planilha nova.")
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
        if not aprovados:
            agora = ("Ainda não há andamento aprovado. Vá primeiro a <a href='/atualizar'>Atualizar</a> (para buscar) e a "
                     "<a href='/'>Revisar</a> (para aprovar). Você pode gerar a planilha assim mesmo, mas ela só renova a data "
                     "de \"sem atualizações\".")
        elif not modelo:
            agora = ("Escolha abaixo a planilha do relatório anterior (ou indique-a em <a href='/config'>Configuração</a>) e "
                     "clique em <b>Gerar planilha</b>.")
        else:
            agora = "Confira a quantidade de andamentos aprovados e clique em <b>Gerar planilha</b>. Depois abra o arquivo e confira antes de enviar."
        gerador = "Finder" if not WINDOWS else "Explorador de Arquivos"
        h = [cabecalho("planilha"), "<h1>Planilha do mês</h1>", _msg(),
             "<div class='caixa'><b>O que fazer agora</b>"
             + ajuda("A planilha do mês é feita no seu computador, a partir da planilha do mês passado e dos andamentos que você aprovou. "
                     "Nada é enviado à internet e a planilha antiga não é alterada.")
             + f"<p>{agora}</p></div>",
             f"<form class='caixa' method='post' enctype='multipart/form-data' "
             "onsubmit=\"return confirm('Gerar a planilha agora? A nova planilha vira a referência do próximo mês e a data do "
             "último relatório passa a ser a de hoje.')\">"
             f"{oculto}"
             f"<p><b>{aprovados}</b> andamento(s) aprovado(s) para entrar na planilha."
             + ajuda("Só entram andamentos que você aprovou em Revisar. Os rascunhos e os descartados ficam de fora.") + "</p>"
             f"<p class='dica'>Referência atual: {html.escape(Path(modelo).name) if modelo else 'nenhuma'}"
             f"{'' if not modelo or Path(modelo).exists() else ' (arquivo não encontrado)'}"
             + ajuda("É a planilha que serve de base. Vem da tela Configuração, ou da última planilha gerada aqui. Para trocá-la, "
                     "envie outra no campo abaixo.") +
             ". A planilha nova é uma cópia dela com os andamentos aprovados acrescentados na coluna Andamentos da aba "
             "Processos; gráficos, tabelas dinâmicas e o resto ficam iguais.</p>"
             "<p>Usar outra planilha como referência: <input type='file' name='modelo' accept='.xlsx'>"
             + ajuda("Opcional. Se escolher um arquivo, ele é usado como base só desta vez (e a planilha gerada vira a nova referência). "
                     "Tem de ser .xlsx com a aba \"Processos\" no modelo do escritório; se não for, o programa avisa e nada é gerado.") + "</p>"
             "<p><label><input type='checkbox' name='sem_novidade' value='1' checked> renovar \"Até DD/MM/AAAA sem atualizações\" "
             "nos processos sem andamento aprovado</label>"
             + ajuda("Nos processos acompanhados que não tiveram andamento aprovado, troca a data da frase \"Até ... sem atualizações\" pela "
                     "de hoje. Desmarque se quiser que esses processos fiquem exatamente como estavam.") + "</p>"
             "<button class='principal'>Gerar planilha</button>"
             + ajuda("Cria um arquivo novo (a antiga não muda) na pasta de relatórios deste relatório. Ele passa a ser a referência do próximo "
                     "mês e a data do último relatório vira a de hoje. Isso não se desfaz sozinho, mas a planilha antiga continua intacta.")
             + "</form>",
             "<h2>Planilhas geradas</h2>", "<ul>"]
        for a in arquivos:
            rel = html.escape(str(a.relative_to(comum.RELATORIOS_DIR)))
            h.append(f"<li><a href='/relatorio?p={rel}'>{html.escape(a.name)}</a> "
                     f"<form style='display:inline' method='post' action='/mostrar'>{oculto}<input type='hidden' name='p' value='{rel}'>"
                     f"<button>Mostrar no {gerador}</button>"
                     + ajuda("Abre a pasta do computador com o arquivo já selecionado. Não envia nada para fora.")
                     + "</form></li>")
        h.append("</ul>" if arquivos else "<li class='vazio'>Nenhuma ainda. Quando você gerar a primeira, ela aparece aqui para baixar.</li></ul>")
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
