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
from painel.base import TAREFA, WINDOWS, _ir, _msg, _tarefa_rodando, ajuda, volta_para


def registrar(app, TOKEN, cabecalho, token_ok):
    oculto = f"<input type='hidden' name='token' value='{TOKEN}'>"

    @app.get("/atualizar")
    def atualizar():
        proj = comum.projeto()
        ultimo = proj.get("ultimo_relatorio", "")
        primeira = not comum.load_json(comum.ESTADO_FILE, {})
        h = [cabecalho("atualizar"), "<h1>Atualizar andamentos</h1>", _msg(),
             "<div class='caixa'><b>O que fazer agora</b>"
             + ajuda("Esta tela faz a busca simples: lê o jus.br e os TRTs só para consultar. A ferramenta nunca protocola, assina "
                     "nem envia nada aos tribunais. Nada entra no relatório sem a sua aprovação em Revisar.")
             + "<ol style='margin:6px 0'><li>Clique em <b>Atualizar</b> abaixo para buscar os andamentos novos.</li>"
               "<li>Quando a tarefa terminar, vá a <a href='/'>Revisar</a> e aprove o que estiver certo.</li>"
               "<li>No fim do mês, gere a <a href='/planilha'>Planilha</a>.</li></ol>"
             "<p class='dica'>Tem um relatório pronto (Word ou planilha) e quer que o programa o leia e confira com a carteira? Use o "
             "<a href='/fluxo/atualizar'>fluxo guiado de atualização por arquivo</a> "
             + ajuda("O fluxo guiado lê o seu relatório (.docx ou .xlsx), pergunta a data-base, mostra o que mudou e só então faz a coleta. "
                     "O arquivo que você enviar nunca é sobrescrito.")
             + ". Para passar um relatório antigo para os modelos novos, use <a href='/migracao'>Migrar de modelo</a>"
             + ajuda("Converte um relatório de outro formato para os modelos do programa (texto, planilha, painel). Trabalha em cópias: "
                     "o arquivo original não é alterado.") + ".</p></div>"]
        if TAREFA:
            rodando = _tarefa_rodando()
            log = Path(TAREFA["log"]).read_text(encoding="utf-8", errors="replace")[-12000:] if Path(TAREFA["log"]).exists() else ""
            estado = "em andamento" if rodando else f"concluída (código {TAREFA['proc'].returncode})"
            h.append(f"<div class='caixa'><b>{html.escape(TAREFA['descricao'])}</b> · relatório "
                     f"{html.escape(TAREFA['nome'])} · {estado} · início {TAREFA['inicio']}"
                     + ajuda("Aqui está o que o programa vai escrevendo enquanto trabalha. Se pedir captcha ou código, uma faixa vermelha "
                             "aparece no alto da tela: resolva na janela do navegador que se abriu.")
                     + f"<pre class='log' id='log'>{html.escape(log)}</pre>")
            if rodando:
                h.append(f"<form method='post' action='/interromper' onsubmit=\"return confirm('Parar esta tarefa agora? "
                         "O que já foi coletado fica salvo; o restante não será buscado.')\">"
                         f"{oculto}<button>Interromper</button>"
                         + ajuda("Encerra a tarefa e o navegador que ela abriu. O que já foi baixado e gravado continua salvo. "
                                 "A tarefa não continua de onde parou: para o resto, é preciso começar de novo.")
                         + "</form>"
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
        h.append(f"<form class='caixa' method='post' action='/tarefa' onsubmit=\"return confirm('Começar a buscar andamentos agora? "
                 "O programa vai entrar no jus.br com o seu certificado e pode levar vários minutos. O PJe Office precisa estar aberto.')\">"
                 f"{oculto}<input type='hidden' name='tipo' value='rodada'>"
                 "<b>1. Buscar andamentos no jus.br</b>"
                 + ajuda("Entra no jus.br com o certificado e o autenticador, consulta os processos do relatório (também nos TRTs, quando "
                         "for processo trabalhista) e baixa os andamentos e documentos novos. Tira print e resume com a IA do seu "
                         "computador. Só lê: não protocola nem assina nada. Para fora do computador vai só o login e as consultas aos tribunais.")
                 + "<p class='dica'>Uma janela de navegador abre minimizada no canto da tela e fecha sozinha. Deixe o PJe Office aberto. "
                   "Ao terminar, os rascunhos aparecem em Revisar; nada vira relatório sem a sua aprovação.</p>"
                 + (f"<p>Primeira atualização deste relatório: considerar como novo o que veio depois de "
                    f"<input type='date' name='desde' value='{html.escape(ultimo)}'> (data do último relatório enviado)"
                    + ajuda("O programa só traz andamentos posteriores a esta data. Se deixar em branco, ele usa a quantidade ao lado. "
                            "Costuma ser a data do último relatório que você mandou ao cliente.") +
                    ". Sem data, o programa lê e baixa os "
                    "<input type='number' name='historico' value='5' min='0' max='200' style='width:4em'> andamentos e "
                    "documentos mais recentes de cada processo (0 = só registrar o que já existe, sem baixar nada)"
                    + ajuda("Serve para quem não tem data de corte. Cinco costuma bastar para começar; números grandes deixam a busca "
                            "bem mais demorada. Com 0, o programa só anota o que já existe e baixa nada.") + ".</p>"
                    if primeira else "")
                 + f"<button class='principal' {bloqueado}>Atualizar</button>"
                 + ajuda("Começa a busca agora. Pede uma confirmação antes. Só uma tarefa roda por vez, porque todas usam o mesmo certificado.")
                 + "</form>")
        h.append(f"<form class='caixa' method='post' action='/tarefa'>{oculto}<input type='hidden' name='tipo' value='conferencia'>"
                 "<b>2. Conferência semanal (opcional)</b>"
                 + ajuda("Rede de segurança: entra no jus.br, olha o que entrou nos autos nos últimos dias e separa o que ainda não foi para "
                         "um relatório aprovado, com os PDFs e os prints, para você conferir à mão. Não usa IA. Não altera relatório nenhum.")
                 + "<p class='dica'>Separa, por responsável, os andamentos e documentos dos últimos "
                 "<input type='text' name='dias' value='7' size='3' inputmode='numeric'> dias que ainda não entraram em relatório aprovado, "
                 "com PDFs e prints, para revisão manual.</p>"
                 f"<button {bloqueado}>Conferir</button>"
                 + ajuda("Começa a conferência. Os arquivos ficam numa pasta deste computador (data/conferencia). Para os processos "
                         "do TRT a conferência ainda não funciona: eles ficam como \"conferir manualmente\".")
                 + "</form>")
        return "".join(h)

    @app.post("/tarefa")
    def tarefa():
        token_ok()
        if _tarefa_rodando():
            return _ir(volta_para("/atualizar"), "Já há uma tarefa em andamento. Aguarde ou interrompa.")
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
        elif tipo in ("teste_pdpj", "ver_login_pdpj"):
            import pdpj
            bloqueio = pdpj.trava() if tipo == "teste_pdpj" else None
            if bloqueio:  # nunca tenta de novo sozinho: a conta do PDPJ pode bloquear
                return _ir(volta_para("/acesso"), f"Teste não iniciado: a última tentativa falhou em {bloqueio.get('quando', '?')}. "
                                      "Confira os dados e use \"Liberar nova tentativa\" antes de testar de novo.")
            if tipo == "teste_pdpj":
                args, descricao = py + [str(raiz / "src" / "pdpj.py"), "--testar"], "Teste de login no PDPJ (uma tentativa)"
            else:
                args, descricao = py + [str(raiz / "src" / "pdpj.py"), "--inspecionar"], "Tela de login do PDPJ (sem digitar nada)"
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
        return redirect(volta_para(None) or {"teste_acesso": "/acesso", "teste_pdpj": "/acesso", "ver_login_pdpj": "/acesso",
                                              "ia": "/ia"}.get(tipo, "/atualizar"))

    @app.post("/interromper")
    def interromper():
        token_ok()
        if _tarefa_rodando():
            if WINDOWS:  # encerra o processo e os filhos (navegador)
                subprocess.run(["taskkill", "/T", "/F", "/PID", str(TAREFA["proc"].pid)], capture_output=True)
            else:
                os.killpg(os.getpgid(TAREFA["proc"].pid), signal.SIGTERM)
        return _ir("/atualizar", "Tarefa interrompida. O que já foi coletado fica salvo.")
