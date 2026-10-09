"""Atualizar: busca de andamentos e conferência como tarefas em segundo plano (/atualizar,
/tarefa, /interromper). A tarefa em andamento fica em painel.base.TAREFA."""
import datetime
import html
import os
import re
import signal
import subprocess
import sys
from pathlib import Path

from flask import abort, redirect, request

import comum
from painel.base import TAREFA, WINDOWS, _ir, _msg, _tarefa_rodando


def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"

    @app.get("/atualizar")
    def atualizar():
        proj = comum.projeto()
        ultimo = proj.get("ultimo_relatorio", "")
        primeira = not comum.load_json(comum.ESTADO_FILE, {})
        h = [cabecalho("atualizar"), "<h1>Atualizar andamentos</h1>", _msg(),
             "<div class='caixa'><b>Tem um relatório pronto (Word ou planilha)?</b> Use o "
             "<a href='/fluxo/atualizar'>fluxo de atualização por arquivo</a>: ele lê o relatório, pergunta a data-base, "
             "mostra o que mudou e faz a coleta. Para passar um relatório atual para os modelos novos (texto simplificado, "
             "planilha ou painel), use <a href='/migracao'>Migrar de modelo</a>.</div>"]
        if TAREFA:
            rodando = _tarefa_rodando()
            log = Path(TAREFA["log"]).read_text(encoding="utf-8", errors="replace")[-12000:] if Path(TAREFA["log"]).exists() else ""
            estado = "em andamento" if rodando else f"concluída (código {TAREFA['proc'].returncode})"
            h.append(f"<div class='caixa'><b>{html.escape(TAREFA['descricao'])}</b> · relatório "
                     f"{html.escape(TAREFA['nome'])} · {estado} · início {TAREFA['inicio']}"
                     f"<pre class='log' id='log'>{html.escape(log)}</pre>")
            if rodando:
                h.append(f"<form method='post' action='/interromper'>{oculto}<button>Interromper</button></form>"
                         "<script>setTimeout(()=>location.reload(),3000);"
                         "const l=document.getElementById('log');l.scrollTop=l.scrollHeight;</script>")
            else:
                h.append("<script>const l=document.getElementById('log');l.scrollTop=l.scrollHeight;</script>"
                         "<a href='/'>Ir para a revisão</a>")
            h.append("</div>")
        bloqueado = "disabled" if _tarefa_rodando() else ""
        from painel.base import _ia_local_pronta
        if not _ia_local_pronta():
            h.append("<div class='alerta'>A IA local ainda não está instalada: a atualização coleta tudo normalmente, mas os "
                     "documentos entram na revisão sem resumo. <a href='/ia'>Instalar a IA local</a></div>")
        h.append(f"<form class='caixa' method='post' action='/tarefa'>{oculto}<input type='hidden' name='tipo' value='rodada'>"
                 "<b>Buscar andamentos no jus.br</b><p class='dica'>Entra com o certificado (janela minimizada no canto), "
                 "lê andamentos e documentos novos de cada processo, tira print e resume com a IA local. "
                 "Ao terminar, os rascunhos aparecem em Revisar.</p>"
                 + (f"<p>Primeira atualização deste relatório: considerar como novo o que veio depois de "
                    f"<input type='date' name='desde' value='{html.escape(ultimo)}'> (data do último relatório enviado). "
                    "Sem data, o programa lê e baixa os "
                    "<input type='number' name='historico' value='5' min='0' max='200' style='width:4em'> andamentos e "
                    "documentos mais recentes de cada processo (0 = só registrar o que já existe, sem baixar nada).</p>"
                    if primeira else "")
                 + f"<button class='principal' {bloqueado}>Atualizar</button></form>")
        h.append(f"<form class='caixa' method='post' action='/tarefa'>{oculto}<input type='hidden' name='tipo' value='conferencia'>"
                 "<b>Conferência</b><p class='dica'>Sem IA. Separa, por responsável, os andamentos e documentos dos últimos "
                 "<input type='text' name='dias' value='7' size='3'> dias que ainda não entraram em relatório aprovado, "
                 "com PDFs e prints, para revisão manual.</p>"
                 f"<button {bloqueado}>Conferir</button></form>")
        return "".join(h)

    @app.post("/tarefa")
    def tarefa():
        token_ok()
        if _tarefa_rodando():
            return _ir("/atualizar", "Já há uma tarefa em andamento. Aguarde ou interrompa.")
        tipo = request.form.get("tipo")
        raiz = comum.RAIZ
        py = [sys.executable, "-u"]
        if tipo == "rodada":
            args = py + [str(raiz / "src" / "rodar.py"), "--projeto", comum.PROJETO]
            if request.form.get("desde"):
                a, m, d = request.form["desde"].split("-")
                args += ["--desde", f"{d}/{m}/{a}"]
            elif request.form.get("historico", "").strip().isdigit():  # 1ª atualização sem data: quantos mais recentes
                args += ["--historico", request.form["historico"].strip()]
            descricao = "Atualização no jus.br"
        elif tipo == "teste_acesso":
            args, descricao = py + [str(raiz / "src" / "coletor.py"), "--testar-login"], "Teste de acesso ao jus.br"
        elif tipo == "ia":
            args, descricao = py + [str(raiz / "src" / "ia_local.py"), "--instalar"], "Instalação da IA local"
        elif tipo == "conferencia":
            dias = re.sub(r"\D", "", request.form.get("dias", "7")) or "7"
            args = py + [str(raiz / "src" / "conferencia.py"), "--projeto", comum.PROJETO, "--dias", dias, "--sem-abrir"]
            descricao = f"Conferência ({dias} dias)"
        else:
            abort(400)
        logs = (comum.DATA if comum.PROJETO else comum.PROJETOS_DIR) / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        log = logs / f"{datetime.datetime.now():%Y%m%d-%H%M%S}-{tipo}.log"
        ambiente = {k: v for k, v in os.environ.items() if not k.startswith("RELATORIO_")}
        ambiente.update(PYTHONUNBUFFERED="1")
        if comum.PROJETO:
            ambiente["RELATORIO_PROJETO"] = comum.PROJETO
        separado = ({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {"start_new_session": True})
        proc = subprocess.Popen(args, cwd=raiz / "src", env=ambiente, stdout=log.open("w", encoding="utf-8"),
                                stderr=subprocess.STDOUT, **separado)
        TAREFA.clear()
        TAREFA.update(proc=proc, log=str(log), descricao=descricao, nome=comum.projeto().get("nome", comum.PROJETO or "-"),
                      inicio=f"{datetime.datetime.now():%H:%M}")
        return redirect({"teste_acesso": "/acesso", "ia": "/ia"}.get(tipo, "/atualizar"))

    @app.post("/interromper")
    def interromper():
        token_ok()
        if _tarefa_rodando():
            if WINDOWS:  # encerra o processo e os filhos (navegador)
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(TAREFA["proc"].pid)], capture_output=True)
            else:
                os.killpg(os.getpgid(TAREFA["proc"].pid), signal.SIGTERM)
        return _ir("/atualizar", "Tarefa interrompida. O que já foi coletado fica salvo.")
